"""Generic Redis-backed response cache for read-heavy GET endpoints.

Designed for the same multi-CI-worker scenario the FairBet odds cache solves:
many Playwright workers / page loads issue identical GETs within a few
seconds. Caching the response shaves DB load and shaves p99 under burst.

Behavior:
- Keyed by (prefix, sha256 of normalized query params).
- TTL is per-call (caller decides). Defaults to 15s in callers.
- Authenticated requests (Authorization or Cookie header) bypass the cache
  to avoid leaking per-user state through a shared key.
- Redis errors trip a short circuit breaker so we don't pile-on retries
  when Redis is sick — same pattern as ``fairbet_runtime``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from fastapi import Request

from app.config import settings
from app.services.circuit_breaker_registry import registry as _cb_registry

logger = logging.getLogger(__name__)

_BREAKER_NAME = "response_cache_redis"
_CIRCUIT_SECONDS = 15.0
_redis_error_until: float = 0.0

_cb_registry.register(_BREAKER_NAME)


def _circuit_open() -> bool:
    return time.time() < _redis_error_until


def _trip_circuit(reason: str) -> None:
    global _redis_error_until
    _redis_error_until = time.time() + _CIRCUIT_SECONDS
    _cb_registry.record_trip(_BREAKER_NAME, reason)


def _reset_circuit() -> None:
    global _redis_error_until
    _redis_error_until = 0.0
    _cb_registry.record_reset(_BREAKER_NAME)


def _get_redis_client():
    import redis

    return redis.from_url(settings.redis_url, decode_responses=True)


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Sort keys and list values for a stable cache key."""
    normalized: dict[str, Any] = {}
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, list):
            normalized[key] = sorted(str(v) for v in value)
        else:
            normalized[key] = value
    return normalized


def build_cache_key(prefix: str, params: dict[str, Any]) -> str:
    norm = _normalize_params(params)
    raw = json.dumps(norm, separators=(",", ":"), sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"response_cache:{prefix}:{digest}"


def should_bypass_cache(request: Request | None) -> bool:
    """Skip the cache for any request that carries credentials.

    A shared response cache must not leak per-user state. Treat both
    ``Authorization`` (bearer) and ``Cookie`` (session) as signals that the
    response could be user-scoped.
    """
    if request is None:
        return False
    headers = request.headers
    return bool(headers.get("authorization") or headers.get("cookie"))


def get_cached(key: str) -> dict[str, Any] | None:
    if _circuit_open():
        return None
    try:
        client = _get_redis_client()
        raw = client.get(key)
        _reset_circuit()
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        _trip_circuit(f"response_cache_read_error: {exc}")
        logger.warning("response_cache_read_error", extra={"error": str(exc)})
        return None


def set_cached(key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
    if _circuit_open():
        return
    try:
        client = _get_redis_client()
        client.setex(key, ttl_seconds, json.dumps(payload, default=str))
        _reset_circuit()
    except Exception as exc:
        _trip_circuit(f"response_cache_write_error: {exc}")
        logger.warning("response_cache_write_error", extra={"error": str(exc)})
