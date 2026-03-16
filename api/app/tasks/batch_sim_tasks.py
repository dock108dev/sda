"""Celery tasks for batch Monte Carlo game simulation and prediction outcomes.

Dispatched from the models UI when a user kicks off batch simulations.
Runs simulations asynchronously and updates DB job rows with results.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.celery_app import celery_app

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Batch simulation task
# ---------------------------------------------------------------------------


@celery_app.task(name="batch_simulate_games", bind=True, max_retries=0)
def batch_simulate_games(self, job_id: int) -> dict:
    """Run Monte Carlo simulations on upcoming games.

    Loads scheduled/pregame games, builds rolling team profiles,
    and runs the SimulationEngine for each game.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_batch_sim(job_id, self.request.id))
    finally:
        loop.close()


async def _run_batch_sim(job_id: int, celery_task_id: str | None = None) -> dict:
    """Async implementation of batch simulation."""
    from app.db.analytics import AnalyticsBatchSimJob

    async with _task_db() as sf:
        run_id = await _start_job_run(
            sf, "analytics_batch_sim", celery_task_id,
            summary_data={"analytics_job_id": job_id},
        )

        async with sf() as db:
            job = await db.get(AnalyticsBatchSimJob, job_id)
            if job is None:
                await _complete_job_run(sf, run_id, "error", "job_not_found")
                return {"error": "job_not_found", "job_id": job_id}

            job.status = "running"
            if celery_task_id:
                job.celery_task_id = celery_task_id
            await db.commit()

        try:
            result = await _execute_batch_sim(
                sf=sf,
                sport=job.sport,
                probability_mode=job.probability_mode,
                iterations=job.iterations,
                rolling_window=getattr(job, "rolling_window", 30),
                date_start=job.date_start,
                date_end=job.date_end,
            )
        except Exception as exc:
            logger.exception("batch_sim_failed", extra={"job_id": job_id})
            async with sf() as db:
                job = await db.get(AnalyticsBatchSimJob, job_id)
                if job:
                    job.status = "failed"
                    job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    job.completed_at = datetime.now(UTC)
                    await db.commit()
            await _complete_job_run(sf, run_id, "error", str(exc)[:500])
            return {"error": str(exc), "job_id": job_id}

        async with sf() as db:
            job = await db.get(AnalyticsBatchSimJob, job_id)
            if job:
                if "error" in result:
                    job.status = "failed"
                    job.error_message = result.get("error", "unknown")
                else:
                    job.status = "completed"
                    job.game_count = result.get("game_count")
                    job.results = result.get("results")
                    # Save individual predictions for outcome tracking
                    await _save_prediction_outcomes(
                        db, job_id, job.sport, job.probability_mode, result.get("results") or []
                    )
                job.completed_at = datetime.now(UTC)
                await db.commit()

        summary = {"analytics_job_id": job_id, "game_count": result.get("game_count")}
        final_status = "error" if "error" in result else "success"
        await _complete_job_run(sf, run_id, final_status, summary_data=summary)

    return result


async def _save_prediction_outcomes(
    db: AsyncSession,
    batch_sim_job_id: int,
    sport: str,
    probability_mode: str,
    results: list[dict],
) -> None:
    """Persist per-game predictions from a batch sim for later outcome matching."""
    from app.db.analytics import AnalyticsPredictionOutcome

    for game_result in results:
        # Skip error-only entries from failed per-game simulations
        if "error" in game_result or "home_win_probability" not in game_result:
            continue
        outcome = AnalyticsPredictionOutcome(
            game_id=game_result["game_id"],
            sport=sport,
            batch_sim_job_id=batch_sim_job_id,
            home_team=game_result["home_team"],
            away_team=game_result["away_team"],
            predicted_home_wp=game_result["home_win_probability"],
            predicted_away_wp=game_result["away_win_probability"],
            predicted_home_score=game_result.get("average_home_score"),
            predicted_away_score=game_result.get("average_away_score"),
            probability_mode=probability_mode,
            game_date=game_result.get("game_date"),
        )
        db.add(outcome)


