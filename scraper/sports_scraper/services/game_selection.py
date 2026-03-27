"""Game selection queries for scrape runs.

These functions select games that need scraping based on various filters.
Used by run_manager to determine which games to process.

Games with ``ingest_error_count >= MAX_INGEST_ERRORS`` are automatically
excluded from selection to prevent infinite retry loops on permanently
broken games.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc, to_et_date

# Games that fail this many times are excluded from automatic selection.
# Reset via admin endpoint or manual DB update.
MAX_INGEST_ERRORS = 5


def select_games_for_boxscores(
    session: Session,
    league_code: str,
    start_date: date,
    end_date: date,
    *,
    only_missing: bool = False,
    updated_before: datetime | None = None,
) -> list[tuple[int, str, date | None]]:
    """Return game ids/keys for boxscore scraping with filters."""
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == league_code
    ).first()
    if not league:
        return []

    query = session.query(
        db_models.SportsGame.id,
        db_models.SportsGame.source_game_key,
        db_models.SportsGame.game_date,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        db_models.SportsGame.source_game_key.isnot(None),
        db_models.SportsGame.ingest_error_count < MAX_INGEST_ERRORS,
    )

    if only_missing:
        has_boxscores = exists().where(
            db_models.SportsTeamBoxscore.game_id == db_models.SportsGame.id
        )
        query = query.filter(not_(has_boxscores))

    if updated_before:
        query = query.filter(db_models.SportsGame.updated_at < updated_before)

    results = query.all()
    return [(r.id, r.source_game_key, to_et_date(r.game_date) if r.game_date else None) for r in results]



def select_games_for_pbp_sportsref(
    session: Session,
    *,
    league_code: str,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, str, date]]:
    """Return game ids/keys for Sports Reference play-by-play ingestion."""
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == league_code
    ).first()
    if not league:
        return []

    query = session.query(
        db_models.SportsGame.id,
        db_models.SportsGame.source_game_key,
        db_models.SportsGame.game_date,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        db_models.SportsGame.source_game_key.isnot(None),
        db_models.SportsGame.ingest_error_count < MAX_INGEST_ERRORS,
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
    return [(gid, str(source_key), game_dt.date()) for gid, source_key, game_dt in rows if source_key]


def record_ingest_error(session: Session, game_id: int, error: str) -> None:
    """Increment the ingest error count for a game and record the error message.

    Called when per-game boxscore/PBP/advanced stats ingestion fails.
    Games that exceed ``MAX_INGEST_ERRORS`` are excluded from future
    automatic selection.
    """
    from sqlalchemy import update

    stmt = (
        update(db_models.SportsGame)
        .where(db_models.SportsGame.id == game_id)
        .values(
            ingest_error_count=db_models.SportsGame.ingest_error_count + 1,
            last_ingest_error=error[:500],  # truncate long error messages
        )
    )
    session.execute(stmt)


def clear_ingest_errors(session: Session, game_id: int) -> None:
    """Clear ingest error tracking for a game after successful processing."""
    from sqlalchemy import update

    stmt = (
        update(db_models.SportsGame)
        .where(db_models.SportsGame.id == game_id)
        .values(ingest_error_count=0, last_ingest_error=None)
    )
    session.execute(stmt)
