"""MLB play-by-play ingestion via official MLB Stats API (statsapi.mlb.com)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..persistence.plays import upsert_plays


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
        db_models.SportsGame.game_date >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
        db_models.SportsGame.game_date <= datetime.combine(end_date, datetime.max.time(), tzinfo=UTC),
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
    from ..live.mlb import MLBLiveFeedClient
    from ..live.mlb_constants import MLB_MIN_EXPECTED_PLAYS
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

    # Step 3: Fetch and persist PBP
    client = MLBLiveFeedClient()
    pbp_games = 0
    pbp_events = 0

    for game_id, mlb_game_pk, game_status in games:
        try:
            payload = client.fetch_play_by_play(mlb_game_pk, game_status=game_status)

            if not payload.plays:
                logger.warning(
                    "mlb_pbp_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                )
                continue

            # Validation: Check if game is final and event count is suspiciously low
            game = session.query(db_models.SportsGame).get(game_id)
            if game and game.status == db_models.GameStatus.final.value and len(payload.plays) < MLB_MIN_EXPECTED_PLAYS:
                logger.warning(
                    "mlb_pbp_insufficient_events",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                    play_count=len(payload.plays),
                    expected_min=MLB_MIN_EXPECTED_PLAYS,
                )

            # Persist plays
            inserted = upsert_plays(session, game_id, payload.plays, source="mlb_api")

            if inserted:
                pbp_games += 1
                pbp_events += inserted

                logger.info(
                    "mlb_pbp_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                    events_inserted=inserted,
                )

        except Exception as exc:
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
