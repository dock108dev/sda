"""Game persistence helpers.

Central game resolution: ``find_or_create_game()`` is the **single entry
point** for every ingestion path (odds, boxscores, PBP, player stats,
schedule feeds, live feeds, backfill).  It uses a multi-tier matching
strategy and a Redis-based match cache shared across all Celery workers.
"""

from __future__ import annotations

import json
from datetime import date as _date_type, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedGame
from ..utils.date_utils import season_from_date
from ..utils.datetime_utils import end_of_et_day_utc, now_utc, start_of_et_day_utc, to_et_date
from ..utils.db_queries import get_league_id
from .teams import _upsert_team

if TYPE_CHECKING:
    from ..models import TeamIdentity


def _notify_game_update(session: Session | None, game_id: int) -> None:
    """Emit pg_notify('game_score_update', ...) within the current transaction.

    Best-effort — never raises. The notification fires on transaction commit
    so the API LISTEN handler always sees consistent data.
    """
    if session is None:
        return
    try:
        payload = json.dumps({"game_id": game_id, "event_type": "game_score_update"})
        session.execute(
            text("SELECT pg_notify('game_score_update', :p)"), {"p": payload}
        )
    except Exception:
        logger.debug("pg_notify_game_update_failed", extra={"game_id": game_id}, exc_info=True)


# ---------------------------------------------------------------------------
# Redis match cache — shared across all Celery workers
# ---------------------------------------------------------------------------

_GAME_CACHE_TTL = 3600  # 1 hour — long enough to avoid repeated queries,
                         # short enough that new games are found quickly.
_GAME_CACHE_PREFIX = "game_match"


def _cache_key(league_code: str, et_date, team_lo: int, team_hi: int) -> str:
    return f"{_GAME_CACHE_PREFIX}:{league_code}:{et_date}:{team_lo}:{team_hi}"


def _cache_get(key: str) -> int | None:
    """Get a game_id from Redis cache. Returns None on miss or error."""
    try:
        import redis as redis_lib
        from ..config import settings
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        val = r.get(key)
        if val is not None:
            return int(val)
    except Exception:
        logger.debug("game_cache_get_failed", extra={"key": key}, exc_info=True)
    return None


def _cache_set(key: str, game_id: int) -> None:
    """Cache a positive match. NEVER cache negatives (None)."""
    try:
        import redis as redis_lib
        from ..config import settings
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        r.set(key, str(game_id), ex=_GAME_CACHE_TTL)
    except Exception:
        logger.debug("game_cache_set_failed", extra={"key": key}, exc_info=True)


def _cache_delete(key: str) -> None:
    """Delete a cache entry (used when a game is deleted)."""
    try:
        import redis as redis_lib
        from ..config import settings
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        r.delete(key)
    except Exception:
        logger.debug("game_cache_delete_failed", extra={"key": key}, exc_info=True)


# ---------------------------------------------------------------------------
# Unified find-or-create
# ---------------------------------------------------------------------------


def _has_real_time(game_date) -> bool:
    """Return True if game_date carries a meaningful tip time (not a
    placeholder created from a date-only source).

    Recognises two placeholder patterns:
    - midnight ET  (from ``date_to_utc_datetime`` / ``_to_datetime``)
    - noon ET      (from NHL ``_et_noon_utc`` schedule fallback)
    """
    if isinstance(game_date, _date_type) and not isinstance(game_date, datetime):
        return False  # bare date — no time info
    et_day = to_et_date(game_date)
    midnight_et = start_of_et_day_utc(et_day)
    noon_et = midnight_et + timedelta(hours=12)
    return game_date != midnight_et and game_date != noon_et


def _to_datetime(game_date) -> datetime:
    """Coerce a date or datetime to a timezone-aware UTC datetime for storage."""
    if isinstance(game_date, _date_type) and not isinstance(game_date, datetime):
        return start_of_et_day_utc(game_date)
    return game_date


