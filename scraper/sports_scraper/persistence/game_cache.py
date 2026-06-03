"""Game update notification and Redis match-cache helpers."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..logging import logger


def _notify_game_update(session: Session | None, game_id: int) -> None:
    """Emit pg_notify('game_score_update', ...) within the current transaction.

    Best-effort — never raises for known transport / DB failures. The
    notification fires on transaction commit so the API LISTEN handler
    always sees consistent data; consumers re-poll on disconnect, so a
    missed NOTIFY is degraded UX, not data loss.

    Catch is narrowed to ``(SQLAlchemyError, OSError)`` — programming bugs
    (e.g. payload schema drift causing TypeError) propagate instead of
    being silently swallowed.
    """
    if session is None:
        return
    try:
        payload = json.dumps({"game_id": game_id, "event_type": "game_score_update"})
        session.execute(
            text("SELECT pg_notify('game_score_update', :p)"), {"p": payload}
        )
    except (SQLAlchemyError, OSError):
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
    """Get a game_id from Redis cache. Returns None on miss or transport error.

    Catch is narrowed to ``RedisError`` (covers connection/protocol/timeout)
    plus ``OSError`` (DNS failure / connection refused). A bug — e.g. a
    refactor that changes the cache key shape and crashes ``int()`` — must
    not be absorbed silently here.
    """
    import redis as redis_lib

    from ..config import settings
    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        val = r.get(key)
        if val is not None:
            return int(val)
    except (redis_lib.RedisError, OSError):
        logger.debug("game_cache_get_failed", extra={"key": key}, exc_info=True)
    return None


def _cache_set(key: str, game_id: int) -> None:
    """Cache a positive match. NEVER cache negatives (None).

    See ``_cache_get`` for catch-narrowing rationale.
    """
    import redis as redis_lib

    from ..config import settings
    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        r.set(key, str(game_id), ex=_GAME_CACHE_TTL)
    except (redis_lib.RedisError, OSError):
        logger.debug("game_cache_set_failed", extra={"key": key}, exc_info=True)


def _cache_delete(key: str) -> None:
    """Delete a cache entry (used when a game is deleted).

    See ``_cache_get`` for catch-narrowing rationale.
    """
    import redis as redis_lib

    from ..config import settings
    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        r.delete(key)
    except (redis_lib.RedisError, OSError):
        logger.debug("game_cache_delete_failed", extra={"key": key}, exc_info=True)
