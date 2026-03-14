"""Odds persistence helpers.

Handles odds matching to games and persistence, including NCAAB-specific name matching.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import Enum

from sqlalchemy import alias, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedOddsSnapshot
from ..utils.datetime_utils import now_utc
from ..utils.db_queries import get_league_id


class OddsUpsertResult(Enum):
    """Result of an odds upsert attempt."""

    PERSISTED = "persisted"
    SKIPPED_NO_MATCH = "skipped_no_match"
    SKIPPED_LIVE = "skipped_live"


from ..odds.fairbet import upsert_fairbet_odds  # noqa: E402
from .games import upsert_game_stub  # noqa: E402
from .odds_matching import (  # noqa: E402
    cache_get,
    cache_set,
    canonicalize_team_names,
    match_game_by_names_ncaab,
    match_game_by_names_non_ncaab,
    match_game_by_team_ids,
    should_log,
)
from .teams import _find_team_by_name, _upsert_team  # noqa: E402


def _execute_odds_upsert(
    session: Session,
    game_id: int,
    snapshot: NormalizedOddsSnapshot,
    side_value: str | None,
) -> None:
    """Insert opening line (first-seen, never overwritten) then upsert closing line.

    Two rows per bet are maintained via the ``is_closing_line`` flag:
    * ``is_closing_line=False`` — opening line, written once via ``DO NOTHING``.
    * ``is_closing_line=True``  — closing line, continuously updated via ``DO UPDATE``.
    """
    common_values: dict = dict(
        game_id=game_id,
        book=snapshot.book,
        market_type=snapshot.market_type,
        side=side_value,
        line=snapshot.line,
        price=snapshot.price,
        observed_at=snapshot.observed_at,
        source_key=snapshot.source_key,
        raw_payload=snapshot.raw_payload,
        market_category=snapshot.market_category,
        player_name=snapshot.player_name,
        description=snapshot.description,
    )

    # --- Opening line: first-seen value, never overwritten ---
    opening_stmt = (
        insert(db_models.SportsGameOdds)
        .values(**common_values, is_closing_line=False)
        .on_conflict_do_nothing(
            index_elements=["game_id", "book", "market_type", "side", "is_closing_line"],
        )
    )
    session.execute(opening_stmt)

    # --- Closing line: continuously updated (existing behaviour) ---
    closing_stmt = (
        insert(db_models.SportsGameOdds)
        .values(**common_values, is_closing_line=True)
        .on_conflict_do_update(
            index_elements=["game_id", "book", "market_type", "side", "is_closing_line"],
            set_={
                "line": snapshot.line,
                "price": snapshot.price,
                "observed_at": snapshot.observed_at,
                "source_key": snapshot.source_key,
                "raw_payload": snapshot.raw_payload,
                "market_category": snapshot.market_category,
                "player_name": snapshot.player_name,
                "description": snapshot.description,
                "updated_at": now_utc(),
            },
        )
    )
    session.execute(closing_stmt)


def upsert_odds(session: Session, snapshot: NormalizedOddsSnapshot) -> OddsUpsertResult:
    """Upsert odds snapshot, matching to existing game.

    Tries multiple matching strategies:
    1. Match by team IDs (exact and swapped)
    2. Match by team names (NCAAB uses normalized matching, others use exact)

    Returns:
        PERSISTED — odds were written to the database.
        SKIPPED_NO_MATCH — no matching game found (or far-future / stub failure).
        SKIPPED_LIVE — game is live; write skipped to preserve closing lines.
    """
    league_id = get_league_id(session, snapshot.league_code)

    home_team_id = _find_team_by_name(
        session, league_id, snapshot.home_team.name, snapshot.home_team.abbreviation
    )
    if home_team_id is None:
        logger.debug(
            "odds_team_not_found_creating",
            team_name=snapshot.home_team.name,
            abbreviation=snapshot.home_team.abbreviation,
            league=snapshot.league_code,
        )
        home_team_id = _upsert_team(session, league_id, snapshot.home_team)
    else:
        if should_log(f"odds_team_found:{home_team_id}", sample=200):
            logger.debug(
                "odds_team_found",
                team_name=snapshot.home_team.name,
                team_id=home_team_id,
                league=snapshot.league_code,
            )

    away_team_id = _find_team_by_name(
        session, league_id, snapshot.away_team.name, snapshot.away_team.abbreviation
    )
    if away_team_id is None:
        logger.debug(
            "odds_team_not_found_creating",
            team_name=snapshot.away_team.name,
            abbreviation=snapshot.away_team.abbreviation,
            league=snapshot.league_code,
        )
        away_team_id = _upsert_team(session, league_id, snapshot.away_team)
    else:
        if should_log(f"odds_team_found:{away_team_id}", sample=200):
            logger.debug(
                "odds_team_found",
                team_name=snapshot.away_team.name,
                team_id=away_team_id,
                league=snapshot.league_code,
            )

    game_day = snapshot.game_date.date()
    cache_key = (
        snapshot.league_code,
        game_day,
        min(home_team_id, away_team_id),
        max(home_team_id, away_team_id),
    )
    cached = cache_get(cache_key)
    if cached is not False:
        game_id = cached  # type: ignore[assignment]
        if game_id is None:
            return OddsUpsertResult.SKIPPED_NO_MATCH

        game = session.get(db_models.SportsGame, game_id)

        # Skip live games to preserve pre-game closing lines
        if game and game.status == db_models.GameStatus.live.value:
            logger.debug("odds_skip_live_game", game_id=game_id, book=snapshot.book)
            return OddsUpsertResult.SKIPPED_LIVE

        # Store odds_api_event_id for downstream prop fetching (cached path)
        if game and snapshot.event_id:
            ext = dict(game.external_ids) if game.external_ids else {}
            if ext.get("odds_api_event_id") != snapshot.event_id:
                ext["odds_api_event_id"] = snapshot.event_id
                game.external_ids = ext

        side_value = snapshot.side if snapshot.side else None
        _execute_odds_upsert(session, game_id, snapshot, side_value)

        # FairBet work table: append odds for non-completed games (cached path)
        if game is not None:
            upsert_fairbet_odds(session, game_id, game.status, snapshot)
            game.last_odds_at = now_utc()

        return OddsUpsertResult.PERSISTED
    day_start = datetime.combine(game_day - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    day_end = datetime.combine(game_day + timedelta(days=1), datetime.max.time(), tzinfo=UTC)

    if should_log("odds_matching_start"):
        logger.debug(
            "odds_matching_start",
            league=snapshot.league_code,
            home_team_name=snapshot.home_team.name,
            home_team_id=home_team_id,
            away_team_name=snapshot.away_team.name,
            away_team_id=away_team_id,
            game_date=str(game_day),
            game_datetime=str(snapshot.game_date),
            day_start=str(day_start),
            day_end=str(day_end),
        )

    home_canonical, away_canonical = canonicalize_team_names(snapshot)

    all_games_check = (
        select(
            db_models.SportsGame.id,
            db_models.SportsGame.game_date,
            db_models.SportsGame.home_team_id,
            db_models.SportsGame.away_team_id,
        )
        .where(db_models.SportsGame.league_id == league_id)
        .where(db_models.SportsGame.game_date >= day_start)
        .where(db_models.SportsGame.game_date <= day_end)
        .limit(10)
    )
    all_games = session.execute(all_games_check).all()

    diagnostic_games = []
    if all_games:
        team_ids = set()
        for game in all_games:
            team_ids.add(game[2])
            team_ids.add(game[3])

        teams_stmt = select(db_models.SportsTeam.id, db_models.SportsTeam.name).where(
            db_models.SportsTeam.id.in_(team_ids)
        )
        teams_map = {row[0]: row[1] for row in session.execute(teams_stmt).all()}

        diagnostic_games = [
            {
                "id": game[0],
                "date": str(game[1]),
                "home_id": game[2],
                "away_id": game[3],
                "home_name": teams_map.get(game[2], "unknown"),
                "away_name": teams_map.get(game[3], "unknown"),
            }
            for game in all_games
        ]

    if should_log("odds_diagnostic_all_games"):
        logger.debug(
            "odds_diagnostic_all_games",
            league=snapshot.league_code,
            game_date=str(game_day),
            day_start=str(day_start),
            day_end=str(day_end),
            total_games_count=len(all_games),
            diagnostic_games=diagnostic_games[:3],
            searching_for_home=snapshot.home_team.name,
            searching_for_away=snapshot.away_team.name,
        )

    home_team_alias = alias(db_models.SportsTeam)
    away_team_alias = alias(db_models.SportsTeam)

    games_check = (
        select(
            db_models.SportsGame.id,
            db_models.SportsGame.game_date,
            db_models.SportsGame.home_team_id,
            db_models.SportsGame.away_team_id,
        )
        .join(home_team_alias, db_models.SportsGame.home_team_id == home_team_alias.c.id)
        .join(away_team_alias, db_models.SportsGame.away_team_id == away_team_alias.c.id)
        .where(db_models.SportsGame.league_id == league_id)
        .where(db_models.SportsGame.game_date >= day_start)
        .where(db_models.SportsGame.game_date <= day_end)
        .where(
            or_(
                db_models.SportsGame.home_team_id == home_team_id,
                db_models.SportsGame.away_team_id == home_team_id,
                db_models.SportsGame.home_team_id == away_team_id,
                db_models.SportsGame.away_team_id == away_team_id,
                func.lower(home_team_alias.c.name) == func.lower(snapshot.home_team.name),
                func.lower(home_team_alias.c.name) == func.lower(home_canonical),
                func.lower(away_team_alias.c.name) == func.lower(snapshot.away_team.name),
                func.lower(away_team_alias.c.name) == func.lower(away_canonical),
                func.lower(home_team_alias.c.name) == func.lower(snapshot.away_team.name),
                func.lower(home_team_alias.c.name) == func.lower(away_canonical),
                func.lower(away_team_alias.c.name) == func.lower(snapshot.home_team.name),
                func.lower(away_team_alias.c.name) == func.lower(home_canonical),
            )
        )
        .limit(20)
    )
    potential_games = session.execute(games_check).all()

    if should_log("odds_potential_games_found"):
        logger.debug(
            "odds_potential_games_found",
            league=snapshot.league_code,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            potential_games_count=len(potential_games),
            potential_games=[
                {
                    "id": game[0],
                    "date": str(game[1]),
                    "home_id": game[2],
                    "away_id": game[3],
                }
                for game in potential_games[:5]
            ],
        )

    game_id = match_game_by_team_ids(
        session, league_id, home_team_id, away_team_id, day_start, day_end
    )

    logger.debug(
        "odds_exact_match_attempt",
        league=snapshot.league_code,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        game_id=game_id,
        matched=game_id is not None,
    )

    if game_id is None:
        if snapshot.league_code == "NCAAB":
            game_id = match_game_by_names_ncaab(
                session, league_id, snapshot, home_canonical, away_canonical, day_start, day_end
            )
        else:
            game_id = match_game_by_names_non_ncaab(
                session, league_id, snapshot, home_canonical, away_canonical, day_start, day_end
            )

    if game_id is None:
        # Game not found - create it via upsert_game_stub
        # Odds API is the sole creator of game records (for both historical and future dates)
        game_date_only = snapshot.game_date.date()
        today = date.today()
        is_historical = game_date_only < today

        # Guard: reject game stubs more than 48 hours in the future.
        # The Odds API sometimes returns events outside the requested
        # commenceTimeTo window.
        max_future = today + timedelta(days=2)
        if game_date_only > max_future:
            logger.debug(
                "odds_skip_far_future_game",
                league=snapshot.league_code,
                game_date=str(game_date_only),
                home_team=snapshot.home_team.name,
                away_team=snapshot.away_team.name,
            )
            cache_set(cache_key, None)
            return OddsUpsertResult.SKIPPED_NO_MATCH

        # Build external_ids with Odds API source key if available
        external_ids = {}
        if snapshot.source_key:
            external_ids["odds_api_event_id"] = snapshot.source_key

        # Historical games are created with "scheduled" status - boxscore scraping will update to "final"
        try:
            game_id, created = upsert_game_stub(
                session,
                league_code=snapshot.league_code,
                game_date=snapshot.game_date,
                home_team=snapshot.home_team,
                away_team=snapshot.away_team,
                status="scheduled",
                external_ids=external_ids if external_ids else None,
            )
        except Exception as exc:
            logger.error(
                "odds_game_stub_failed",
                league=snapshot.league_code,
                home_team=snapshot.home_team.name,
                away_team=snapshot.away_team.name,
                game_date=str(game_date_only),
                is_historical=is_historical,
                error=str(exc),
                exc_info=True,
            )
            cache_set(cache_key, None)
            return OddsUpsertResult.SKIPPED_NO_MATCH

        logger.info(
            "odds_created_game_stub",
            league=snapshot.league_code,
            game_id=game_id,
            created=created,
            home_team=snapshot.home_team.name,
            away_team=snapshot.away_team.name,
            game_date=str(game_date_only),
            is_historical=is_historical,
        )

        # Cache the newly created game_id for subsequent odds records
        cache_set(cache_key, game_id)

    game = session.get(db_models.SportsGame, game_id)

    # Skip live games to preserve pre-game closing lines
    if game and game.status == db_models.GameStatus.live.value:
        logger.debug("odds_skip_live_game", game_id=game_id, book=snapshot.book)
        cache_set(cache_key, game_id)
        return OddsUpsertResult.SKIPPED_LIVE

    # Store odds_api_event_id for downstream prop fetching
    if game and snapshot.event_id:
        ext = dict(game.external_ids) if game.external_ids else {}
        if ext.get("odds_api_event_id") != snapshot.event_id:
            ext["odds_api_event_id"] = snapshot.event_id
            game.external_ids = ext

    side_value = snapshot.side if snapshot.side else None
    _execute_odds_upsert(session, game_id, snapshot, side_value)

    # FairBet work table: append odds for non-completed games
    # This enables cross-book comparison in FairBet
    if game is not None:
        upsert_fairbet_odds(session, game_id, game.status, snapshot)
        game.last_odds_at = now_utc()

    cache_set(cache_key, game_id)
    return OddsUpsertResult.PERSISTED
