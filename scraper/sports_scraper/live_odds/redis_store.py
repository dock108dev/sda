"""Redis-backed ephemeral storage for live in-game odds.

Key patterns:
  live:odds:{league}:{game_id}:{market_key}           -> latest snapshot (JSON)
  live:odds:history:{game_id}:{market_key}             -> ring buffer (Redis LIST)

All keys auto-expire via TTL — nothing persists long-term.
"""

from __future__ import annotations

import json
import time

from ..config import settings
from ..logging import logger

# TTL for latest snapshot (covers game + post-game browsing)
LIVE_SNAPSHOT_TTL_S = 6 * 3600  # 6 hours

# TTL for history ring buffer
HISTORY_TTL_S = 12 * 3600  # 12 hours

# Max entries in history ring buffer per game/market
HISTORY_MAX_LEN = 300

# Enable/disable debug history ring buffer
HISTORY_ENABLED = True


def _get_redis():
    """Get a Redis client for live odds storage."""
    import redis as redis_lib
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def _snapshot_key(league: str, game_id: int, market_key: str) -> str:
    return f"live:odds:{league}:{game_id}:{market_key}"


def _history_key(game_id: int, market_key: str) -> str:
    return f"live:odds:history:{game_id}:{market_key}"


def write_live_snapshot(
    league: str,
    game_id: int,
    market_key: str,
    selections: list[dict],
    provider: str,
    *,
    source_request_id: str = "",
    rate_remaining: int | None = None,
) -> None:
    """Write latest live odds snapshot to Redis with TTL.

    Args:
        league: League code (NBA, NHL, etc.)
        game_id: Internal game ID
        market_key: Market identifier (e.g., "spread", "total", "moneyline")
        selections: List of dicts with {selection, line, price, implied_prob?}
        provider: Provider name
        source_request_id: Optional request ID for tracing
        rate_remaining: Provider rate limit remaining count
    """
    snapshot = {
        "last_updated_at": time.time(),
        "provider": provider,
        "league": league,
        "game_id": game_id,
        "market_key": market_key,
        "selections": selections,
        "meta": {
            "source_request_id": source_request_id,
            "rate_remaining": rate_remaining,
        },
    }

    try:
        r = _get_redis()
        key = _snapshot_key(league, game_id, market_key)
        r.set(key, json.dumps(snapshot), ex=LIVE_SNAPSHOT_TTL_S)

        # Append to history ring buffer if enabled
        if HISTORY_ENABLED:
            hist_key = _history_key(game_id, market_key)
            compact = {
                "t": round(time.time()),
                "selections": [
                    {"s": s.get("selection", ""), "l": s.get("line"), "p": s.get("price")}
                    for s in selections
                ],
            }
            pipe = r.pipeline()
            pipe.lpush(hist_key, json.dumps(compact))
            pipe.ltrim(hist_key, 0, HISTORY_MAX_LEN - 1)
            pipe.expire(hist_key, HISTORY_TTL_S)
            pipe.execute()

    except Exception as exc:
        logger.warning(
            "live_odds_redis_write_error",
            league=league,
            game_id=game_id,
            market_key=market_key,
            error=str(exc),
        )


def read_live_snapshot(
    league: str, game_id: int, market_key: str
) -> dict | None:
    """Read latest live odds snapshot from Redis."""
    try:
        r = _get_redis()
        key = _snapshot_key(league, game_id, market_key)
        raw = r.get(key)
        if raw:
            data = json.loads(raw)
            data["ttl_seconds_remaining"] = r.ttl(key)
            return data
        return None
    except Exception as exc:
        logger.warning(
            "live_odds_redis_read_error",
            game_id=game_id,
            market_key=market_key,
            error=str(exc),
        )
        return None


def read_live_history(
    game_id: int, market_key: str, count: int = 50
) -> list[dict]:
    """Read recent entries from the history ring buffer."""
    try:
        r = _get_redis()
        key = _history_key(game_id, market_key)
        raw_list = r.lrange(key, 0, count - 1)
        return [json.loads(item) for item in raw_list]
    except Exception as exc:
        logger.warning(
            "live_odds_redis_history_error",
            game_id=game_id,
            market_key=market_key,
            error=str(exc),
        )
        return []


def get_all_live_keys_for_game(game_id: int) -> list[str]:
    """Return all live:odds:*:{game_id}:* keys (for debugging)."""
    try:
        r = _get_redis()
        return list(r.scan_iter(f"live:odds:*:{game_id}:*", count=100))
    except Exception:
        return []