def find_or_create_game(
    session: Session,
    *,
    league_code: str,
    game_date: datetime,  # accepts date or datetime
    home_team: TeamIdentity,
    away_team: TeamIdentity,
    status: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    venue: str | None = None,
    external_ids: dict[str, Any] | None = None,
    source_game_key: str | None = None,
    season_type: str = "regular",
    create_if_missing: bool = True,
) -> tuple[int | None, bool]:
    """Find an existing game or create one.  THE single entry point for all
    ingestion paths.

    Matching strategy (tried in order):
    1. Redis cache hit (keyed by league + ET date + sorted team IDs)
    2. External ID match (nba_game_id, nhl_game_pk, odds_api_event_id, etc.)
    3. source_game_key match
    4. Team ID + ET calendar day match (exact home/away)
    5. Team ID + ET calendar day match (swapped home/away)
    6. Create (if ``create_if_missing=True``)

    On match, merges external_ids and updates game_date if more precise.
    NEVER caches negative results — only positive matches are cached.

    Returns ``(game_id, created)``.  If ``create_if_missing=False`` and no
    match, returns ``(None, False)``.
    """
    league_id = get_league_id(session, league_code)
    home_team_id = _upsert_team(session, league_id, home_team)
    away_team_id = _upsert_team(session, league_id, away_team)

    # Coerce date → datetime for DB operations; keep original for _enrich checks
    game_date_dt = _to_datetime(game_date)
    game_date_only = to_et_date(game_date_dt)
    day_start = start_of_et_day_utc(game_date_only)
    day_end = end_of_et_day_utc(game_date_only)

    team_lo = min(home_team_id, away_team_id)
    team_hi = max(home_team_id, away_team_id)
    cache_key = _cache_key(league_code, game_date_only, team_lo, team_hi)

    # --- Tier 1: Redis cache ---
    cached_id = _cache_get(cache_key)
    if cached_id is not None:
        game = session.get(db_models.SportsGame, cached_id)
        if game is not None:
            _enrich_existing(game, status, home_score, away_score, venue,
                             external_ids, game_date, season_type)
            session.flush()
            return game.id, False
        # Game was deleted since caching — fall through
        _cache_delete(cache_key)

    # --- Tier 2: External ID match ---
    if external_ids:
        for eid_key in ("nba_game_id", "nhl_game_pk", "mlb_game_pk",
                        "espn_game_id", "cbb_game_id", "ncaa_game_id",
                        "odds_api_event_id"):
            eid_val = external_ids.get(eid_key)
            if eid_val is not None:
                game = (
                    session.query(db_models.SportsGame)
                    .filter(
                        db_models.SportsGame.league_id == league_id,
                        db_models.SportsGame.external_ids[eid_key].astext == str(eid_val),
                    )
                    .first()
                )
                if game is not None:
                    _enrich_existing(game, status, home_score, away_score,
                                     venue, external_ids, game_date, season_type)
                    session.flush()
                    _cache_set(cache_key, game.id)
                    return game.id, False

    # --- Tier 3: source_game_key match ---
    if source_game_key:
        game = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id == league_id,
                db_models.SportsGame.source_game_key == source_game_key,
            )
            .first()
        )
        if game is not None:
            _enrich_existing(game, status, home_score, away_score, venue,
                             external_ids, game_date, season_type)
            session.flush()
            _cache_set(cache_key, game.id)
            return game.id, False

    # --- Tier 4: Team ID + ET date (exact) ---
    game = (
        session.query(db_models.SportsGame)
        .filter(
            db_models.SportsGame.league_id == league_id,
            db_models.SportsGame.home_team_id == home_team_id,
            db_models.SportsGame.away_team_id == away_team_id,
            db_models.SportsGame.game_date >= day_start,
            db_models.SportsGame.game_date < day_end,
        )
        .first()
    )
    if game is not None:
        _enrich_existing(game, status, home_score, away_score, venue,
                         external_ids, game_date, season_type)
        session.flush()
        _cache_set(cache_key, game.id)
        return game.id, False

    # --- Tier 5: Team ID + ET date (swapped home/away) ---
    game = (
        session.query(db_models.SportsGame)
        .filter(
            db_models.SportsGame.league_id == league_id,
            db_models.SportsGame.home_team_id == away_team_id,
            db_models.SportsGame.away_team_id == home_team_id,
            db_models.SportsGame.game_date >= day_start,
            db_models.SportsGame.game_date < day_end,
        )
        .first()
    )
    if game is not None:
        _enrich_existing(game, status, home_score, away_score, venue,
                         external_ids, game_date, season_type)
        session.flush()
        _cache_set(cache_key, game.id)
        return game.id, False

    # --- Tier 6: Create ---
    if not create_if_missing:
        return None, False

    season = season_from_date(game_date_only, league_code)
    normalized_status = _normalize_status(status)

    game = db_models.SportsGame(
        league_id=league_id,
        season=season,
        season_type=season_type,
        game_date=game_date_dt,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
        venue=venue,
        status=normalized_status,
        end_time=None,
        source_game_key=source_game_key,
        scrape_version=1,
        last_scraped_at=None,
        last_ingested_at=now_utc(),
        external_ids=external_ids or {},
    )
    session.add(game)
    session.flush()

    _cache_set(cache_key, game.id)

    logger.info(
        "game_created",
        league=league_code,
        game_id=game.id,
        game_date=str(game_date_only),
        home_team=home_team.name,
        away_team=away_team.name,
    )

    return game.id, True


