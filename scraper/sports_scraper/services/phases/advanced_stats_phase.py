"""MLB Statcast advanced stats ingestion phase."""

from __future__ import annotations

from datetime import UTC, datetime

from ...db import db_models
from ...logging import logger


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
    """Phase: MLB Statcast advanced stats ingestion."""
    if config.league_code != "MLB":
        logger.info(
            "advanced_stats_skip_non_mlb",
            run_id=run_id,
            league=config.league_code,
            message="Advanced stats only available for MLB; skipping.",
        )
        return

    adv_run_id = start_job_run("advanced_stats", ["MLB"])
    logger.info(
        "advanced_stats_start",
        run_id=run_id,
        league=config.league_code,
        start_date=str(start),
        end_date=str(end),
        only_missing=config.only_missing,
    )
    try:
        from ..mlb_advanced_stats_ingestion import ingest_advanced_stats_for_game

        with get_session() as session:
            window_start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
            window_end = datetime.combine(end, datetime.max.time(), tzinfo=UTC)

            query = (
                session.query(db_models.SportsGame)
                .join(
                    db_models.SportsLeague,
                    db_models.SportsGame.league_id == db_models.SportsLeague.id,
                )
                .filter(
                    db_models.SportsLeague.code == "MLB",
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
