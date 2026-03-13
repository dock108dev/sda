"""Celery tasks for historical replay of completed MLB games.

Replays finished games using point-in-time state to evaluate model
accuracy against known outcomes.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.celery_app import celery_app
from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db
from app.tasks._training_helpers import build_rolling_profile

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@celery_app.task(name="replay_historical_games", bind=True, max_retries=0)
def replay_historical_games(self, job_id: int) -> dict:
    """Replay completed games for model evaluation."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_replay(job_id, self.request.id))
    finally:
        loop.close()


async def _run_replay(job_id: int, celery_task_id: str | None = None) -> dict:
    """Async implementation of historical replay."""
    from app.db.analytics import AnalyticsReplayJob

    async with _task_db() as sf:
        run_id = await _start_job_run(
            sf, "analytics_replay", celery_task_id,
            summary_data={"replay_job_id": job_id},
        )

        async with sf() as db:
            job = await db.get(AnalyticsReplayJob, job_id)
            if job is None:
                await _complete_job_run(sf, run_id, "error", "job_not_found")
                return {"error": "job_not_found"}

            job.status = "running"
            if celery_task_id:
                job.celery_task_id = celery_task_id
            await db.commit()

        try:
            result = await _execute_replay(sf, job)
        except Exception as exc:
            logger.exception("replay_failed", extra={"job_id": job_id})
            async with sf() as db:
                job = await db.get(AnalyticsReplayJob, job_id)
                if job:
                    job.status = "failed"
                    job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    job.completed_at = datetime.now(UTC)
                    await db.commit()
            await _complete_job_run(sf, run_id, "error", str(exc)[:500])
            return {"error": str(exc)}

        async with sf() as db:
            job = await db.get(AnalyticsReplayJob, job_id)
            if job:
                if "error" in result:
                    job.status = "failed"
                    job.error_message = result.get("error")
                else:
                    job.status = "completed"
                    job.game_count = result.get("game_count")
                    job.results = result.get("results")
                    job.metrics = result.get("metrics")
                job.completed_at = datetime.now(UTC)
                await db.commit()

        summary = {"replay_job_id": job_id, "game_count": result.get("game_count")}
        final_status = "error" if "error" in result else "success"
        await _complete_job_run(sf, run_id, final_status, summary_data=summary)

    return result


