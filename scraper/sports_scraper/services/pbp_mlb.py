"""MLB play-by-play ingestion via official MLB Stats API (statsapi.mlb.com)."""

from __future__ import annotations

from datetime import date, datetime

from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc

from sqlalchemy import exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger


def select_games_for_pbp_mlb_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int, str | None]]:
    """Return game ids, MLB game PKs, and status for MLB API play-by-play ingestion.

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have PBP data
        updated_before: Only include games with stale PBP data

    Returns:
        List of (game_id, mlb_game_pk, game_status) tuples for games needing PBP
    """
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "MLB"
    ).first()
    if not league:
        return []

    mlb_game_pk_expr = db_models.SportsGame.external_ids["mlb_game_pk"].astext

    query = session.query(
        db_models.SportsGame.id,
        mlb_game_pk_expr.label("mlb_game_pk"),
        db_models.SportsGame.status,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        mlb_game_pk_expr.isnot(None),
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
    results = []
    for game_id, mlb_game_pk, status in rows:
        if mlb_game_pk:
            try:
                mlb_pk = int(mlb_game_pk)
                results.append((game_id, mlb_pk, status))
            except (ValueError, TypeError):
                logger.warning(
                    "mlb_pbp_invalid_game_pk",
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                )
    return results


def ingest_pbp_via_mlb_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int]:
    """Ingest PBP using the official MLB Stats API.

    Flow:
    1. Populate mlb_game_pk for games missing it (via MLB schedule API)
    2. Select games with mlb_game_pk that need PBP
    3. Fetch and persist PBP for each game

    Returns:
        Tuple of (games_with_pbp, total_events_inserted)
    """
    from .mlb_boxscore_ingestion import populate_mlb_game_ids

    # Step 1: Populate missing MLB game IDs
    populate_mlb_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )

    # Step 2: Select games for PBP ingestion
    games = select_games_for_pbp_mlb_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "mlb_pbp_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0)

    logger.info(
        "mlb_pbp_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Step 3: Fetch and persist PBP via SSOT game_processors
    from .game_processors import process_game_pbp_mlb

    pbp_games = 0
    pbp_events = 0

    for game_id, mlb_game_pk, game_status in games:
        try:
            game = session.query(db_models.SportsGame).get(game_id)
            if not game:
                continue

            result = process_game_pbp_mlb(session, game)

            if result.events_inserted:
                pbp_games += 1
                pbp_events += result.events_inserted

                logger.info(
                    "mlb_pbp_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                    events_inserted=result.events_inserted,
                )
            elif not result.events_inserted and result.api_calls > 0:
                logger.warning(
                    "mlb_pbp_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                )

            session.commit()

        except Exception as exc:
            session.rollback()
            logger.warning(
                "mlb_pbp_fetch_failed",
                run_id=run_id,
                game_id=game_id,
                mlb_game_pk=mlb_game_pk,
                error=str(exc),
            )
            continue

    logger.info(
        "mlb_pbp_ingestion_complete",
        run_id=run_id,
        games_processed=pbp_games,
        total_events=pbp_events,
    )

    return (pbp_games, pbp_events)