async def _execute_batch_sim(
    *,
    sf,
    sport: str,
    probability_mode: str,
    iterations: int,
    rolling_window: int,
    date_start: str | None,
    date_end: str | None,
) -> dict:
    """Run simulations on upcoming games using rolling team profiles."""
    from sqlalchemy import select

    from app.analytics.core.simulation_engine import SimulationEngine
    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame, SportsTeam

    if sport.lower() != "mlb":
        return {"error": "only_mlb_supported"}

    async with sf() as db:
        # 1. Find games to simulate
        # When a date range is provided, include all games (historical + future).
        # Without dates, default to upcoming (scheduled/pregame) from today.
        game_stmt = select(SportsGame).order_by(SportsGame.game_date.asc())

        if date_start:
            dt_start = datetime.strptime(date_start, "%Y-%m-%d").replace(tzinfo=UTC)
            game_stmt = game_stmt.where(SportsGame.game_date >= dt_start)
        else:
            # No start date — only upcoming games
            game_stmt = game_stmt.where(
                SportsGame.status.in_(["scheduled", "pregame"]),
                SportsGame.game_date >= datetime.now(UTC).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
            )
        if date_end:
            dt_end = datetime.strptime(date_end, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
            game_stmt = game_stmt.where(SportsGame.game_date <= dt_end)

        # Filter to MLB games via league join
        from app.db.sports import SportsLeague
        mlb_league = await db.execute(
            select(SportsLeague.id).where(SportsLeague.code == "MLB")
        )
        mlb_league_id = mlb_league.scalar_one_or_none()
        if mlb_league_id:
            game_stmt = game_stmt.where(SportsGame.league_id == mlb_league_id)

        game_result = await db.execute(game_stmt)
        upcoming_games = game_result.scalars().all()

        if not upcoming_games:
            return {"error": "no_games_found", "game_count": 0, "results": []}

        # 2. Load team names for display
        team_ids = set()
        for g in upcoming_games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)

        team_stmt = select(SportsTeam).where(SportsTeam.id.in_(list(team_ids)))
        team_result = await db.execute(team_stmt)
        teams = {t.id: t for t in team_result.scalars().all()}

        # 3. Load all historical advanced stats for rolling profiles
        all_stats_stmt = (
            select(MLBGameAdvancedStats)
            .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
            .where(SportsGame.status == "final")
            .order_by(SportsGame.game_date.asc())
        )
        stats_result = await db.execute(all_stats_stmt)
        all_stats = stats_result.scalars().all()

        # Index by game_id
        stats_by_game: dict[int, list] = defaultdict(list)
        for s in all_stats:
            stats_by_game[s.game_id].append(s)

        # Get dates for all games with stats
        all_game_ids = list(stats_by_game.keys())
        game_dates: dict[int, str] = {}
        if all_game_ids:
            dates_stmt = select(SportsGame.id, SportsGame.game_date).where(
                SportsGame.id.in_(all_game_ids)
            )
            dates_result = await db.execute(dates_stmt)
            for gid, gdate in dates_result:
                game_dates[gid] = str(gdate)

        # Build per-team chronological history
        team_history: dict[int, list[tuple[str, object]]] = defaultdict(list)
        for game_id, stats_list in stats_by_game.items():
            gdate = game_dates.get(game_id, "")
            for s in stats_list:
                team_history[s.team_id].append((gdate, s))

        for tid in team_history:
            team_history[tid].sort(key=lambda x: x[0])

    # 4. Run simulations for each upcoming game
    engine = SimulationEngine(sport)
    sim_results = []

    for game in upcoming_games:
        home_team = teams.get(game.home_team_id)
        away_team = teams.get(game.away_team_id)
        home_name = home_team.name if home_team else f"Team {game.home_team_id}"
        away_name = away_team.name if away_team else f"Team {game.away_team_id}"

        # Build rolling profiles
        game_date_str = str(game.game_date)[:10]  # YYYY-MM-DD
        # Strict cutoff: only use data from games before this date
        profile_cutoff = game_date_str

        home_profile = _build_rolling_profile(
            team_history.get(game.home_team_id, []),
            before_date=profile_cutoff,
            window=rolling_window,
            min_games=3,
        )
        away_profile = _build_rolling_profile(
            team_history.get(game.away_team_id, []),
            before_date=profile_cutoff,
            window=rolling_window,
            min_games=3,
        )

        # Build game context for SimulationEngine
        game_context: dict = {
            "home_team": home_name,
            "away_team": away_name,
            "probability_mode": probability_mode,
        }

        # If we have profiles, attach them as probability inputs
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
            logger.warning(
                "batch_sim_game_error",
                extra={"game_id": game.id, "error": str(exc)},
            )
            sim_results.append({
                "game_id": game.id,
                "game_date": game_date_str,
                "home_team": home_name,
                "away_team": away_name,
                "error": str(exc),
            })
            continue

        sim_results.append({
            "game_id": game.id,
            "game_date": game_date_str,
            "home_team": home_name,
            "away_team": away_name,
            "home_win_probability": sim.get("home_win_probability"),
            "away_win_probability": sim.get("away_win_probability"),
            "average_home_score": sim.get("average_home_score"),
            "average_away_score": sim.get("average_away_score"),
            "probability_source": sim.get("probability_source", probability_mode),
            "has_profiles": bool(home_profile and away_profile),
        })

    logger.info(
        "batch_sim_complete",
        extra={"game_count": len(sim_results), "sport": sport},
    )

    return {
        "game_count": len(sim_results),
        "results": sim_results,
    }


# ---------------------------------------------------------------------------
# Shared helpers — imported from _training_helpers
# ---------------------------------------------------------------------------

from app.tasks._training_helpers import (  # noqa: E402
    build_rolling_profile as _build_rolling_profile,
)
