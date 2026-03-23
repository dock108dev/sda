"""Advanced stats ingestion phase (all leagues).

Runs independently of boxscore/PBP phases — populates external IDs
itself so it can be backfilled standalone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ...db import db_models
from ...logging import logger
from ...utils.commit_loop import commit_loop
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

            def _process_game(sess, game):
                result = ingest_advanced_stats_for_game(sess, game.id)
                status = result.get("status", "skipped")
                if status == "skipped":
                    reason = result.get("reason", "unknown")
                    return f"skipped:{reason}"
                return status

            loop = commit_loop(
                session,
                games,
                _process_game,
                batch_size=1,
                label=f"advanced_stats_{config.league_code.lower()}",
                max_consecutive_errors=10,
            )

        summary["advanced_stats"] = loop.success
        summary["advanced_stats_errors"] = loop.errors
        summary["advanced_stats_skipped"] = loop.skipped
        complete_job_run(adv_run_id, "success")
    except Exception as exc:
        logger.exception(
            "advanced_stats_failed",
            run_id=run_id,
            league=config.league_code,
            error=str(exc),
        )
        complete_job_run(adv_run_id, "error", str(exc))
