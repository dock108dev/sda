"""Celery tasks for batch Monte Carlo game simulation and prediction outcomes.

Dispatched from the models UI when a user kicks off batch simulations.
Runs simulations asynchronously and updates DB job rows with results.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections import defaultdict
from datetime import UTC, date, datetime

from app.utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc
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
def batch_simulate_games(self, job_id: int, model_id: str | None = None) -> dict:
    """Run Monte Carlo simulations on upcoming games.

    Loads scheduled/pregame games, builds rolling team profiles,
    and runs the SimulationEngine for each game.

    Args:
        job_id: DB job ID.
        model_id: Optional specific model ID to use instead of
            the active model.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _run_batch_sim(job_id, self.request.id, model_id=model_id)
        )
    finally:
        loop.close()


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
                    # Save predictions + immediately record outcomes for final games
                    await _save_prediction_outcomes(
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


async def _save_prediction_outcomes(
    db: AsyncSession,
    batch_sim_job_id: int,
    sport: str,
    probability_mode: str,
    results: list[dict],
    games_by_id: dict | None = None,
) -> None:
    """Persist per-game predictions; immediately record outcomes for final games.

    If the game is already final (historical backtest), scores and
    correct_winner are filled in right away rather than waiting for the
    periodic ``record_completed_outcomes`` task.
    """
    from datetime import UTC, datetime

    from app.db.analytics import AnalyticsPredictionOutcome

    for game_result in results:
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
            sim_wp_std_dev=game_result.get("home_wp_std_dev"),
            sim_iterations=game_result.get("iterations"),
            sim_score_std_home=game_result.get("score_std_home"),
            sim_score_std_away=game_result.get("score_std_away"),
            profile_games_home=game_result.get("profile_games_home"),
            profile_games_away=game_result.get("profile_games_away"),
            sim_probability_source=game_result.get("probability_source"),
            feature_snapshot=game_result.get("feature_snapshot"),
        )

        # Immediately record outcome if game is already final
        game = games_by_id.get(game_result["game_id"]) if games_by_id else None
        if (
            game is not None
            and game.status in ("final", "archived")
            and game.home_score is not None
            and game.away_score is not None
        ):
            home_win_actual = game.home_score > game.away_score
            predicted_home_win = outcome.predicted_home_wp > 0.5
            actual = 1.0 if home_win_actual else 0.0

            outcome.actual_home_score = game.home_score
            outcome.actual_away_score = game.away_score
            outcome.home_win_actual = home_win_actual
            outcome.correct_winner = predicted_home_win == home_win_actual
            outcome.brier_score = round((outcome.predicted_home_wp - actual) ** 2, 6)
            outcome.outcome_recorded_at = datetime.now(UTC)

        db.add(outcome)


def _get_advanced_stats_model(sport: str):
    """Return the advanced stats ORM model for a sport."""
    if sport == "nba":
        from app.db.nba_advanced import NBAGameAdvancedStats
        return NBAGameAdvancedStats
    if sport == "ncaab":
        from app.db.ncaab_advanced import NCAABGameAdvancedStats
        return NCAABGameAdvancedStats
    if sport == "nhl":
        from app.db.nhl_advanced import NHLGameAdvancedStats
        return NHLGameAdvancedStats
    if sport == "nfl":
        from app.db.nfl_advanced import NFLGameAdvancedStats
        return NFLGameAdvancedStats
    from app.db.mlb_advanced import MLBGameAdvancedStats
    return MLBGameAdvancedStats


