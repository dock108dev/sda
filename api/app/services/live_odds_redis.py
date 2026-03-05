"""API-side Redis reader for live ephemeral odds data.

Provides async-compatible reads from the Redis keys written by the scraper's
live_odds.redis_store module.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Key patterns (must match scraper/sports_scraper/live_odds/redis_store.py)
_SNAPSHOT_KEY = "live:odds:{league}:{game_id}:{market_key}"
_HISTORY_KEY = "live:odds:history:{game_id}:{market_key}"


def _get_redis():
    """Get a sync Redis client. Lazy import to avoid startup validation issues."""
    import redis
    from app.config import settings
    return redis.from_url(settings.redis_url, decode_responses=True)


def read_live_snapshot(
    league: str, game_id: int, market_key: str
) -> dict | None:
    """Read latest live odds snapshot from Redis."""
    try:
        r = _get_redis()
        key = _SNAPSHOT_KEY.format(league=league, game_id=game_id, market_key=market_key)
        raw = r.get(key)
        if raw:
            data = json.loads(raw)
            data["ttl_seconds_remaining"] = r.ttl(key)
            return data
        return None
    except Exception as exc:
        logger.warning("live_odds_redis_read_error", extra={
            "game_id": game_id, "market_key": market_key, "error": str(exc)
        })
        return None


def read_live_history(
    game_id: int, market_key: str, count: int = 50
) -> list[dict]:
    """Read recent entries from the history ring buffer."""
    try:
        r = _get_redis()
        key = _HISTORY_KEY.format(game_id=game_id, market_key=market_key)
        raw_list = r.lrange(key, 0, count - 1)
        return [json.loads(item) for item in raw_list]
    except Exception as exc:
        logger.warning("live_odds_redis_history_error", extra={
            "game_id": game_id, "market_key": market_key, "error": str(exc)
        })
        return []


def read_all_live_snapshots_for_game(
    league: str, game_id: int
) -> dict[str, dict]:
    """Read all live snapshots for a game (all market keys)."""
    try:
        r = _get_redis()
        pattern = f"live:odds:{league}:{game_id}:*"
        result: dict[str, dict] = {}
        for key in r.scan_iter(pattern, count=50):
            raw = r.get(key)
            if raw:
                data = json.loads(raw)
                market_key = key.rsplit(":", 1)[-1]
                data["ttl_seconds_remaining"] = r.ttl(key)
                result[market_key] = data
        return result
    except Exception as exc:
        logger.warning("live_odds_redis_scan_error", extra={
            "game_id": game_id, "error": str(exc)
        })
        return {}