def _enrich_existing(
    game: db_models.SportsGame,
    status: str | None,
    home_score: int | None,
    away_score: int | None,
    venue: str | None,
    external_ids: dict[str, Any] | None,
    game_date,
    season_type: str,
) -> None:
    """Update an existing game with new data without regressing state.

    Never updates ``game_date`` to a value that would violate the
    ``uq_game_identity`` constraint — if the new timestamp conflicts
    with another game row, the update is silently skipped.
    """
    updated = False

    # Status: only advance forward
    if status:
        new_status = resolve_status_transition(game.status, _normalize_status(status))
        if new_status != game.status:
            game.status = new_status
            updated = True

    # Scores: only set if provided
    if home_score is not None and home_score != game.home_score:
        game.home_score = home_score
        updated = True
    if away_score is not None and away_score != game.away_score:
        game.away_score = away_score
        updated = True

    # Venue
    if venue and venue != game.venue:
        game.venue = venue
        updated = True

    # External IDs: merge
    if external_ids:
        merged = merge_external_ids(game.external_ids, external_ids)
        if merged != game.external_ids:
            game.external_ids = merged
            updated = True

    # Only update game_date when the incoming value carries a REAL time
    # and the existing value is a placeholder.
    # DO NOT update if it would violate uq_game_identity (another game
    # already has this exact timestamp for the same teams).
    if _has_real_time(game_date) and not _has_real_time(game.game_date):
        new_dt = _to_datetime(game_date)
        if new_dt != game.game_date:
            # Check for conflict before updating
            from sqlalchemy import select
            conflict = (
                select(db_models.SportsGame.id)
                .where(
                    db_models.SportsGame.league_id == game.league_id,
                    db_models.SportsGame.season == game.season,
                    db_models.SportsGame.game_date == new_dt,
                    db_models.SportsGame.home_team_id == game.home_team_id,
                    db_models.SportsGame.away_team_id == game.away_team_id,
                    db_models.SportsGame.id != game.id,
                )
            )
            # Use the session bound to this game's state
            sess = object_session(game)
            if sess and not sess.execute(conflict).first():
                game.game_date = new_dt
                updated = True

    # Season type
    if season_type != "regular" and game.season_type == "regular":
        game.season_type = season_type
        updated = True

    if updated:
        game.updated_at = now_utc()
        game.last_ingested_at = now_utc()
        _notify_game_update(object_session(game), game.id)


def _normalize_status(status: str | None) -> str:
    if not status:
        return db_models.GameStatus.scheduled.value
    status_normalized = status.lower()
    if status_normalized in {"final", "completed"}:
        return db_models.GameStatus.final.value
    if status_normalized == db_models.GameStatus.live.value:
        return db_models.GameStatus.live.value
    if status_normalized == db_models.GameStatus.pregame.value:
        return db_models.GameStatus.pregame.value
    if status_normalized == db_models.GameStatus.archived.value:
        return db_models.GameStatus.archived.value
    if status_normalized == db_models.GameStatus.scheduled.value:
        return db_models.GameStatus.scheduled.value
    if status_normalized == db_models.GameStatus.postponed.value:
        return db_models.GameStatus.postponed.value
    if status_normalized in {db_models.GameStatus.CANCELLED.value, "canceled"}:
        return db_models.GameStatus.CANCELLED.value
    return db_models.GameStatus.scheduled.value


# One-way progression order for the happy path.
# Higher index = further along in lifecycle. Transitions may only move forward.
_STATUS_ORDER: dict[str, int] = {
    db_models.GameStatus.scheduled.value: 0,
    db_models.GameStatus.pregame.value: 1,
    db_models.GameStatus.live.value: 2,
    db_models.GameStatus.final.value: 3,
    db_models.GameStatus.archived.value: 4,
}


