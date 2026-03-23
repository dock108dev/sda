"""NFL play-by-play ingestion via ESPN API."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..persistence.plays import upsert_plays
from ..utils.datetime_utils import end_of_et_day_utc, now_utc, start_of_et_day_utc


def select_games_for_pbp_nfl_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int]]:
    """Return (game_id, espn_game_id) tuples for NFL PBP ingestion."""
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NFL"
    ).first()
    if not league:
        return []

    espn_id_expr = db_models.SportsGame.external_ids["espn_game_id"].astext

    query = session.query(
        db_models.SportsGame.id,
        espn_id_expr.label("espn_game_id"),
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        db_models.SportsGame.status == db_models.GameStatus.final.value,
    )

    if only_missing:
        has_pbp = exists().where(
            db_models.SportsGamePlay.game_id == db_models.SportsGame.id
        )
        query = query.filter(not_(has_pbp))

    if updated_before:
        has_fresh = exists().where(
            db_models.SportsGamePlay.game_id == db_models.SportsGame.id,
            db_models.SportsGamePlay.updated_at >= updated_before,
        )
        query = query.filter(not_(has_fresh))

    rows = query.all()
    results = []
    for game_id, espn_game_id in rows:
        if espn_game_id:
            try:
                results.append((game_id, int(espn_game_id)))
            except (ValueError, TypeError):
                pass
    return results


def ingest_pbp_via_nfl_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int]:
    """Ingest NFL PBP using the ESPN API.

    Returns (games_with_pbp, total_events).
    """
    from .nfl_boxscore_ingestion import populate_nfl_game_ids

    # Step 1: Populate missing ESPN game IDs
    populate_nfl_game_ids(session, run_id=run_id, start_date=start_date, end_date=end_date)
    session.expire_all()

    # Step 2: Select games
    games = select_games_for_pbp_nfl_api(
        session, start_date=start_date, end_date=end_date,
        only_missing=only_missing, updated_before=updated_before,
    )

    if not games:
        logger.info("nfl_pbp_no_games", run_id=run_id)
        return (0, 0)

    logger.info("nfl_pbp_games_selected", run_id=run_id, count=len(games))

    # Step 3: Fetch and persist
    from ..live.nfl import NFLLiveFeedClient
    client = NFLLiveFeedClient()
    pbp_games = 0
    total_events = 0

    for game_id, espn_game_id in games:
        try:
            payload = client.fetch_play_by_play(espn_game_id)
            if payload.plays:
                inserted = upsert_plays(session, game_id, payload.plays, source="espn_nfl_api")
                session.commit()

                game = session.get(db_models.SportsGame, game_id)
                if game:
                    game.last_pbp_at = now_utc()
                    session.commit()

                pbp_games += 1
                total_events += inserted or 0
                logger.info(
                    "nfl_pbp_ingested", run_id=run_id,
                    game_id=game_id, espn_game_id=espn_game_id,
                    plays=inserted,
                )
        except Exception as exc:
            session.rollback()
            logger.warning(
                "nfl_pbp_failed", run_id=run_id,
                game_id=game_id, espn_game_id=espn_game_id,
                error=str(exc),
            )
            continue

    return (pbp_games, total_events)