async def _execute_replay(sf: Any, job: Any) -> dict:
    """Run replay simulations on completed historical games."""
    from sqlalchemy import select

    from app.analytics.core.simulation_engine import SimulationEngine
    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame, SportsLeague, SportsTeam

    sport = job.sport or "mlb"
    if sport.lower() != "mlb":
        return {"error": "only_mlb_supported"}

    async with sf() as db:
        # Find completed games matching criteria
        game_stmt = (
            select(SportsGame)
            .where(SportsGame.status.in_(["final", "archived"]))
            .order_by(SportsGame.game_date.desc())
        )

        # Filter by MLB league
        mlb_league = await db.execute(
            select(SportsLeague.id).where(SportsLeague.code == "MLB")
        )
        mlb_league_id = mlb_league.scalar_one_or_none()
        if mlb_league_id:
            game_stmt = game_stmt.where(SportsGame.league_id == mlb_league_id)

        # Apply date range
        if job.date_start:
            dt_start = datetime.strptime(job.date_start, "%Y-%m-%d").replace(tzinfo=UTC)
            game_stmt = game_stmt.where(SportsGame.game_date >= dt_start)
        if job.date_end:
            dt_end = datetime.strptime(job.date_end, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
            game_stmt = game_stmt.where(SportsGame.game_date <= dt_end)

        # Apply game count limit
        if job.game_count_requested:
            game_stmt = game_stmt.limit(job.game_count_requested)

        game_result = await db.execute(game_stmt)
        games = game_result.scalars().all()

        if not games:
            return {"error": "no_games_found", "game_count": 0}

        # Load teams
        team_ids = set()
        for g in games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)
        team_result = await db.execute(
            select(SportsTeam).where(SportsTeam.id.in_(list(team_ids)))
        )
        teams = {t.id: t for t in team_result.scalars().all()}

        # Load historical stats for rolling profiles
        all_stats_stmt = (
            select(MLBGameAdvancedStats)
            .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
            .where(SportsGame.status.in_(["final", "archived"]))
            .order_by(SportsGame.game_date.asc())
        )
        stats_result = await db.execute(all_stats_stmt)
        all_stats = stats_result.scalars().all()

        # Build indices
        stats_by_game: dict[int, list] = defaultdict(list)
        for s in all_stats:
            stats_by_game[s.game_id].append(s)

        all_game_ids = list(stats_by_game.keys())
        game_dates: dict[int, str] = {}
        if all_game_ids:
            dates_stmt = select(SportsGame.id, SportsGame.game_date).where(
                SportsGame.id.in_(all_game_ids)
            )
            dates_result = await db.execute(dates_stmt)
            for gid, gdate in dates_result:
                game_dates[gid] = str(gdate)

        team_history: dict[int, list[tuple[str, Any]]] = defaultdict(list)
        for game_id, stats_list in stats_by_game.items():
            gdate = game_dates.get(game_id, "")
            for s in stats_list:
                team_history[s.team_id].append((gdate, s))
        for tid in team_history:
            team_history[tid].sort(key=lambda x: x[0])

    # Run replay simulations
    engine = SimulationEngine(sport)
    rolling_window = job.rolling_window or 30
    iterations = job.iterations or 5000
    probability_mode = job.probability_mode or "ml"

    replay_results = []
    correct_winners = 0
    brier_scores = []
    score_errors = []

    for game in games:
        home_team = teams.get(game.home_team_id)
        away_team = teams.get(game.away_team_id)
        home_name = home_team.name if home_team else f"Team {game.home_team_id}"
        away_name = away_team.name if away_team else f"Team {game.away_team_id}"
        game_date_str = str(game.game_date)

        # Point-in-time profiles (strictly before game)
        home_profile = build_rolling_profile(
            team_history.get(game.home_team_id, []),
            before_date=game_date_str,
            window=rolling_window,
            min_games=3,
        )
        away_profile = build_rolling_profile(
            team_history.get(game.away_team_id, []),
            before_date=game_date_str,
            window=rolling_window,
            min_games=3,
        )

        game_context: dict = {
            "home_team": home_name,
            "away_team": away_name,
            "probability_mode": probability_mode,
        }
        if home_profile and away_profile:
            game_context["profiles"] = {
                "home_profile": {"metrics": home_profile},
                "away_profile": {"metrics": away_profile},
            }

        try:
            sim = engine.run_simulation(
                game_context=game_context,
                iterations=iterations,
            )
        except Exception as exc:
            replay_results.append({
                "game_id": game.id,
                "game_date": game_date_str[:10],
                "home_team": home_name,
                "away_team": away_name,
                "error": str(exc),
            })
            continue

        predicted_home_wp = sim.get("home_win_probability", 0.5)
        predicted_away_wp = sim.get("away_win_probability", 0.5)
        pred_home_score = sim.get("average_home_score")
        pred_away_score = sim.get("average_away_score")

        # Compare to actuals
        actual_home_win = (game.home_score or 0) > (game.away_score or 0)
        predicted_home_win = predicted_home_wp > 0.5
        is_correct = predicted_home_win == actual_home_win

        if is_correct:
            correct_winners += 1

        # Brier score
        brier = (predicted_home_wp - (1.0 if actual_home_win else 0.0)) ** 2
        brier_scores.append(brier)

        # Score error
        if pred_home_score is not None and game.home_score is not None:
            home_err = abs(pred_home_score - game.home_score)
            away_err = abs((pred_away_score or 0) - (game.away_score or 0))
            score_errors.append((home_err + away_err) / 2)

        replay_results.append({
            "game_id": game.id,
            "game_date": game_date_str[:10],
            "home_team": home_name,
            "away_team": away_name,
            "predicted_home_wp": round(predicted_home_wp, 4),
            "predicted_away_wp": round(predicted_away_wp, 4),
            "predicted_home_score": round(pred_home_score, 2) if pred_home_score else None,
            "predicted_away_score": round(pred_away_score, 2) if pred_away_score else None,
            "actual_home_score": game.home_score,
            "actual_away_score": game.away_score,
            "actual_home_win": actual_home_win,
            "correct_winner": is_correct,
            "brier_score": round(brier, 6),
        })

    game_count = len(replay_results)
    valid_count = len([r for r in replay_results if "error" not in r])

    metrics: dict[str, Any] = {
        "game_count": game_count,
        "valid_count": valid_count,
    }
    if valid_count > 0:
        metrics["winner_accuracy"] = round(correct_winners / valid_count, 4)
    if brier_scores:
        metrics["avg_brier_score"] = round(sum(brier_scores) / len(brier_scores), 6)
    if score_errors:
        metrics["avg_score_mae"] = round(sum(score_errors) / len(score_errors), 4)

    return {
        "game_count": game_count,
        "results": replay_results,
        "metrics": metrics,
    }
