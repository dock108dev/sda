"""Per-IP-per-club sliding-window rate limiter for public entry submissions.

Uses the Redis-backed sliding-window helper from ``fairbet_runtime``. On rate
limit hit, emits a structured abuse log (``event=entry_abuse``) for ops
visibility.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.fairbet_runtime import redis_allow_request

logger = logging.getLogger(__name__)

ENTRY_RATE_LIMIT = 5
ENTRY_RATE_WINDOW_SECONDS = 600  # 10 minutes
_KEY_PREFIX = "entries"


def _bucket_key(club_identifier: str, client_ip: str) -> str:
    return f"{_KEY_PREFIX}:{club_identifier}:{client_ip}"


async def check_entry_rate_limit(
    club_identifier: str,
    client_ip: str,
    pool_id: int,
    *,
    limit: int = ENTRY_RATE_LIMIT,
    window_seconds: int = ENTRY_RATE_WINDOW_SECONDS,
) -> tuple[bool, int]:
    """Return ``(allowed, retry_after_seconds)`` for the given IP and club.

    Emits a structured abuse log on rate-limit hits so ops can detect
    high-volume sources.
    """
    key = _bucket_key(club_identifier, client_ip)
    allowed, retry_after = await asyncio.to_thread(
        redis_allow_request, key, limit, window_seconds
    )
    if not allowed:
        logger.warning(
            "entry_abuse_rate_limited",
            extra={
                "event": "entry_abuse",
                "client_ip": client_ip,
                "club": club_identifier,
                "pool_id": pool_id,
                "limit": limit,
                "window_seconds": window_seconds,
            },
        )
    return allowed, retry_after