async def _try_build_nba_rotation_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Attempt to build starter/bench rotation weights for an NBA game.

    For final games: reconstructs rotation from NBAPlayerAdvancedStats.
    For scheduled/pregame games: uses most recent rotation.

    Returns True if rotation weights were built, False otherwise.
    """
    from app.analytics.services.nba_rotation_service import (
        get_recent_rotation,
        reconstruct_rotation_from_stats,
    )
    from app.analytics.services.nba_rotation_weights import build_rotation_weights

    is_final = game.status in ("final", "archived")

    if is_final:
        home_rotation = await reconstruct_rotation_from_stats(db, game.id, game.home_team_id)
        away_rotation = await reconstruct_rotation_from_stats(db, game.id, game.away_team_id)
    else:
        home_rotation = await get_recent_rotation(db, game.home_team_id, exclude_game_id=game.id)
        away_rotation = await get_recent_rotation(db, game.away_team_id, exclude_game_id=game.id)

    if not home_rotation or not away_rotation:
        return False

    # Get opposing defense ratings for matchup adjustments
    away_def = (away_profile or {}).get("def_rating")
    home_def = (home_profile or {}).get("def_rating")

    home_weights = await build_rotation_weights(
        db, home_rotation, game.home_team_id,
        opposing_def_rating=away_def,
        rolling_window=rolling_window,
    )
    away_weights = await build_rotation_weights(
        db, away_rotation, game.away_team_id,
        opposing_def_rating=home_def,
        rolling_window=rolling_window,
    )

    game_context["home_starter_weights"] = home_weights["starter_weights"]
    game_context["home_bench_weights"] = home_weights["bench_weights"]
    game_context["home_starter_share"] = home_weights["starter_share"]
    game_context["home_ft_pct_starter"] = home_weights["ft_pct_starter"]
    game_context["home_ft_pct_bench"] = home_weights["ft_pct_bench"]

    game_context["away_starter_weights"] = away_weights["starter_weights"]
    game_context["away_bench_weights"] = away_weights["bench_weights"]
    game_context["away_starter_share"] = away_weights["starter_share"]
    game_context["away_ft_pct_starter"] = away_weights["ft_pct_starter"]
    game_context["away_ft_pct_bench"] = away_weights["ft_pct_bench"]

    logger.info(
        "batch_sim_nba_rotation_built",
        extra={
            "game_id": game.id,
            "home_starters": len(home_rotation["starters"]),
            "away_starters": len(away_rotation["starters"]),
            "home_resolved": home_weights["players_resolved"],
            "away_resolved": away_weights["players_resolved"],
            "home_starter_share": home_weights["starter_share"],
            "away_starter_share": away_weights["starter_share"],
        },
    )
    return True


async def _try_build_nfl_drive_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Build drive outcome weights for an NFL game.

    Uses team EPA profiles + defensive boxscore stats to create
    matchup-specific drive outcome probabilities.
    """
    from app.analytics.services.nfl_drive_weights import build_drive_weights

    result = await build_drive_weights(
        db, game, home_profile, away_profile, rolling_window,
    )

    if result is None:
        return False

    game_context["home_drive_weights"] = result["home_drive_weights"]
    game_context["away_drive_weights"] = result["away_drive_weights"]
    game_context["home_xp_pct"] = result["home_xp_pct"]
    game_context["away_xp_pct"] = result["away_xp_pct"]
    game_context["home_fg_pct"] = result["home_fg_pct"]
    game_context["away_fg_pct"] = result["away_fg_pct"]

    logger.info(
        "batch_sim_nfl_drive_weights_built",
        extra={"game_id": game.id},
    )
    return True