def resolve_status_transition(current_status: str | None, incoming_status: str | None) -> str:
    """Resolve a safe status transition without regressing games.

    Rules:
    - archived is terminal (never regresses from archived)
    - final never regresses (except to archived)
    - Generally, status only moves forward in the lifecycle
    - Non-lifecycle statuses (postponed, cancelled) are accepted as-is
    """
    current = _normalize_status(current_status)
    incoming = _normalize_status(incoming_status)

    # Terminal states: archived never regresses
    if current == db_models.GameStatus.archived.value:
        return current

    # Final never regresses except to archived
    if current == db_models.GameStatus.final.value:
        if incoming == db_models.GameStatus.archived.value:
            return incoming
        return current

    # For lifecycle states, only allow forward progression
    current_order = _STATUS_ORDER.get(current)
    incoming_order = _STATUS_ORDER.get(incoming)

    if current_order is not None and incoming_order is not None:
        if incoming_order < current_order:
            return current  # Don't regress
        return incoming

    # Non-lifecycle statuses (postponed, cancelled) pass through
    return incoming


def merge_external_ids(
    existing: dict[str, Any],
    updates: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge external IDs, preferring new non-null values."""
    if not updates:
        return existing

    merged = dict(existing or {})
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    return merged


def upsert_game_stub(
    session: Session,
    *,
    league_code: str,
    game_date: datetime,
    home_team: TeamIdentity,
    away_team: TeamIdentity,
    status: str | None,
    home_score: int | None = None,
    away_score: int | None = None,
    venue: str | None = None,
    external_ids: dict[str, Any] | None = None,
    season_type: str = "regular",
) -> tuple[int, bool]:
    """Upsert a game without boxscores.

    Thin wrapper around ``find_or_create_game`` — kept for backward
    compatibility with existing callers.
    """
    game_id, created = find_or_create_game(
        session,
        league_code=league_code,
        game_date=game_date,
        home_team=home_team,
        away_team=away_team,
        status=status,
        home_score=home_score,
        away_score=away_score,
        venue=venue,
        external_ids=external_ids,
        season_type=season_type,
    )
    # find_or_create_game always creates if missing, so game_id is never None here
    return game_id, created  # type: ignore[return-value]


def update_game_from_live_feed(
    session: Session,
    *,
    game: db_models.SportsGame,
    status: str | None,
    home_score: int | None,
    away_score: int | None,
    venue: str | None = None,
    external_ids: dict[str, Any] | None = None,
) -> bool:
    """Apply live feed updates while preventing status regression."""
    updated_status = resolve_status_transition(game.status, status)
    merged_external_ids = merge_external_ids(game.external_ids, external_ids)
    updated = False

    if updated_status != game.status:
        game.status = updated_status
        updated = True
    if home_score is not None and home_score != game.home_score:
        game.home_score = home_score
        updated = True
    if away_score is not None and away_score != game.away_score:
        game.away_score = away_score
        updated = True
    if venue and venue != game.venue:
        game.venue = venue
        updated = True
    if merged_external_ids != game.external_ids:
        game.external_ids = merged_external_ids
        updated = True

    if updated:
        game.updated_at = now_utc()
        game.last_ingested_at = now_utc()
        session.flush()
        _notify_game_update(session, game.id)
    return updated


def upsert_game(session: Session, normalized: NormalizedGame) -> tuple[int, bool]:
    """Upsert a game from historical boxscore ingestion.

    Delegates to ``find_or_create_game`` for game resolution, then sets
    boxscore-specific fields (source_game_key, scrape_version).

    Returns the game ID and whether it was newly created.
    """
    game_id, created = find_or_create_game(
        session,
        league_code=normalized.identity.league_code,
        game_date=normalized.identity.game_date,
        home_team=normalized.identity.home_team,
        away_team=normalized.identity.away_team,
        status=normalized.status,
        home_score=normalized.home_score,
        away_score=normalized.away_score,
        venue=normalized.venue,
        source_game_key=normalized.identity.source_game_key,
        season_type=normalized.identity.season_type or "regular",
    )

    # Set boxscore-specific fields that find_or_create_game doesn't handle
    if game_id is not None:
        game = session.get(db_models.SportsGame, game_id)
        if game is not None:
            updated = False
            if normalized.identity.source_game_key and not game.source_game_key:
                game.source_game_key = normalized.identity.source_game_key
                updated = True
            game.scrape_version = (game.scrape_version or 0) + 1
            game.last_scraped_at = now_utc()
            if updated:
                game.updated_at = now_utc()
            session.flush()

    logger.info(
        "game_resolution",
        league=normalized.identity.league_code,
        game_id=game_id,
        external_id=normalized.identity.source_game_key,
        inserted=created,
    )
    return game_id, created  # type: ignore[return-value]
