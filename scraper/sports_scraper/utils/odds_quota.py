"""Weekly credit quota guard for The Odds API.

Tracks credits consumed per ISO week in Redis and blocks requests
when the weekly cap is reached, ensuring backfills don't starve
live data polling.

Redis key: ``odds_api:weekly_credits:{year}:{week}`` with an 8-day TTL
so each week's counter self-cleans.
"""

from __future__ import annotations

from datetime import date

from ..logging import logger

# Key prefix in Redis
_KEY_PREFIX = "odds_api:weekly_credits"

# TTL slightly longer than a week so the key survives the full ISO week
_KEY_TTL_SECONDS = 8 * 86_400  # 8 days


def _week_key() -> str:
    """Return the Redis key for the current ISO week."""
    iso = date.today().isocalendar()
    return f"{_KEY_PREFIX}:{iso[0]}:{iso[1]}"


def _get_redis():  # noqa: ANN202
    """Return a Redis client (import deferred to avoid circular deps)."""
    import redis as redis_lib

    from ..config import settings

    return redis_lib.from_url(settings.redis_url)


def get_weekly_cap() -> int:
    """Return the configured weekly credit cap."""
    from ..config import settings

    return settings.odds_config.weekly_credit_cap


def record_usage(credits_used: int) -> int:
    """Increment weekly usage counter by *credits_used*.

    Returns the new cumulative total for the week.
    """
    if credits_used <= 0:
        return get_weekly_usage()

    try:
        r = _get_redis()
        key = _week_key()
        new_total = r.incrby(key, credits_used)
        # Ensure TTL is set (idempotent — only sets if no TTL yet)
        if r.ttl(key) < 0:
            r.expire(key, _KEY_TTL_SECONDS)
        return int(new_total)
    except Exception as exc:
        logger.warning("odds_quota_record_failed", error=str(exc))
        return 0


def get_weekly_usage() -> int:
    """Return credits used so far this ISO week."""
    try:
        r = _get_redis()
        val = r.get(_week_key())
        return int(val) if val else 0
    except Exception as exc:
        logger.warning("odds_quota_read_failed", error=str(exc))
        return 0


def is_quota_exceeded() -> bool:
    """Return True if the weekly credit cap has been reached."""
    cap = get_weekly_cap()
    used = get_weekly_usage()
    exceeded = used >= cap
    if exceeded:
        logger.warning(
            "odds_weekly_quota_exceeded",
            used=used,
            cap=cap,
            message="Weekly credit cap reached — blocking Odds API requests",
        )
    return exceeded


def quota_status() -> dict:
    """Return a dict with current quota stats (useful for debugging/admin)."""
    cap = get_weekly_cap()
    used = get_weekly_usage()
    return {
        "weekly_cap": cap,
        "weekly_used": used,
        "weekly_remaining": max(0, cap - used),
        "exceeded": used >= cap,
        "week_key": _week_key(),
    }
