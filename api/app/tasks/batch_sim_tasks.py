"""Celery tasks for batch Monte Carlo game simulation and prediction outcomes.

Dispatched from the models UI when a user kicks off batch simulations.
Runs simulations asynchronously and updates DB job rows with results.

Heavy lifting is split across helper modules:
- ``_batch_sim_helpers``: stats converters, profile builder, serializers
- ``_batch_sim_weights``: sport-specific rotation/lineup weight builders
- ``_batch_sim_enrichment``: line analysis, batch summary, outcome persistence
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.celery_app import celery_app
from app.tasks._batch_sim_enrichment import (
    build_batch_summary,
    enrich_with_closing_lines,
    save_prediction_outcomes,
)
from app.tasks._batch_sim_helpers import (
    build_rolling_profile,
    count_profile_games,
    get_advanced_stats_model,
    serialize_lineup_meta,
)
from app.tasks._batch_sim_weights import (
    try_build_lineup_weights,
    try_build_nba_rotation_weights,
    try_build_ncaab_rotation_weights,
    try_build_nfl_drive_weights,
    try_build_nhl_rotation_weights,
)
from app.utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Celery task entry point
# ---------------------------------------------------------------------------


@celery_app.task(name="batch_simulate_games", bind=True, max_retries=0)
def batch_simulate_games(self, job_id: int, model_id: str | None = None) -> dict:
    """Run Monte Carlo simulations on upcoming games.

    Loads scheduled/pregame games, builds rolling team profiles,
    and runs the SimulationEngine for each game.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _run_batch_sim(job_id, self.request.id, model_id=model_id)
        )
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Async job lifecycle
# ---------------------------------------------------------------------------


async def _run_batch_sim(
    job_id: int,
    celery_task_id: str | None = None,
    *,
    model_id: str | None = None,
) -> dict:
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
                model_id=model_id,
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
                    await save_prediction_outcomes(
                        db, job_id, job.sport, job.probability_mode,
                        result.get("results") or [],
                        games_by_id=result.get("_games_by_id"),
                    )
                job.completed_at = datetime.now(UTC)
                await db.commit()

        summary = {"analytics_job_id": job_id, "game_count": result.get("game_count")}
        final_status = "error" if "error" in result else "success"
        await _complete_job_run(sf, run_id, final_status, summary_data=summary)

    # Strip internal-only keys before returning (ORM objects aren't serializable)
    result.pop("_games_by_id", None)
    return result


# ---------------------------------------------------------------------------
# Core simulation orchestrator
# ---------------------------------------------------------------------------


