"""Odds game matching helpers."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from sqlalchemy import alias, func, or_, select
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedOddsSnapshot
from ..normalization import normalize_team_name
from ..utils.datetime_utils import to_et_date
from .teams import _NCAAB_STOPWORDS, _normalize_ncaab_name_for_matching

# Odds API team name -> DB team name mappings for NCAAB
# Keeps this list tiny—only unavoidable canonical differences.
_ODDS_API_TO_DB_MAPPINGS: dict[str, str] = {
    "St. John's Red Storm": "St. John's (NY)",
    "St John's Red Storm": "St. John's (NY)",
    "St Johns Red Storm": "St. John's (NY)",
    # HBCU / mid-major names that collide with Power conference after normalization
    "Alabama A&M Bulldogs": "Alabama A&M Bulldogs",
    "North Carolina Central Eagles": "North Carolina Central Eagles",
    "Maryland Eastern Shore Hawks": "Maryland-Eastern Shore Hawks",
    "Texas Southern Tigers": "Texas Southern Tigers",
    "Grambling Tigers": "Grambling St Tigers",
    "Grambling State Tigers": "Grambling St Tigers",
    "Howard Bison": "Howard Bison",
    "Coppin State Eagles": "Coppin St Eagles",
}

# Simple LRU cache to avoid repeating heavy match queries/logs for the same game+date.
_MATCH_CACHE: OrderedDict[tuple, int | None] = OrderedDict()
_MATCH_CACHE_MAX = 512


def cache_get(key: tuple) -> int | None | bool:
    if key in _MATCH_CACHE:
        _MATCH_CACHE.move_to_end(key)
        return _MATCH_CACHE[key]
    return False


def cache_set(key: tuple, value: int | None) -> None:
    _MATCH_CACHE[key] = value
    _MATCH_CACHE.move_to_end(key)
    if len(_MATCH_CACHE) > _MATCH_CACHE_MAX:
        _MATCH_CACHE.popitem(last=False)


def cache_clear() -> int:
    """Clear all cached game lookups. Returns number of entries cleared.

    Call this when games are deleted to prevent stale cache hits.
    """
    count = len(_MATCH_CACHE)
    _MATCH_CACHE.clear()
    logger.info("odds_match_cache_cleared", entries_cleared=count)
    return count


def cache_invalidate_game(game_id: int) -> int:
    """Invalidate cache entries for a specific game ID.

    Call this when a single game is deleted.
    Returns number of entries invalidated.
    """
    keys_to_remove = [key for key, value in _MATCH_CACHE.items() if value == game_id]
    for key in keys_to_remove:
        del _MATCH_CACHE[key]
    if keys_to_remove:
        logger.info("odds_match_cache_invalidated", game_id=game_id, entries_removed=len(keys_to_remove))
    return len(keys_to_remove)


# Simple counters to only log a subset of noisy events
_LOG_COUNTERS: dict[str, int] = {}
_LOG_SAMPLE = 50  # log every Nth occurrence per event key


def should_log(event_key: str, sample: int = _LOG_SAMPLE) -> bool:
    count = _LOG_COUNTERS.get(event_key, 0) + 1
    _LOG_COUNTERS[event_key] = count
    return count % sample == 1  # log first and then every Nth


def match_game_by_team_ids(
    session: Session,
    league_id: int,
    home_team_id: int,
    away_team_id: int,
    day_start: datetime,
    day_end: datetime,
) -> int | None:
    """Try to match a game by team IDs (exact and swapped)."""
    stmt = (
        select(db_models.SportsGame.id)
        .where(db_models.SportsGame.league_id == league_id)
        .where(db_models.SportsGame.home_team_id == home_team_id)
        .where(db_models.SportsGame.away_team_id == away_team_id)
        .where(db_models.SportsGame.game_date >= day_start)
        .where(db_models.SportsGame.game_date < day_end)
    )
    game_id = session.execute(stmt).scalar()

    if game_id is None:
        swap_stmt = (
            select(db_models.SportsGame.id)
            .where(db_models.SportsGame.league_id == league_id)
            .where(db_models.SportsGame.home_team_id == away_team_id)
            .where(db_models.SportsGame.away_team_id == home_team_id)
            .where(db_models.SportsGame.game_date >= day_start)
            .where(db_models.SportsGame.game_date < day_end)
        )
        game_id = session.execute(swap_stmt).scalar()

    return game_id


def _ncaab_name_contains(a: str, b: str) -> bool:
    """Substring match with 80% length-ratio guard."""
    shorter, longer = sorted([a, b], key=len)
    return shorter in longer and len(shorter) / len(longer) >= 0.8


def match_game_by_names_ncaab(
    session: Session,
    league_id: int,
    snapshot: NormalizedOddsSnapshot,
    home_canonical: str,
    away_canonical: str,
    day_start: datetime,
    day_end: datetime,
) -> int | None:
    """Match game by normalized names for NCAAB (handles name variations)."""
    home_api_name = _ODDS_API_TO_DB_MAPPINGS.get(snapshot.home_team.name, snapshot.home_team.name)
    away_api_name = _ODDS_API_TO_DB_MAPPINGS.get(snapshot.away_team.name, snapshot.away_team.name)

    home_normalized = _normalize_ncaab_name_for_matching(home_api_name)
    away_normalized = _normalize_ncaab_name_for_matching(away_api_name)
    home_canonical_norm = _normalize_ncaab_name_for_matching(home_canonical)
    away_canonical_norm = _normalize_ncaab_name_for_matching(away_canonical)

    def _tokens(text: str) -> set[str]:
        return {token for token in text.split(" ") if token and token not in _NCAAB_STOPWORDS}

    all_games_in_range = (
        select(
            db_models.SportsGame.id,
            db_models.SportsGame.home_team_id,
            db_models.SportsGame.away_team_id,
        )
        .where(db_models.SportsGame.league_id == league_id)
        .where(db_models.SportsGame.game_date >= day_start)
        .where(db_models.SportsGame.game_date < day_end)
    )
    games_in_range = session.execute(all_games_in_range).all()

    team_ids = set()
    for game in games_in_range:
        team_ids.add(game[1])
        team_ids.add(game[2])

    if not team_ids:
        return None

    teams_stmt = select(db_models.SportsTeam.id, db_models.SportsTeam.name).where(
        db_models.SportsTeam.id.in_(team_ids)
    )
    teams_map = {row[0]: row[1] for row in session.execute(teams_stmt).all()}

    for game_id_candidate, home_id, away_id in games_in_range:
        home_db_name = teams_map.get(home_id, "")
        away_db_name = teams_map.get(away_id, "")
        home_db_norm = _normalize_ncaab_name_for_matching(home_db_name)
        away_db_norm = _normalize_ncaab_name_for_matching(away_db_name)
        home_db_tokens = _tokens(home_db_norm)
        away_db_tokens = _tokens(away_db_norm)
        home_tokens = _tokens(home_normalized)
        away_tokens = _tokens(away_normalized)

        home_matches = (
            home_db_norm == home_normalized
            or home_db_norm == home_canonical_norm
            or _ncaab_name_contains(home_normalized, home_db_norm)
        )
        away_matches = (
            away_db_norm == away_normalized
            or away_db_norm == away_canonical_norm
            or _ncaab_name_contains(away_normalized, away_db_norm)
        )
        if not home_matches:
            overlap_home = len(home_tokens & home_db_tokens)
            # Require 2+ overlap unless one side has only 1 token.
            # Old threshold of 1 for <=2-token names caused false matches
            # (e.g., "Illinois State" matching "Youngstown State" on shared "state").
            threshold_home = 1 if min(len(home_tokens), len(home_db_tokens)) <= 1 else 2
            home_matches = (
                overlap_home >= threshold_home
                # Only allow subset matching when the subset has 2+ tokens
                or (len(home_tokens) >= 2 and home_tokens.issubset(home_db_tokens))
                or (len(home_db_tokens) >= 2 and home_db_tokens.issubset(home_tokens))
            )
        if not away_matches:
            overlap_away = len(away_tokens & away_db_tokens)
            threshold_away = 1 if min(len(away_tokens), len(away_db_tokens)) <= 1 else 2
            away_matches = (
                overlap_away >= threshold_away
                or (len(away_tokens) >= 2 and away_tokens.issubset(away_db_tokens))
                or (len(away_db_tokens) >= 2 and away_db_tokens.issubset(away_tokens))
            )

        if home_matches and away_matches:
            logger.info(
                "odds_game_matched_by_normalized_name",
                league=snapshot.league_code,
                home_team_name=snapshot.home_team.name,
                home_team_normalized=home_normalized,
                home_db_name=home_db_name,
                home_db_normalized=home_db_norm,
                away_team_name=snapshot.away_team.name,
                away_team_normalized=away_normalized,
                away_db_name=away_db_name,
                away_db_normalized=away_db_norm,
                matched_game_id=game_id_candidate,
                game_date=str(to_et_date(snapshot.game_date)),
            )
            return game_id_candidate

        home_matches_swapped = (
            home_db_norm == away_normalized
            or home_db_norm == away_canonical_norm
            or _ncaab_name_contains(away_normalized, home_db_norm)
        )
        away_matches_swapped = (
            away_db_norm == home_normalized
            or away_db_norm == home_canonical_norm
            or _ncaab_name_contains(home_normalized, away_db_norm)
        )

        if home_matches_swapped and away_matches_swapped:
            logger.info(
                "odds_game_matched_by_normalized_name_swapped",
                league=snapshot.league_code,
                requested_home=snapshot.home_team.name,
                requested_away=snapshot.away_team.name,
                matched_as_home=away_db_name,
                matched_as_away=home_db_name,
                matched_game_id=game_id_candidate,
                game_date=str(to_et_date(snapshot.game_date)),
            )
            return game_id_candidate

    return None


def match_game_by_names_non_ncaab(
    session: Session,
    league_id: int,
    snapshot: NormalizedOddsSnapshot,
    home_canonical: str,
    away_canonical: str,
    day_start: datetime,
    day_end: datetime,
) -> int | None:
    """Match game by exact names for non-NCAAB leagues."""
    home_team_alias = alias(db_models.SportsTeam)
    away_team_alias = alias(db_models.SportsTeam)

    name_match_stmt = (
        select(db_models.SportsGame.id)
        .join(home_team_alias, db_models.SportsGame.home_team_id == home_team_alias.c.id)
        .join(away_team_alias, db_models.SportsGame.away_team_id == away_team_alias.c.id)
        .where(db_models.SportsGame.league_id == league_id)
        .where(
            or_(
                func.lower(home_team_alias.c.name) == func.lower(home_canonical),
                func.lower(home_team_alias.c.name) == func.lower(snapshot.home_team.name),
            )
        )
        .where(
            or_(
                func.lower(away_team_alias.c.name) == func.lower(away_canonical),
                func.lower(away_team_alias.c.name) == func.lower(snapshot.away_team.name),
            )
        )
        .where(db_models.SportsGame.game_date >= day_start)
        .where(db_models.SportsGame.game_date < day_end)
    )
    name_match_id = session.execute(name_match_stmt).scalar()

    if name_match_id is None:
        swapped_name_match_stmt = (
            select(db_models.SportsGame.id)
            .join(home_team_alias, db_models.SportsGame.home_team_id == home_team_alias.c.id)
            .join(away_team_alias, db_models.SportsGame.away_team_id == away_team_alias.c.id)
            .where(db_models.SportsGame.league_id == league_id)
            .where(
                or_(
                    func.lower(home_team_alias.c.name) == func.lower(away_canonical),
                    func.lower(home_team_alias.c.name) == func.lower(snapshot.away_team.name),
                )
            )
            .where(
                or_(
                    func.lower(away_team_alias.c.name) == func.lower(home_canonical),
                    func.lower(away_team_alias.c.name) == func.lower(snapshot.home_team.name),
                )
            )
            .where(db_models.SportsGame.game_date >= day_start)
            .where(db_models.SportsGame.game_date < day_end)
        )
        name_match_id = session.execute(swapped_name_match_stmt).scalar()

    if name_match_id is not None:
        logger.info(
            "odds_game_matched_by_name",
            league=snapshot.league_code,
            home_team_name=snapshot.home_team.name,
            away_team_name=snapshot.away_team.name,
            matched_game_id=name_match_id,
            game_date=str(to_et_date(snapshot.game_date)),
        )

    return name_match_id


def canonicalize_team_names(snapshot: NormalizedOddsSnapshot) -> tuple[str, str]:
    home_canonical, _ = normalize_team_name(snapshot.league_code, snapshot.home_team.name)
    away_canonical, _ = normalize_team_name(snapshot.league_code, snapshot.away_team.name)
    return home_canonical, away_canonical
