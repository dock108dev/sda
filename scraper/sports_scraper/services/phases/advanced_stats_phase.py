"""Advanced stats ingestion phase (all leagues)."""

from __future__ import annotations

from datetime import UTC, datetime

from ...db import db_models
from ...logging import logger
from ...utils.datetime_utils import start_of_et_day_utc


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
    """Phase: advanced stats ingestion (MLB Statcast, NBA stats.nba.com)."""
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
                    db_models.SportsGame.status == db_models.GameStatus.final.value,
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
            for game in games:
                try:
                    ingest_advanced_stats_for_game(session, game.id)
                    count += 1
                except Exception as exc:
                    logger.warning(
                        "advanced_stats_game_failed",
                        game_id=game.id,
                        error=str(exc),
                    )

            session.commit()

        summary["advanced_stats"] = count
        logger.info(
            "advanced_stats_complete",
            run_id=run_id,
            count=count,
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