async def _execute_batch_sim(
    *,
    sf,
    sport: str,
    probability_mode: str,
    iterations: int,
    rolling_window: int,
    date_start: str | None,
    date_end: str | None,
    model_id: str | None = None,
) -> dict:
    """Run simulations on upcoming games using rolling team profiles."""
    from sqlalchemy import select

    from app.analytics.core.simulation_engine import SimulationEngine
    from app.db.sports import SportsGame, SportsLeague, SportsTeam

    sport_lower = sport.lower()
    if sport_lower not in ("mlb", "nba", "ncaab", "nhl", "nfl"):
        return {"error": "sport_not_supported", "supported": ["mlb", "nba", "ncaab", "nhl", "nfl"]}

    async with sf() as db:
        # 1. Find games to simulate
        game_stmt = select(SportsGame).order_by(SportsGame.game_date.asc())

        if date_start:
            game_stmt = game_stmt.where(
                SportsGame.game_date >= start_of_et_day_utc(date.fromisoformat(date_start))
            )
        else:
            game_stmt = game_stmt.where(
                SportsGame.status.in_(["scheduled", "pregame"]),
                SportsGame.game_date >= start_of_et_day_utc(date.today()),
            )
        if date_end:
            game_stmt = game_stmt.where(
                SportsGame.game_date < end_of_et_day_utc(date.fromisoformat(date_end))
            )

        league_code = sport.upper()
        league_result = await db.execute(
            select(SportsLeague.id).where(SportsLeague.code == league_code)
        )
        league_id = league_result.scalar_one_or_none()
        if league_id:
            game_stmt = game_stmt.where(SportsGame.league_id == league_id)

        game_result = await db.execute(game_stmt)
        upcoming_games = game_result.scalars().all()

        if not upcoming_games:
            return {"error": "no_games_found", "game_count": 0, "results": []}

        # 2. Load team names
        team_ids = set()
        for g in upcoming_games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)

        team_stmt = select(SportsTeam).where(SportsTeam.id.in_(list(team_ids)))
        team_result = await db.execute(team_stmt)
        teams = {t.id: t for t in team_result.scalars().all()}

        # 3. Load historical advanced stats for rolling profiles
        AdvancedStatsModel = get_advanced_stats_model(sport_lower)
        all_stats_stmt = (
            select(AdvancedStatsModel)
            .join(SportsGame, SportsGame.id == AdvancedStatsModel.game_id)
            .where(SportsGame.status == "final")
            .order_by(SportsGame.game_date.asc())
        )
        stats_result = await db.execute(all_stats_stmt)
        all_stats = stats_result.scalars().all()

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

        game_date_str = str(game.game_date)[:10]
        profile_cutoff = game_date_str

        home_profile = build_rolling_profile(
            team_history.get(game.home_team_id, []),
            before_date=profile_cutoff, window=rolling_window,
            min_games=3, sport=sport_lower,
        )
        away_profile = build_rolling_profile(
            team_history.get(game.away_team_id, []),
            before_date=profile_cutoff, window=rolling_window,
            min_games=3, sport=sport_lower,
        )

        game_context: dict = {"home_team": home_name, "away_team": away_name}

        has_profiles = bool(home_profile and away_profile)
        use_ml = model_id or probability_mode in ("ml", "ensemble")
        lineup_mode = False
        lineup_meta: dict | None = None

        # Attempt lineup/rotation-aware simulation
        try:
            async with sf() as lineup_db:
                if sport_lower == "nba":
                    lineup_mode = await try_build_nba_rotation_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile, rolling_window,
                    )
                elif sport_lower == "ncaab":
                    lineup_mode = await try_build_ncaab_rotation_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile, rolling_window,
                    )
                elif sport_lower == "nhl":
                    lineup_mode = await try_build_nhl_rotation_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile, rolling_window,
                    )
                elif sport_lower == "nfl":
                    lineup_mode = await try_build_nfl_drive_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile, rolling_window,
                    )
                else:
                    lineup_meta = await try_build_lineup_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile, rolling_window,
                    )
                    lineup_mode = lineup_meta is not None
        except Exception as exc:
            logger.warning(
                "lineup_weight_build_exception",
                extra={
                    "game_id": game.id, "sport": sport_lower,
                    "error": str(exc), "error_type": type(exc).__name__,
                },
            )

        if not lineup_mode:
            logger.warning(
                "lineup_mode_fallback",
                extra={"game_id": game.id, "sport": sport_lower, "game_status": game.status},
            )
            if has_profiles and use_ml:
                game_context["profiles"] = {
                    "home_profile": {"metrics": home_profile},
                    "away_profile": {"metrics": away_profile},
                }
                game_context["probability_mode"] = probability_mode
                if model_id:
                    game_context["_model_id"] = model_id
            elif has_profiles:
                from app.analytics.services.profile_service import profile_to_pa_probabilities
                home_pa = profile_to_pa_probabilities(home_profile)
                away_pa = profile_to_pa_probabilities(away_profile)
                game_context["home_probabilities"] = home_pa
                game_context["away_probabilities"] = away_pa
            elif use_ml:
                game_context["probability_mode"] = probability_mode
                if model_id:
                    game_context["_model_id"] = model_id
                logger.warning(
                    "batch_sim_missing_profiles_for_ml",
                    extra={"game_id": game.id, "probability_mode": probability_mode, "model_id": model_id},
                )

        # Log probability path
        if lineup_mode:
            _prob_path = "lineup_matchup"
        elif has_profiles and use_ml:
            _prob_path = "team_ml"
        elif has_profiles:
            _prob_path = "team_rule_based"
        else:
            _prob_path = "league_defaults"
        logger.info(
            "batch_sim_game_prob_path",
            extra={"game_id": game.id, "prob_path": _prob_path, "lineup_mode": lineup_mode, "has_profiles": has_profiles},
        )

        try:
            sim = engine.run_simulation(
                game_context=game_context, iterations=iterations, use_lineup=lineup_mode,
            )
        except Exception as exc:
            logger.warning("batch_sim_game_error", extra={"game_id": game.id, "error": str(exc)})
            sim_results.append({
                "game_id": game.id, "game_date": game_date_str,
                "home_team": home_name, "away_team": away_name, "error": str(exc),
            })
            continue

        # Derive probability_source
        if lineup_mode:
            prob_source = "lineup_matchup"
        elif "probability_source" in sim:
            prob_source = sim["probability_source"]
        elif has_profiles:
            prob_source = "team_profile"
        else:
            prob_source = "league_defaults"

        feature_snap = {"home": home_profile, "away": away_profile} if home_profile or away_profile else None

        game_result = {
            "game_id": game.id,
            "game_date": game_date_str,
            "home_team": home_name,
            "away_team": away_name,
            "home_win_probability": sim.get("home_win_probability"),
            "away_win_probability": sim.get("away_win_probability"),
            "average_home_score": sim.get("average_home_score"),
            "average_away_score": sim.get("average_away_score"),
            "probability_source": prob_source,
            "has_profiles": has_profiles,
            "home_wp_std_dev": sim.get("home_wp_std_dev"),
            "iterations": sim.get("iterations"),
            "score_std_home": sim.get("score_std_home"),
            "score_std_away": sim.get("score_std_away"),
            "profile_games_home": count_profile_games(team_history, game.home_team_id, profile_cutoff, rolling_window),
            "profile_games_away": count_profile_games(team_history, game.away_team_id, profile_cutoff, rolling_window),
            "feature_snapshot": feature_snap,
        }
        if "event_summary" in sim:
            game_result["event_summary"] = sim["event_summary"]

        if lineup_meta:
            game_result["lineup_info"] = serialize_lineup_meta(lineup_meta)

        score_dist = sim.get("score_distribution", {})
        if score_dist:
            top_scores = sorted(score_dist.items(), key=lambda x: x[1], reverse=True)[:10]
            game_result["score_distribution"] = dict(top_scores)
            game_result["most_common_scores"] = [
                {"score": s, "probability": round(p, 4)} for s, p in top_scores
            ]

        sim_results.append(game_result)

    logger.info("batch_sim_complete", extra={"game_count": len(sim_results), "sport": sport})

    # Enrich with line analysis
    try:
        async with sf() as cl_db:
            await enrich_with_closing_lines(cl_db, sim_results)
    except Exception as exc:
        logger.warning("closing_line_enrichment_failed", extra={"error": str(exc)})

    batch_summary, batch_warnings = build_batch_summary(sim_results)

    games_lookup = {g.id: g for g in upcoming_games}

    result_payload: dict = {
        "game_count": len(sim_results),
        "results": sim_results,
        "_games_by_id": games_lookup,
    }
    if batch_summary:
        result_payload["batch_summary"] = batch_summary
    if batch_warnings:
        result_payload["warnings"] = batch_warnings

    return result_payload