async def _try_build_nhl_rotation_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Attempt to build top-line/depth rotation weights for an NHL game."""
    from app.analytics.services.nhl_rotation_service import (
        get_recent_rotation,
        reconstruct_rotation_from_stats,
    )
    from app.analytics.services.nhl_rotation_weights import build_rotation_weights

    is_final = game.status in ("final", "archived")

    if is_final:
        home_rotation = await reconstruct_rotation_from_stats(db, game.id, game.home_team_id)
        away_rotation = await reconstruct_rotation_from_stats(db, game.id, game.away_team_id)
    else:
        home_rotation = await get_recent_rotation(db, game.home_team_id, exclude_game_id=game.id)
        away_rotation = await get_recent_rotation(db, game.away_team_id, exclude_game_id=game.id)

    if not home_rotation or not away_rotation:
        return False

    # Get opposing goalie save% for goal probability adjustments
    away_goalie = away_rotation.get("goalie", {})
    home_goalie = home_rotation.get("goalie", {})
    away_save_pct = away_goalie.get("save_pct") if away_goalie else None
    home_save_pct = home_goalie.get("save_pct") if home_goalie else None

    home_weights = await build_rotation_weights(
        db, home_rotation, game.home_team_id,
        opposing_goalie_save_pct=away_save_pct,
        rolling_window=rolling_window,
    )
    away_weights = await build_rotation_weights(
        db, away_rotation, game.away_team_id,
        opposing_goalie_save_pct=home_save_pct,
        rolling_window=rolling_window,
    )

    game_context["home_starter_weights"] = home_weights["starter_weights"]
    game_context["home_bench_weights"] = home_weights["bench_weights"]
    game_context["home_starter_share"] = home_weights["starter_share"]

    game_context["away_starter_weights"] = away_weights["starter_weights"]
    game_context["away_bench_weights"] = away_weights["bench_weights"]
    game_context["away_starter_share"] = away_weights["starter_share"]

    logger.info(
        "batch_sim_nhl_rotation_built",
        extra={
            "game_id": game.id,
            "home_resolved": home_weights["players_resolved"],
            "away_resolved": away_weights["players_resolved"],
            "home_goalie": away_goalie.get("name") if away_goalie else None,
            "away_goalie": home_goalie.get("name") if home_goalie else None,
        },
    )
    return True


async def _try_build_ncaab_rotation_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Attempt to build starter/bench rotation weights for an NCAAB game."""
    from app.analytics.services.ncaab_rotation_service import (
        get_recent_rotation,
        reconstruct_rotation_from_stats,
    )
    from app.analytics.services.ncaab_rotation_weights import build_rotation_weights

    is_final = game.status in ("final", "archived")

    if is_final:
        home_rotation = await reconstruct_rotation_from_stats(db, game.id, game.home_team_id)
        away_rotation = await reconstruct_rotation_from_stats(db, game.id, game.away_team_id)
    else:
        home_rotation = await get_recent_rotation(db, game.home_team_id, exclude_game_id=game.id)
        away_rotation = await get_recent_rotation(db, game.away_team_id, exclude_game_id=game.id)

    if not home_rotation or not away_rotation:
        return False

    away_def = (away_profile or {}).get("def_rating")
    home_def = (home_profile or {}).get("def_rating")

    home_weights = await build_rotation_weights(
        db, home_rotation, game.home_team_id,
        opposing_def_rating=away_def,
        rolling_window=rolling_window,
    )
    away_weights = await build_rotation_weights(
        db, away_rotation, game.away_team_id,
        opposing_def_rating=home_def,
        rolling_window=rolling_window,
    )

    game_context["home_starter_weights"] = home_weights["starter_weights"]
    game_context["home_bench_weights"] = home_weights["bench_weights"]
    game_context["home_starter_share"] = home_weights["starter_share"]
    game_context["home_ft_pct_starter"] = home_weights["ft_pct_starter"]
    game_context["home_ft_pct_bench"] = home_weights["ft_pct_bench"]
    game_context["home_orb_pct_starter"] = home_weights["orb_pct_starter"]
    game_context["home_orb_pct_bench"] = home_weights["orb_pct_bench"]

    game_context["away_starter_weights"] = away_weights["starter_weights"]
    game_context["away_bench_weights"] = away_weights["bench_weights"]
    game_context["away_starter_share"] = away_weights["starter_share"]
    game_context["away_ft_pct_starter"] = away_weights["ft_pct_starter"]
    game_context["away_ft_pct_bench"] = away_weights["ft_pct_bench"]
    game_context["away_orb_pct_starter"] = away_weights["orb_pct_starter"]
    game_context["away_orb_pct_bench"] = away_weights["orb_pct_bench"]

    logger.info(
        "batch_sim_ncaab_rotation_built",
        extra={
            "game_id": game.id,
            "home_resolved": home_weights["players_resolved"],
            "away_resolved": away_weights["players_resolved"],
        },
    )
    return True


