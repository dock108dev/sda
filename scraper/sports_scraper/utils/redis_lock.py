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
        return str(uuid.uuid4())  # Proceed anyway if Redis is down (return dummy token)


def release_redis_lock(lock_name: str, token: str) -> None:
    """Release a Redis lock only if we still own it (token matches)."""
    try:
        import redis as redis_lib

        from ..config import settings

        r = redis_lib.from_url(settings.redis_url)
        r.eval(_RELEASE_SCRIPT, 1, lock_name, token)
    except Exception as exc:
        logger.warning("redis_unlock_failed", lock=lock_name, error=str(exc))
