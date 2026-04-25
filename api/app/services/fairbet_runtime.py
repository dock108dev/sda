"""Runtime helpers for FairBet odds pagination, cache, and snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.services.circuit_breaker_registry import registry as _cb_registry

logger = logging.getLogger(__name__)

_BREAKER_NAME = "fairbet_redis"
_CACHE_PREFIX = "fairbet:odds:cache:v1"
_SNAPSHOT_PREFIX = "fairbet:odds:snapshot:v1"
_LIMITER_PREFIX = "ratelimit:fairbet:odds"
_redis_error_until: float = 0.0
_REDIS_CIRCUIT_SECONDS = 15.0

_cb_registry.register(_BREAKER_NAME)


def _circuit_open() -> bool:
    return time.time() < _redis_error_until


def cache_status() -> dict[str, Any]:
    """Healthcheck-friendly view of the FairBet Redis circuit breaker."""
    now = time.time()
    is_open = now < _redis_error_until
    return {
        "name": _BREAKER_NAME,
        "open": is_open,
        "open_for_seconds": max(0.0, _redis_error_until - now) if is_open else 0.0,
    }


def _trip_circuit(reason: str = "redis_error") -> None:
    global _redis_error_until
    _redis_error_until = time.time() + _REDIS_CIRCUIT_SECONDS
    _cb_registry.record_trip(_BREAKER_NAME, reason)


def _reset_circuit() -> None:
    global _redis_error_until
    _redis_error_until = 0.0
    _cb_registry.record_reset(_BREAKER_NAME)


def get_redis_client():
    """Return sync Redis client used for low-latency cache operations."""
    import redis

    return redis.from_url(settings.redis_url, decode_responses=True)


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    padding = "=" * ((4 - len(cursor) % 4) % 4)
    raw = base64.urlsafe_b64decode((cursor + padding).encode())
    return json.loads(raw.decode())


def normalize_query_dict(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize query params into a deterministic JSON-safe shape."""
    normalized: dict[str, Any] = {}
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, list):
            normalized[key] = sorted(value)
        else:
            normalized[key] = value
    return normalized


def build_query_hash(params: dict[str, Any]) -> str:
    norm = normalize_query_dict(params)
    raw = json.dumps(norm, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def cache_key(query_hash: str, content_version: str) -> str:
    return f"{_CACHE_PREFIX}:{query_hash}:{content_version}"


def get_cached_response(query_hash: str, content_version: str) -> dict[str, Any] | None:
    if _circuit_open() or not settings.fairbet_odds_cache_enabled:
        return None
    try:
        r = get_redis_client()
        raw = r.get(cache_key(query_hash, content_version))
        _reset_circuit()
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        _trip_circuit(f"fairbet_cache_read_error: {exc}")
        logger.warning("fairbet_cache_read_error", extra={"error": str(exc)})
        return None


def set_cached_response(
    query_hash: str,
    content_version: str,
    payload: dict[str, Any],
    ttl_seconds: int | None = None,
) -> None:
    if _circuit_open() or not settings.fairbet_odds_cache_enabled:
        return
    ttl = ttl_seconds or settings.fairbet_odds_cache_ttl_seconds
    try:
        r = get_redis_client()
        r.setex(cache_key(query_hash, content_version), ttl, json.dumps(payload, default=str))
        _reset_circuit()
    except Exception as exc:
        _trip_circuit(f"fairbet_cache_write_error: {exc}")
        logger.warning("fairbet_cache_write_error", extra={"error": str(exc)})


def create_snapshot(
    query_hash: str, items: list[dict[str, Any]], total: int
) -> tuple[str | None, datetime]:
    """Persist EV-sorted snapshot for stable cursor paging."""
    if _circuit_open():
        return None, datetime.now(UTC)

    sid = str(uuid.uuid4())
    generated = datetime.now(UTC)
    payload = {
        "query_hash": query_hash,
        "generated_at": generated.isoformat(),
        "items": items,
        "total": total,
    }
    try:
        r = get_redis_client()
        r.setex(
            f"{_SNAPSHOT_PREFIX}:{sid}",
            settings.fairbet_odds_snapshot_ttl_seconds,
            json.dumps(payload, default=str),
        )
        _reset_circuit()
    except Exception as exc:
        _trip_circuit(f"fairbet_snapshot_write_error: {exc}")
        logger.warning("fairbet_snapshot_write_error", extra={"error": str(exc)})
        return None, generated
    return sid, generated


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    if _circuit_open():
        return None
    try:
        r = get_redis_client()
        raw = r.get(f"{_SNAPSHOT_PREFIX}:{snapshot_id}")
        _reset_circuit()
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        _trip_circuit(f"fairbet_snapshot_read_error: {exc}")
        logger.warning("fairbet_snapshot_read_error", extra={"error": str(exc)})
        return None


def redis_allow_request(client_key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """Sliding-window allow/deny using Redis sorted set."""
    now_ms = int(time.time() * 1000)
    window_start = now_ms - (window_seconds * 1000)
    key = f"{_LIMITER_PREFIX}:{client_key}"
    if _circuit_open():
        return True, 0

    try:
        r = get_redis_client()
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        _, current = pipe.execute()
        current_count = int(current or 0)
        if current_count >= limit:
            retry_after = max(1, window_seconds)
            return False, retry_after

        member = f"{now_ms}-{uuid.uuid4().hex[:8]}"
        pipe = r.pipeline()
        pipe.zadd(key, {member: now_ms})
        pipe.expire(key, window_seconds)
        pipe.execute()
        _reset_circuit()
        return True, 0
    except Exception as exc:
        _trip_circuit()
        logger.warning("fairbet_limiter_redis_error", extra={"error": str(exc)})
        return True, 0
