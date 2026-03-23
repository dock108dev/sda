"""Advanced stats ingestion phase (all leagues).

Runs independently of boxscore/PBP phases — populates external IDs
itself so it can be backfilled standalone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ...db import db_models
from ...logging import logger
from ...utils.datetime_utils import start_of_et_day_utc


def _populate_external_ids(session, league_code: str, start: date, end: date) -> None:
    """Ensure games have external IDs needed for advanced stats APIs.

    Each league's advanced stats ingestion requires an external game ID
    (nba_game_id, nhl_game_pk, etc.) to fetch data from external sources.
    This step is normally done by the boxscore/PBP phases, but advanced
    stats must be able to run standalone.
    """
    try:
        if league_code == "NBA":
            from ..pbp_nba import populate_nba_game_ids
            populate_nba_game_ids(session, run_id=0, start_date=start, end_date=end)
        elif league_code == "NHL":
            from ..pbp_nhl import populate_nhl_game_ids
            populate_nhl_game_ids(session, run_id=0, start_date=start, end_date=end)
        elif league_code == "MLB":
            from ..mlb_boxscore_ingestion import populate_mlb_game_ids
            populate_mlb_game_ids(session, run_id=0, start_date=start, end_date=end)
        elif league_code == "NCAAB":
            from ..ncaab_game_ids import populate_ncaab_game_ids
            populate_ncaab_game_ids(session, run_id=0, start_date=start, end_date=end)
        # NFL uses espn_game_id populated by calendar polling — no separate populate step
    except Exception as exc:
        logger.warning(
            "advanced_stats_populate_ids_failed",
            league=league_code,
            error=str(exc),
        )


def ingest_advanced_stats(
    run_id: int,
    config,
    summary: dict,
    start: datetime,
    end: datetime,
    updated_before_dt: datetime | None,
    *,
    get_session,
    start_job_run,
    complete_job_run,
) -> None:
    """Phase: advanced stats ingestion (all leagues)."""
    supported_leagues = {"MLB", "NBA", "NHL", "NFL", "NCAAB"}
    if config.league_code not in supported_leagues:
        logger.info(
            "advanced_stats_skip_unsupported",
            run_id=run_id,
            league=config.league_code,
            message=f"Advanced stats not yet available for {config.league_code}; skipping.",
        )
        return

    adv_run_id = start_job_run("advanced_stats", [config.league_code])
    logger.info(
        "advanced_stats_start",
        run_id=run_id,
        league=config.league_code,
        start_date=str(start),
        end_date=str(end),
        only_missing=config.only_missing,
    )
    try:
        import importlib

        _INGESTION_MODULES = {
            "MLB": "mlb_advanced_stats_ingestion",
            "NBA": "nba_advanced_stats_ingestion",
            "NHL": "nhl_advanced_stats_ingestion",
            "NFL": "nfl_advanced_stats_ingestion",
            "NCAAB": "ncaab_advanced_stats_ingestion",
        }
        mod = importlib.import_module(
            f"..{_INGESTION_MODULES[config.league_code]}",
            package="sports_scraper.services.phases",
        )
        ingest_advanced_stats_for_game = mod.ingest_advanced_stats_for_game

        with get_session() as session:
            # Populate external IDs if missing — advanced stats need them
            # to fetch from external APIs (same step boxscore/PBP phases do)
            _populate_external_ids(session, config.league_code, start, end)
            session.commit()

            window_start = start_of_et_day_utc(start)
            window_end = datetime.combine(end, datetime.max.time(), tzinfo=UTC)

            query = (
                session.query(db_models.SportsGame)
                .join(
                    db_models.SportsLeague,
                    db_models.SportsGame.league_id == db_models.SportsLeague.id,
                )
                .filter(
                    db_models.SportsLeague.code == config.league_code,
                    db_models.SportsGame.status.in_([
                        db_models.GameStatus.final.value,
                        db_models.GameStatus.archived.value,
                    ]),
                    db_models.SportsGame.game_date >= window_start,
                    db_models.SportsGame.game_date <= window_end,
                )
            )

            if config.only_missing:
                query = query.filter(db_models.SportsGame.last_advanced_stats_at.is_(None))

            if updated_before_dt:
                query = query.filter(
                    (db_models.SportsGame.last_advanced_stats_at.is_(None))
                    | (db_models.SportsGame.last_advanced_stats_at < updated_before_dt)
                )

            games = query.all()
            count = 0
            errors = 0
            consecutive_failures = 0
            max_consecutive_failures = 5  # Stop if 5 games in a row fail (API likely blocked)

            for game in games:
                if consecutive_failures >= max_consecutive_failures:
                    logger.warning(
                        "advanced_stats_circuit_breaker",
                        run_id=run_id,
                        league=config.league_code,
                        consecutive_failures=consecutive_failures,
                        remaining_games=len(games) - count - consecutive_failures,
                        message="Stopping: too many consecutive failures (API may be blocked)",
                    )
                    break

                try:
                    result = ingest_advanced_stats_for_game(session, game.id)
                    session.commit()
                    if result.get("status") == "success":
                        count += 1
                        consecutive_failures = 0  # Reset on success
                    elif result.get("status") == "error":
                        consecutive_failures += 1
                    # "skipped" doesn't count as failure (missing data, not API issue)
                except Exception as exc:
                    session.rollback()
                    errors += 1
                    consecutive_failures += 1
                    logger.warning(
                        "advanced_stats_game_failed",
                        game_id=game.id,
                        error=str(exc),
                    )

        summary["advanced_stats"] = count
        summary["advanced_stats_errors"] = errors
        logger.info(
            "advanced_stats_complete",
            run_id=run_id,
            count=count,
            errors=errors,
            total_games=len(games),
        )
        complete_job_run(adv_run_id, "success")
    except Exception as exc:
        logger.exception(
            "advanced_stats_failed",
            run_id=run_id,
            league=config.league_code,
            error=str(exc),
        )
        complete_job_run(adv_run_id, "error", str(exc))
