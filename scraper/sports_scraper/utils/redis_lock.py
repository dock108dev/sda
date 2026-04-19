"""Shared Redis distributed lock helpers.

Uses a token-based pattern: acquire stores a UUID, release only deletes
if the stored value matches (via an atomic Lua script). This prevents
a holder whose TTL expired from accidentally deleting a lock that a
second process has since acquired.
"""
from __future__ import annotations

import uuid

from ..logging import logger

# Named lock timeout constants — use these instead of bare integers
LOCK_TIMEOUT_5MIN = 300
LOCK_TIMEOUT_10MIN = 600
LOCK_TIMEOUT_30MIN = 1800
LOCK_TIMEOUT_1HOUR = 3600

# Lua script: compare-and-delete (atomic on Redis server)
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def acquire_redis_lock(lock_name: str, timeout: int = LOCK_TIMEOUT_5MIN) -> str | None:
    """Try to acquire a Redis lock. Returns unique token if acquired, None otherwise."""
    try:
        import redis as redis_lib

        from ..config import settings

        token = str(uuid.uuid4())
        r = redis_lib.from_url(settings.redis_url)
        if r.set(lock_name, token, nx=True, ex=timeout):
            return token
        return None
    except Exception as exc:
        logger.warning("redis_lock_failed", lock=lock_name, error=str(exc))
        return None  # Fail-closed: treat Redis failure as lock-not-acquired


def release_redis_lock(lock_name: str, token: str) -> None:
    """Release a Redis lock only if we still own it (token matches)."""
    try:
        import redis as redis_lib

        from ..config import settings

        r = redis_lib.from_url(settings.redis_url)
        r.eval(_RELEASE_SCRIPT, 1, lock_name, token)
    except Exception as exc:
        logger.warning("redis_unlock_failed", lock=lock_name, error=str(exc))


def force_release_lock(lock_name: str) -> bool:
    """Unconditionally delete a lock key, regardless of who owns it.

    Use only when a lock is known to be orphaned (e.g., the owning
    worker crashed and the TTL hasn't expired yet).
    """
    try:
        import redis as redis_lib

        from ..config import settings

        r = redis_lib.from_url(settings.redis_url)
        deleted = r.delete(lock_name)
        if deleted:
            logger.info("force_released_lock", lock=lock_name)
        return bool(deleted)
    except Exception as exc:
        logger.warning("force_release_lock_failed", lock=lock_name, error=str(exc))
        return False


def clear_all_locks() -> int:
    """Delete all ``lock:*`` keys in Redis. Call on worker startup to clear stale locks
    left behind by a crashed/restarted container."""
    try:
        import redis as redis_lib

        from ..config import settings

        r = redis_lib.from_url(settings.redis_url)
        keys = r.keys("lock:*")
        if keys:
            deleted = r.delete(*keys)
            logger.info("stale_locks_cleared", count=deleted, keys=[k.decode() for k in keys])
            return deleted
        return 0
    except Exception as exc:
        logger.warning("clear_locks_failed", error=str(exc))
        return 0
