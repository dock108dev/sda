"""Shared database query utilities."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from .datetime_utils import end_of_et_day_utc

from sqlalchemy import exists, func, not_, or_, select
from sqlalchemy.orm import Session

from ..db import db_models


def get_league_id(session: Session, league_code: str) -> int:
    """Get league ID by code.

    Args:
        session: Database session
        league_code: League code (NBA, NFL, etc.)

    Returns:
        League ID

    Raises:
        ValueError: If league not found
    """
    stmt = select(db_models.SportsLeague.id).where(db_models.SportsLeague.code == league_code)
    league_id = session.execute(stmt).scalar()
    if league_id is None:
        raise ValueError(f"League code {league_code} not found. Seed sports_leagues first.")
    return league_id


def count_team_games(session: Session, team_id: int) -> int:
    """Count number of games for a team.

    Args:
        session: Database session
        team_id: Team ID

    Returns:
        Number of games (home or away)
    """
    stmt = select(func.count(db_models.SportsGame.id)).where(
        or_(
            db_models.SportsGame.home_team_id == team_id,
            db_models.SportsGame.away_team_id == team_id,
        )
    )
    return session.execute(stmt).scalar() or 0


def has_player_boxscores(session: Session, game_id: int) -> bool:
    """Check if a game has player boxscores.

    Args:
        session: Database session
        game_id: Game ID

    Returns:
        True if game has player boxscores
    """
    stmt = exists().where(db_models.SportsPlayerBoxscore.game_id == game_id)
    return session.execute(select(stmt)).scalar() or False


def has_odds(session: Session, game_id: int) -> bool:
    """Check if a game has odds data.

    Args:
        session: Database session
        game_id: Game ID

    Returns:
        True if game has odds
    """
    stmt = exists().where(db_models.SportsGameOdds.game_id == game_id)
    return session.execute(select(stmt)).scalar() or False


def find_games_in_date_range(
    session: Session,
    league_id: int,
    start_date: date,
    end_date: date,
    missing_players: bool = False,
    missing_odds: bool = False,
    require_source_key: bool = True,
) -> Sequence[tuple[int, str | None, datetime | None]]:
    """Find games in a date range, optionally filtering by missing data.

    Args:
        session: Database session
        league_id: League ID
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        missing_players: If True, only return games missing player boxscores
        missing_odds: If True, only return games missing odds
        require_source_key: If True, only return games with source_game_key

    Returns:
        Sequence of (game_id, source_game_key, game_date) tuples
    """
    query = session.query(
        db_models.SportsGame.id,
        db_models.SportsGame.source_game_key,
        db_models.SportsGame.game_date,
    ).filter(
        db_models.SportsGame.league_id == league_id,
        db_models.SportsGame.game_date >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
    )

    if require_source_key:
        query = query.filter(db_models.SportsGame.source_game_key.isnot(None))

    # Build filter conditions
    conditions = []
    if missing_players:
        has_players = exists().where(
            db_models.SportsPlayerBoxscore.game_id == db_models.SportsGame.id
        )
        conditions.append(not_(has_players))
    if missing_odds:
        has_odds = exists().where(
            db_models.SportsGameOdds.game_id == db_models.SportsGame.id
        )
        conditions.append(not_(has_odds))

    if conditions:
        query = query.filter(or_(*conditions))

    return query.all()