async def _try_build_lineup_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Attempt to build per-batter lineup weights for a game.

    For final games: reconstructs batting order from PBP.
    For scheduled/pregame games: uses most recent lineup + probable pitcher.

    Returns True if lineup weights were successfully built and added to
    ``game_context``, False otherwise (caller should fall back to team-level).
    """
    from app.analytics.services.lineup_fetcher import (
        fetch_probable_starter,
        fetch_recent_lineup,
        get_team_external_ref,
    )
    from app.analytics.services.lineup_reconstruction import (
        get_starting_pitcher,
        reconstruct_lineup_from_pbp,
    )
    from app.analytics.services.lineup_weights import (
        build_lineup_weights,
        pitching_metrics_from_profile,
        regress_pitcher_profile,
    )
    from app.analytics.services.profile_service import get_pitcher_rolling_profile

    fallback_pitcher = {
        "strikeout_rate": 0.22, "walk_rate": 0.08,
        "contact_suppression": 0.0, "power_suppression": 0.0,
    }

    is_final = game.status in ("final", "archived")

    # --- Get lineups ---
    if is_final:
        home_lineup_data = await reconstruct_lineup_from_pbp(
            db, game.id, game.home_team_id,
        )
        away_lineup_data = await reconstruct_lineup_from_pbp(
            db, game.id, game.away_team_id,
        )
    else:
        home_lineup_batters = await fetch_recent_lineup(
            db, game.home_team_id, before_game_id=game.id,
        )
        away_lineup_batters = await fetch_recent_lineup(
            db, game.away_team_id, before_game_id=game.id,
        )
        home_lineup_data = {"batters": home_lineup_batters} if home_lineup_batters else None
        away_lineup_data = {"batters": away_lineup_batters} if away_lineup_batters else None

    if not home_lineup_data or not away_lineup_data:
        logger.info(
            "lineup_build_no_lineup_data",
            extra={
                "game_id": game.id,
                "has_home": bool(home_lineup_data),
                "has_away": bool(away_lineup_data),
                "is_final": is_final,
            },
        )
        return False

    home_batters = home_lineup_data["batters"]
    away_batters = away_lineup_data["batters"]

    if len(home_batters) < 3 or len(away_batters) < 3:
        logger.info(
            "lineup_build_insufficient_batters",
            extra={
                "game_id": game.id,
                "home_batters": len(home_batters),
                "away_batters": len(away_batters),
            },
        )
        return False

    # --- Get starting pitchers ---
    # Away starter faces home lineup; home starter faces away lineup
    away_sp_info: dict | None = None
    home_sp_info: dict | None = None

    if is_final:
        # For final games, get the actual starter from pitcher stats
        away_sp_info = await get_starting_pitcher(db, game.id, game.away_team_id)
        home_sp_info = await get_starting_pitcher(db, game.id, game.home_team_id)
    else:
        # For future games, try MLB Stats API probable pitchers
        from app.utils.datetime_utils import to_et_date
        game_date = to_et_date(game.game_date) if game.game_date else None
        if game_date:
            away_ext = await get_team_external_ref(db, game.away_team_id)
            home_ext = await get_team_external_ref(db, game.home_team_id)
            if away_ext:
                away_sp_info = await fetch_probable_starter(game_date, away_ext)
            if home_ext:
                home_sp_info = await fetch_probable_starter(game_date, home_ext)

    logger.info(
        "lineup_build_pitcher_lookup",
        extra={
            "game_id": game.id,
            "is_final": is_final,
            "home_sp_found": home_sp_info is not None,
            "away_sp_found": away_sp_info is not None,
            "home_sp_name": (home_sp_info or {}).get("name"),
            "away_sp_name": (away_sp_info or {}).get("name"),
        },
    )

    # --- Get pitcher profiles ---
    away_sp_profile = fallback_pitcher
    home_sp_profile = fallback_pitcher
    away_sp_avg_ip: float | None = None
    home_sp_avg_ip: float | None = None

    if away_sp_info:
        raw = await get_pitcher_rolling_profile(
            away_sp_info["external_ref"], game.away_team_id,
            rolling_window=rolling_window, db=db,
        )
        if raw:
            away_sp_avg_ip = away_sp_info.get("avg_ip")
            away_sp_profile = regress_pitcher_profile(raw, away_sp_avg_ip)
        else:
            logger.info(
                "lineup_build_pitcher_profile_empty",
                extra={
                    "game_id": game.id,
                    "side": "away",
                    "pitcher_ref": away_sp_info["external_ref"],
                },
            )

    if home_sp_info:
        raw = await get_pitcher_rolling_profile(
            home_sp_info["external_ref"], game.home_team_id,
            rolling_window=rolling_window, db=db,
        )
        if raw:
            home_sp_avg_ip = home_sp_info.get("avg_ip")
            home_sp_profile = regress_pitcher_profile(raw, home_sp_avg_ip)
        else:
            logger.info(
                "lineup_build_pitcher_profile_empty",
                extra={
                    "game_id": game.id,
                    "side": "home",
                    "pitcher_ref": home_sp_info["external_ref"],
                },
            )

    # Bullpen profiles derived from the OPPOSING team's batting tendencies
    # as a proxy for that team's pitching staff quality.
    # Home batters face the away team's bullpen → derived from away profile.
    # Away batters face the home team's bullpen → derived from home profile.
    away_team_bullpen = pitching_metrics_from_profile(away_profile) or fallback_pitcher
    home_team_bullpen = pitching_metrics_from_profile(home_profile) or fallback_pitcher

    # --- Build per-batter weights ---
    # Home batters face away starter + away team's bullpen
    home_weights = await build_lineup_weights(
        db, home_batters, game.home_team_id,
        opposing_starter_profile=away_sp_profile,
        opposing_bullpen_profile=away_team_bullpen,
        team_profile=home_profile,
        rolling_window=rolling_window,
    )
    # Away batters face home starter + home team's bullpen
    away_weights = await build_lineup_weights(
        db, away_batters, game.away_team_id,
        opposing_starter_profile=home_sp_profile,
        opposing_bullpen_profile=home_team_bullpen,
        team_profile=away_profile,
        rolling_window=rolling_window,
    )

    game_context["home_lineup_weights"] = home_weights["starter_weights"]
    game_context["away_lineup_weights"] = away_weights["starter_weights"]
    game_context["home_bullpen_weights"] = home_weights["bullpen_weights"]
    game_context["away_bullpen_weights"] = away_weights["bullpen_weights"]
    game_context["starter_innings"] = 6.0

    logger.info(
        "batch_sim_lineup_built",
        extra={
            "game_id": game.id,
            "home_batters": len(home_batters),
            "away_batters": len(away_batters),
            "home_resolved": home_weights["batters_resolved"],
            "away_resolved": away_weights["batters_resolved"],
            "home_sp": home_sp_info.get("name") if home_sp_info else None,
            "away_sp": away_sp_info.get("name") if away_sp_info else None,
        },
    )
    return True


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

        # Convert date boundaries to ET so late-night games map correctly.
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

        # Filter to sport's league
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

        # 2. Load team names for display
        team_ids = set()
        for g in upcoming_games:
            team_ids.add(g.home_team_id)
            team_ids.add(g.away_team_id)

        team_stmt = select(SportsTeam).where(SportsTeam.id.in_(list(team_ids)))
        team_result = await db.execute(team_stmt)
        teams = {t.id: t for t in team_result.scalars().all()}

        # 3. Load all historical advanced stats for rolling profiles
        AdvancedStatsModel = _get_advanced_stats_model(sport_lower)
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

        # Build rolling profiles
        game_date_str = str(game.game_date)[:10]  # YYYY-MM-DD
        # Strict cutoff: only use data from games before this date
        profile_cutoff = game_date_str

        home_profile = _build_rolling_profile(
            team_history.get(game.home_team_id, []),
            before_date=profile_cutoff,
            window=rolling_window,
            min_games=3,
            sport=sport_lower,
        )
        away_profile = _build_rolling_profile(
            team_history.get(game.away_team_id, []),
            before_date=profile_cutoff,
            window=rolling_window,
            min_games=3,
            sport=sport_lower,
        )

        # Build game context for SimulationEngine
        game_context: dict = {
            "home_team": home_name,
            "away_team": away_name,
        }

        has_profiles = bool(home_profile and away_profile)
        use_ml = model_id or probability_mode in ("ml", "ensemble")
        lineup_mode = False

        # ----------------------------------------------------------
        # Attempt lineup/rotation-aware simulation
        # NOTE: The outer ``async with sf() as db:`` closes before
        # this loop, so we open a fresh session for DB-dependent
        # lineup/rotation weight building.
        # ----------------------------------------------------------
        try:
            async with sf() as lineup_db:
                if sport_lower == "nba":
                    lineup_mode = await _try_build_nba_rotation_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile,
                        rolling_window,
                    )
                elif sport_lower == "ncaab":
                    lineup_mode = await _try_build_ncaab_rotation_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile,
                        rolling_window,
                    )
                elif sport_lower == "nhl":
                    lineup_mode = await _try_build_nhl_rotation_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile,
                        rolling_window,
                    )
                elif sport_lower == "nfl":
                    lineup_mode = await _try_build_nfl_drive_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile,
                        rolling_window,
                    )
                else:
                    lineup_mode = await _try_build_lineup_weights(
                        lineup_db, game, game_context,
                        home_profile, away_profile,
                        rolling_window,
                    )
        except Exception as exc:
            logger.warning(
                "lineup_weight_build_exception",
                extra={
                    "game_id": game.id,
                    "sport": sport_lower,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

        if not lineup_mode:
            logger.warning(
                "lineup_mode_fallback",
                extra={
                    "game_id": game.id,
                    "sport": sport_lower,
                    "game_status": game.status,
                },
            )
            # Fall back to team-level probability resolution
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
                    extra={
                        "game_id": game.id,
                        "probability_mode": probability_mode,
                        "model_id": model_id,
                    },
                )

        # Log which probability path this game is taking
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
            extra={
                "game_id": game.id,
                "prob_path": _prob_path,
                "lineup_mode": lineup_mode,
                "has_profiles": has_profiles,
            },
        )

        try:
            sim = engine.run_simulation(
                game_context=game_context,
                iterations=iterations,
                use_lineup=lineup_mode,
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

        # Derive accurate probability_source from what actually ran
        if lineup_mode:
            prob_source = "lineup_matchup"
        elif "probability_source" in sim:
            prob_source = sim["probability_source"]
        elif has_profiles:
            prob_source = "team_profile"
        else:
            prob_source = "league_defaults"

        # Build feature snapshot from profiles for model-odds pipeline
        feature_snap = None
        if home_profile or away_profile:
            feature_snap = {
                "home": home_profile,
                "away": away_profile,
            }

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
            # Sim observability for model-odds pipeline
            "home_wp_std_dev": sim.get("home_wp_std_dev"),
            "iterations": sim.get("iterations"),
            "score_std_home": sim.get("score_std_home"),
            "score_std_away": sim.get("score_std_away"),
            "profile_games_home": _count_profile_games(
                team_history, game.home_team_id, profile_cutoff, rolling_window,
            ),
            "profile_games_away": _count_profile_games(
                team_history, game.away_team_id, profile_cutoff, rolling_window,
            ),
            "feature_snapshot": feature_snap,
        }
        if "event_summary" in sim:
            game_result["event_summary"] = sim["event_summary"]

        # Score distribution: top 10 most likely final scores
        score_dist = sim.get("score_distribution", {})
        if score_dist:
            top_scores = sorted(score_dist.items(), key=lambda x: x[1], reverse=True)[:10]
            game_result["score_distribution"] = dict(top_scores)
            game_result["most_common_scores"] = [
                {"score": s, "probability": round(p, 4)} for s, p in top_scores
            ]

        sim_results.append(game_result)

    logger.info(
        "batch_sim_complete",
        extra={"game_count": len(sim_results), "sport": sport},
    )

    # Build batch summary and sanity warnings
    batch_summary, batch_warnings = _build_batch_summary(sim_results)

    # Build a game lookup so outcome recording can fill in scores immediately
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


def _build_batch_summary(
    sim_results: list[dict],
) -> tuple[dict | None, list[str]]:
    """Compute batch-level summary stats and sanity warnings."""
    success = [r for r in sim_results if "error" not in r and r.get("home_win_probability") is not None]
    if not success:
        return None, []

    n = len(success)
    avg_home_score = sum(r.get("average_home_score", 0) or 0 for r in success) / n
    avg_away_score = sum(r.get("average_away_score", 0) or 0 for r in success) / n
    home_wins = sum(1 for r in success if (r.get("home_win_probability", 0) or 0) > 0.5)

    # WP distribution buckets
    wp_dist = {"50-55": 0, "55-60": 0, "60-70": 0, "70+": 0}
    for r in success:
        wp = max(r.get("home_win_probability", 0) or 0, r.get("away_win_probability", 0) or 0) * 100
        if wp >= 70:
            wp_dist["70+"] += 1
        elif wp >= 60:
            wp_dist["60-70"] += 1
        elif wp >= 55:
            wp_dist["55-60"] += 1
        else:
            wp_dist["50-55"] += 1

    # Collect per-game event summaries to compute aggregate
    event_summaries = [r.get("event_summary") for r in success if r.get("event_summary")]
    avg_pa = 0.0
    if event_summaries:
        avg_pa = sum(
            (es.get("home", {}).get("avg_pa", 0) + es.get("away", {}).get("avg_pa", 0)) / 2
            for es in event_summaries
        ) / len(event_summaries)

    batch_summary = {
        "avg_runs_per_team": round((avg_home_score + avg_away_score) / 2, 1),
        "avg_total_per_game": round(avg_home_score + avg_away_score, 1),
        "avg_pa_per_team": round(avg_pa, 1) if avg_pa else None,
        "home_win_rate": round(home_wins / n, 3),
        "wp_distribution": wp_dist,
    }

    # Sanity warnings — aggregate event stats across all games, not just first
    from app.analytics.core.simulation_analysis import check_batch_sanity
    aggregate_events = _aggregate_event_summaries(event_summaries) if event_summaries else None
    warnings = check_batch_sanity(success, aggregate_events)

    return batch_summary, warnings


def _aggregate_event_summaries(
    summaries: list[dict],
) -> dict:
    """Average per-game event summaries into a single batch-level summary.

    Produces the same shape as a single-game ``event_summary`` so it can
    be passed directly to ``check_simulation_sanity()``.
    """
    n = len(summaries)
    if n == 0:
        return {}

    def _avg_team(side: str) -> dict:
        teams = [s.get(side, {}) for s in summaries]
        avg = lambda key: round(sum(t.get(key, 0) for t in teams) / n, 1)  # noqa: E731
        rates = [t.get("pa_rates", {}) for t in teams]
        avg_rate = lambda key: round(sum(r.get(key, 0) for r in rates) / n, 3)  # noqa: E731
        return {
            "avg_pa": avg("avg_pa"),
            "avg_hits": avg("avg_hits"),
            "avg_hr": avg("avg_hr"),
            "avg_bb": avg("avg_bb"),
            "avg_k": avg("avg_k"),
            "avg_runs": avg("avg_runs"),
            "pa_rates": {
                "k_pct": avg_rate("k_pct"),
                "bb_pct": avg_rate("bb_pct"),
                "single_pct": avg_rate("single_pct"),
                "double_pct": avg_rate("double_pct"),
                "triple_pct": avg_rate("triple_pct"),
                "hr_pct": avg_rate("hr_pct"),
                "out_pct": avg_rate("out_pct"),
            },
        }

    games = [s.get("game", {}) for s in summaries]
    avg_game = lambda key: round(sum(g.get(key, 0) for g in games) / n, 3)  # noqa: E731

    return {
        "home": _avg_team("home"),
        "away": _avg_team("away"),
        "game": {
            "avg_total_runs": round(sum(g.get("avg_total_runs", 0) for g in games) / n, 1),
            "median_total_runs": round(sum(g.get("median_total_runs", 0) for g in games) / n, 0),
            "extra_innings_pct": avg_game("extra_innings_pct"),
            "shutout_pct": avg_game("shutout_pct"),
            "one_run_game_pct": avg_game("one_run_game_pct"),
        },
    }


def _count_profile_games(
    team_history: dict[int, list[tuple[str, object]]],
    team_id: int,
    cutoff: str,
    window: int,
) -> int | None:
    """Count games used in a team's rolling profile for observability."""
    if team_id not in team_history:
        return None
    prior = [s for d, s in team_history[team_id] if d < cutoff]
    return len(prior[-window:])


