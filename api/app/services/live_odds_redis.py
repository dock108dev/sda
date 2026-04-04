"""API-side Redis reader for live ephemeral odds data.

Provides sync reads from the Redis keys written by the scraper's
live_odds.redis_store module.

Snapshot format: each key holds ALL bookmakers' odds for a (game, market),
enabling fair-bet / +EV computation across books.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

# Simple circuit breaker: after a Redis failure, skip retries for this many
# seconds to avoid hammering a dead Redis on every request.
_CIRCUIT_BREAK_SECONDS = 30.0
_redis_error_until: float = 0.0

# Key patterns (must match scraper/sports_scraper/live_odds/redis_store.py)
_SNAPSHOT_KEY = "live:odds:{league}:{game_id}:{market_key}"
_HISTORY_KEY = "live:odds:history:{game_id}:{market_key}"


def _circuit_open() -> bool:
    """Return True if the circuit breaker is tripped (Redis recently failed)."""
    return time.time() < _redis_error_until


def _trip_circuit() -> None:
    """Trip the circuit breaker after a Redis failure."""
    global _redis_error_until
    _redis_error_until = time.time() + _CIRCUIT_BREAK_SECONDS


def _reset_circuit() -> None:
    """Reset the circuit breaker after a successful Redis call."""
    global _redis_error_until
    _redis_error_until = 0.0


def _get_redis():
    """Get a sync Redis client pointing at the scraper's Redis DB.

    The scraper writes live odds to CELERY_BROKER_URL (Redis DB 2),
    not the API's REDIS_URL (DB 0).  Use celery_broker so reads
    hit the same database as scraper writes.
    """
    import redis

    from app.config import settings
    return redis.from_url(settings.celery_broker, decode_responses=True)


def read_live_snapshot(
    league: str, game_id: int, market_key: str
) -> tuple[dict | None, str | None]:
    """Read latest live odds snapshot from Redis.

    Returns:
        (data, error) — data is the snapshot dict or None; error is a
        human-readable string if Redis was unreachable, else None.
    """
    if _circuit_open():
        return None, "redis_circuit_open"
    try:
        r = _get_redis()
        key = _SNAPSHOT_KEY.format(league=league, game_id=game_id, market_key=market_key)
        raw = r.get(key)
        _reset_circuit()
    except Exception as exc:
        _trip_circuit()
        logger.warning("live_odds_redis_read_error", extra={
            "game_id": game_id, "market_key": market_key, "error": str(exc)
        })
        return None, f"redis_error: {exc}"
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as exc:
            logger.warning("live_odds_redis_json_error", extra={
                "game_id": game_id, "market_key": market_key, "error": str(exc)
            })
            return None, f"json_error: {exc}"
        data["ttl_seconds_remaining"] = r.ttl(key)
        return data, None
    return None, None


def read_all_live_snapshots_for_game(
    league: str, game_id: int
) -> tuple[dict[str, dict], str | None]:
    """Read all live snapshots for a game (all market keys).

    Returns:
        (result, error) — result is a dict mapping market_key -> snapshot
        dict; error is a human-readable string if Redis was unreachable,
        else None.
    """
    if _circuit_open():
        return {}, "redis_circuit_open"
    try:
        r = _get_redis()
        pattern = f"live:odds:{league}:{game_id}:*"
        result: dict[str, dict] = {}
        for key in r.scan_iter(pattern, count=50):
            if ":history:" in key:
                continue
            raw = r.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                except (ValueError, TypeError):
                    continue  # skip malformed keys, don't trip circuit
                market_key = key.rsplit(":", 1)[-1]
                data["ttl_seconds_remaining"] = r.ttl(key)
                result[market_key] = data
        _reset_circuit()
        return result, None
    except Exception as exc:
        _trip_circuit()
        logger.warning("live_odds_redis_scan_error", extra={
            "game_id": game_id, "error": str(exc)
        })
        return {}, f"redis_error: {exc}"


def read_live_history(
    game_id: int, market_key: str, count: int = 50
) -> tuple[list[dict], str | None]:
    """Read recent entries from the history ring buffer.

    Returns:
        (entries, error) — entries is a list of history dicts; error is a
        human-readable string if Redis was unreachable, else None.
    """
    if _circuit_open():
        return [], "redis_circuit_open"
    try:
        r = _get_redis()
        key = _HISTORY_KEY.format(game_id=game_id, market_key=market_key)
        raw_list = r.lrange(key, 0, count - 1)
        _reset_circuit()
    except Exception as exc:
        _trip_circuit()
        logger.warning("live_odds_redis_history_error", extra={
            "game_id": game_id, "market_key": market_key, "error": str(exc)
        })
        return [], f"redis_error: {exc}"
    entries = []
    for item in raw_list:
        try:
            entries.append(json.loads(item))
        except (ValueError, TypeError):
            continue  # skip malformed entries, don't trip circuit
    return entries, None


def discover_live_game_ids(league: str | None = None) -> list[tuple[str, int]]:
    """Scan Redis for all games that currently have live odds data.

    Returns list of (league_code, game_id) tuples.
    """
    if _circuit_open():
        return []
    try:
        r = _get_redis()
        pattern = f"live:odds:{league}:*" if league else "live:odds:*"
        seen: set[tuple[str, int]] = set()
        for key in r.scan_iter(pattern, count=200):
            if ":history:" in key:
                continue
            # Key format: live:odds:{league}:{game_id}:{market_key}
            parts = key.split(":")
            if len(parts) >= 5:
                league_code = parts[2]
                try:
                    game_id = int(parts[3])
                    seen.add((league_code, game_id))
                except (ValueError, IndexError):
                    continue
        _reset_circuit()
        return sorted(seen)
    except Exception as exc:
        _trip_circuit()
        logger.warning("live_odds_redis_discover_error", extra={"error": str(exc)})
        return []
