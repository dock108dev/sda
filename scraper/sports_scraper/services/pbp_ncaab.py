"""NCAAB play-by-play ingestion via College Basketball Data API."""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..utils.datetime_utils import end_of_et_day_utc

from sqlalchemy import exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..persistence.plays import upsert_plays


def select_games_for_pbp_ncaab_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int, str | None]]:
    """Return game ids, CBB game IDs, and status for NCAAB API play-by-play ingestion.

    NCAAB PBP is fetched via the College Basketball Data API using the CBB game ID
    stored in external_ids['cbb_game_id'].

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have PBP data
        updated_before: Only include games with stale PBP data

    Returns:
        List of (game_id, cbb_game_id, status) tuples for games needing PBP
    """
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NCAAB"
    ).first()
    if not league:
        return []

    # CBB game ID is stored in external_ids JSONB field under 'cbb_game_id' key
    cbb_game_id_expr = db_models.SportsGame.external_ids["cbb_game_id"].astext

    query = session.query(
        db_models.SportsGame.id,
        cbb_game_id_expr.label("cbb_game_id"),
        db_models.SportsGame.status,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        # cbb_game_id is required for CBB API PBP fetch
        cbb_game_id_expr.isnot(None),
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
    results: list[tuple[int, int, str | None]] = []
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
    from ..live.ncaab_constants import NCAAB_MIN_EXPECTED_PLAYS
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

    # Fetch and persist PBP
    client = NCAABLiveFeedClient()
    pbp_games = 0
    pbp_events = 0

    for game_id, cbb_game_id, game_status in games:
        try:
            # Fetch PBP from CBB API
            payload = client.fetch_play_by_play(cbb_game_id, game_status=game_status)

            if not payload.plays:
                logger.warning(
                    "ncaab_pbp_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    cbb_game_id=cbb_game_id,
                )
                continue

            # Validation: Check if game is final and event count is suspiciously low
            game = session.query(db_models.SportsGame).get(game_id)
            if game and game.status == db_models.GameStatus.final.value:
                if len(payload.plays) < NCAAB_MIN_EXPECTED_PLAYS:
                    logger.warning(
                        "ncaab_pbp_insufficient_events",
                        run_id=run_id,
                        game_id=game_id,
                        cbb_game_id=cbb_game_id,
                        play_count=len(payload.plays),
                        expected_min=NCAAB_MIN_EXPECTED_PLAYS,
                    )

            # Persist plays
            inserted = upsert_plays(session, game_id, payload.plays, source="cbb_api")

            if inserted:
                pbp_games += 1
                pbp_events += inserted

                logger.info(
                    "ncaab_pbp_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    cbb_game_id=cbb_game_id,
                    events_inserted=inserted,
                )

        except Exception as exc:
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