# ---------------------------------------------------------------------------
# Shared helpers — imported from _training_helpers
# ---------------------------------------------------------------------------

from app.tasks._training_helpers import (  # noqa: E402
    build_rolling_profile as _build_rolling_profile_mlb,
)


def _nba_stats_to_metrics(stats) -> dict:
    """Convert NBAGameAdvancedStats row to a flat metrics dict."""
    return {
        "off_rating": float(stats.off_rating or 114.0),
        "def_rating": float(stats.def_rating or 114.0),
        "net_rating": float(stats.net_rating or 0.0),
        "pace": float(stats.pace or 100.0),
        "efg_pct": float(stats.efg_pct or 0.54),
        "ts_pct": float(stats.ts_pct or 0.58),
        "tov_pct": float(stats.tov_pct or 0.13),
        "orb_pct": float(stats.orb_pct or 0.25),
        "ft_rate": float(stats.ft_rate or 0.27),
        "fg3_pct": float(stats.fg3_pct or 0.35),
        "ft_pct": float(stats.ft_pct or 0.78),
        "ast_pct": float(stats.ast_pct or 0.60),
    }


def _nfl_stats_to_metrics(stats) -> dict:
    """Convert NFLGameAdvancedStats row to a flat metrics dict."""
    return {
        "epa_per_play": float(stats.epa_per_play or 0.0),
        "pass_epa": float(stats.pass_epa or 0.0),
        "rush_epa": float(stats.rush_epa or 0.0),
        "success_rate": float(stats.success_rate or 0.45),
        "pass_success_rate": float(stats.pass_success_rate or 0.45),
        "rush_success_rate": float(stats.rush_success_rate or 0.40),
        "explosive_play_rate": float(stats.explosive_play_rate or 0.08),
        "avg_cpoe": float(stats.avg_cpoe or 0.0),
        "total_plays": float(stats.total_plays or 60),
        "pass_plays": float(stats.pass_plays or 35),
        "rush_plays": float(stats.rush_plays or 25),
    }


