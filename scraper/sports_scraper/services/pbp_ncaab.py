"""NCAAB play-by-play ingestion via College Basketball Data API."""

from __future__ import annotations

from datetime import date, datetime

from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc

from sqlalchemy import exists, not_, or_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger


def select_games_for_pbp_ncaab_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int | None, str | None]]:
    """Return games needing NCAAB PBP ingestion.

    Selects games with either cbb_game_id OR ncaa_game_id — the SSOT
    game_processors handle fallback between the two APIs internally.

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have PBP data
        updated_before: Only include games with stale PBP data

    Returns:
        List of (game_id, cbb_game_id_or_0, status) tuples for games needing PBP.
        cbb_game_id may be 0 for games with only ncaa_game_id.
    """
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NCAAB"
    ).first()
    if not league:
        return []

    cbb_game_id_expr = db_models.SportsGame.external_ids["cbb_game_id"].astext
    ncaa_game_id_expr = db_models.SportsGame.external_ids["ncaa_game_id"].astext

    query = session.query(
        db_models.SportsGame.id,
        cbb_game_id_expr.label("cbb_game_id"),
        db_models.SportsGame.status,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        # Need at least one game ID for data fetching
        or_(cbb_game_id_expr.isnot(None), ncaa_game_id_expr.isnot(None)),
    )

    if only_missing:
        has_pbp = exists().where(db_models.SportsGamePlay.game_id == db_models.SportsGame.id)
        query = query.filter(not_(has_pbp))

    if updated_before:
        has_fresh = exists().where(
            db_models.SportsGamePlay.game_id == db_models.SportsGame.id,
            db_models.SportsGamePlay.updated_at >= updated_before,
        )
        query = query.filter(not_(has_fresh))

    rows = query.all()
    results: list[tuple[int, int | None, str | None]] = []
    for game_id, cbb_game_id, status in rows:
        if cbb_game_id:
            try:
                cbb_id = int(cbb_game_id)
                results.append((game_id, cbb_id, status))
            except (ValueError, TypeError):
                logger.warning(
                    "ncaab_pbp_invalid_game_id",
                    game_id=game_id,
                    cbb_game_id=cbb_game_id,
                )
        else:
            # Game has ncaa_game_id only — process_game_pbp_ncaab handles this
            results.append((game_id, 0, status))
    return results


def ingest_pbp_via_ncaab_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int]:
    """Ingest PBP using the College Basketball Data API.

    Flow (follows NHL pattern):
    1. Populate cbb_game_id for games missing it (via CBB schedule API)
    2. Select games with cbb_game_id that need PBP
    3. Fetch and persist PBP for each game

    Args:
        session: Database session
        run_id: Scrape run ID for logging
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have PBP data
        updated_before: Only include games with stale PBP data

    Returns:
        Tuple of (games_with_pbp, total_events_inserted)
    """
    from ..live.ncaab import NCAABLiveFeedClient
    from .ncaab_game_ids import populate_ncaab_game_ids

    logger.info(
        "ncaab_pbp_ingestion_start",
        run_id=run_id,
        start_date=str(start_date),
        end_date=str(end_date),
        only_missing=only_missing,
    )

    # Step 1: Populate missing CBB game IDs
    populate_ncaab_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )

    # Step 2: Select games for PBP ingestion
    games = select_games_for_pbp_ncaab_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "ncaab_pbp_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0)

    logger.info(
        "ncaab_pbp_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Fetch and persist PBP via SSOT game_processors
    from .game_processors import process_game_pbp_ncaab

    client = NCAABLiveFeedClient()
    pbp_games = 0
    pbp_events = 0

    for game_id, cbb_game_id, game_status in games:
        try:
            game = session.query(db_models.SportsGame).get(game_id)
            if not game:
                continue

            result = process_game_pbp_ncaab(session, game, client=client)

            if result.events_inserted:
                pbp_games += 1
                pbp_events += result.events_inserted

                logger.info(
                    "ncaab_pbp_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    cbb_game_id=cbb_game_id,
                    events_inserted=result.events_inserted,
                )
            elif not result.events_inserted and result.api_calls > 0:
                logger.warning(
                    "ncaab_pbp_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    cbb_game_id=cbb_game_id,
                )

            session.commit()

        except Exception as exc:
            session.rollback()
            logger.warning(
                "ncaab_pbp_fetch_failed",
                run_id=run_id,
                game_id=game_id,
                cbb_game_id=cbb_game_id,
                error=str(exc),
            )
            continue

    logger.info(
        "ncaab_pbp_ingestion_complete",
        run_id=run_id,
        games_processed=pbp_games,
        total_events=pbp_events,
    )

    return (pbp_games, pbp_events)