def _nhl_stats_to_metrics(stats) -> dict:
    """Convert NHLGameAdvancedStats row to a flat metrics dict."""
    return {
        "xgoals_for": float(stats.xgoals_for or 2.8),
        "xgoals_against": float(stats.xgoals_against or 2.8),
        "corsi_pct": float(stats.corsi_pct or 0.50),
        "fenwick_pct": float(stats.fenwick_pct or 0.50),
        "shooting_pct": float(stats.shooting_pct or 9.0),
        "save_pct": float(stats.save_pct or 91.0),
        "pdo": float(stats.pdo or 100.0),
        "shots_for": float(stats.shots_for or 30),
        "shots_against": float(stats.shots_against or 30),
    }


def _ncaab_stats_to_metrics(stats) -> dict:
    """Convert NCAABGameAdvancedStats row to a flat metrics dict."""
    return {
        "off_rating": float(stats.off_rating or 105.0),
        "def_rating": float(stats.def_rating or 105.0),
        "net_rating": float(stats.net_rating or 0.0),
        "pace": float(stats.pace or 68.0),
        "off_efg_pct": float(stats.off_efg_pct or 0.50),
        "off_tov_pct": float(stats.off_tov_pct or 0.17),
        "off_orb_pct": float(stats.off_orb_pct or 0.28),
        "off_ft_rate": float(stats.off_ft_rate or 0.30),
        "def_efg_pct": float(stats.def_efg_pct or 0.50),
        "def_tov_pct": float(stats.def_tov_pct or 0.17),
        "def_orb_pct": float(stats.def_orb_pct or 0.28),
        "fg_pct": float(stats.fg_pct or 0.44),
        "three_pt_pct": float(stats.three_pt_pct or 0.34),
        "ft_pct": float(stats.ft_pct or 0.70),
    }


def _build_rolling_profile(
    team_games: list[tuple[str, object]],
    *,
    before_date: str,
    window: int,
    min_games: int = 5,
    sport: str = "mlb",
) -> dict | None:
    """Sport-aware rolling profile builder."""
    if sport in ("nba", "ncaab", "nhl", "nfl"):
        converter = {
            "nba": _nba_stats_to_metrics,
            "ncaab": _ncaab_stats_to_metrics,
            "nhl": _nhl_stats_to_metrics,
            "nfl": _nfl_stats_to_metrics,
        }[sport]
        prior = [stats for date_str, stats in team_games if date_str < before_date]
        if len(prior) < min_games:
            return None
        recent = prior[-window:]
        all_metrics = [converter(s) for s in recent]
        aggregated: dict[str, float] = {}
        for key in all_metrics[0]:
            values = [m[key] for m in all_metrics if key in m]
            if values:
                aggregated[key] = round(sum(values) / len(values), 4)
        return aggregated
    return _build_rolling_profile_mlb(
        team_games, before_date=before_date, window=window, min_games=min_games,
    )
