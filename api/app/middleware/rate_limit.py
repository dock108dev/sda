"""Rate limiting middleware with per-path tiers.

Tiers:
- **SSE** (``/v1/sse``): generous keyed limit (API key from ``X-API-Key`` or
  ``api_key`` query — browsers cannot set headers on EventSource, so query is
  supported but discouraged for server-side clients). No longer exempt from
  all throttling.
- **Admin**: Tighter limit for ``/api/admin/`` routes.
- **Global**: Per-IP or per-``X-API-Key`` sliding window.
- **Auth-strict**: Login/signup/forgot-password/etc.
- **Onboarding-strict**: Public onboarding forms.

When ``RATE_LIMIT_USE_REDIS=true``, auth-strict and onboarding-strict use
Redis fixed-window counters so limits are shared across API replicas. On
Redis errors the middleware falls back to the in-memory sliding window.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from fastapi import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.metrics import rate_limit_redis_fallback_total

logger = logging.getLogger(__name__)

# Auth endpoints with stricter limits to prevent brute-force attacks.
_AUTH_STRICT_PREFIXES = (
    "/auth/login",
    "/auth/signup",
    "/auth/forgot-password",
    "/auth/magic-link",
    "/auth/reset-password",
)

_AUTH_STRICT_LIMIT = 10
_AUTH_STRICT_WINDOW = 60

_ONBOARDING_STRICT_PREFIXES = ("/api/onboarding/",)
_ONBOARDING_STRICT_LIMIT = 5
_ONBOARDING_STRICT_WINDOW = 3600

_ADMIN_PREFIX = "/api/admin/"
_SSE_PREFIX = "/v1/sse"

_rl_redis: Any = None


async def _get_rl_redis() -> Any:
    global _rl_redis
    if _rl_redis is None:
        import redis.asyncio as aioredis

        _rl_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _rl_redis


async def _redis_fixed_window_allow(redis_key: str, limit: int, window: int) -> bool:
    """Return True if request is allowed (counter <= limit after INCR)."""
    r = await _get_rl_redis()
    slot = int(time.time() // window)
    rk = f"{redis_key}:{slot}"
    n = await r.incr(rk)
    if n == 1:
        await r.expire(rk, window * 2 + 1)
    return n <= limit


class RateLimitMiddleware:
    """Sliding-window rate limiter with optional Redis for strict public tiers."""

    def __init__(self, app: Callable) -> None:
        self.app = app
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._keyed_requests: dict[str, deque[float]] = defaultdict(deque)
        self._auth_requests: dict[str, deque[float]] = defaultdict(deque)
        self._admin_requests: dict[str, deque[float]] = defaultdict(deque)
        self._onboarding_requests: dict[str, deque[float]] = defaultdict(deque)
        self._sse_requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        request = Request(scope, receive=receive)
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # --- SSE tier (was fully exempt; now keyed, generous budget) ---
        if path.startswith(_SSE_PREFIX):
            key_material = (
                request.headers.get("x-api-key")
                or request.query_params.get("api_key")
                or client_ip
            )
            bucket_key = f"sse:{key_material[:200]}"
            window = settings.rate_limit_window_seconds_keyed
            limit = settings.rate_limit_requests_keyed
            sse_times = self._sse_requests[bucket_key]
            while sse_times and sse_times[0] <= now - window:
                sse_times.popleft()
            if len(sse_times) >= limit:
                response = JSONResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(window)},
                )
                await response(scope, receive, send)
                return
            sse_times.append(now)
            await self.app(scope, receive, send)
            return

        # --- Auth-strict tier (Redis replaces in-memory only for this tier; still
        #     falls through to global limits unless Redis denied the request) ---
        if any(path.startswith(p) for p in _AUTH_STRICT_PREFIXES):
            bucket_key = f"{client_ip}:{path}"
            skip_memory_auth = False
            if settings.rate_limit_use_redis:
                try:
                    rk = f"rl:auth:{bucket_key}"
                    if not await _redis_fixed_window_allow(
                        rk, _AUTH_STRICT_LIMIT, _AUTH_STRICT_WINDOW
                    ):
                        response = JSONResponse(
                            {"detail": "Too many attempts. Please try again later."},
                            status_code=429,
                            headers={"Retry-After": str(_AUTH_STRICT_WINDOW)},
                        )
                        await response(scope, receive, send)
                        return
                    skip_memory_auth = True
                except Exception:
                    rate_limit_redis_fallback_total.labels("auth_strict").inc()
                    # Log only static fields: path/request data and exception objects are
                    # treated as potentially credential-bearing by security scanners.
                    logger.warning(
                        "rate_limit_redis_auth_fallback",
                        extra={"tier": "auth_strict"},
                    )

            if not skip_memory_auth:
                auth_times = self._auth_requests[bucket_key]
                while auth_times and auth_times[0] <= now - _AUTH_STRICT_WINDOW:
                    auth_times.popleft()
                if len(auth_times) >= _AUTH_STRICT_LIMIT:
                    response = JSONResponse(
                        {"detail": "Too many attempts. Please try again later."},
                        status_code=429,
                        headers={"Retry-After": str(_AUTH_STRICT_WINDOW)},
                    )
                    await response(scope, receive, send)
                    return
                auth_times.append(now)

        # --- Onboarding-strict tier ---
        if any(path.startswith(p) for p in _ONBOARDING_STRICT_PREFIXES):
            if settings.rate_limit_use_redis:
                try:
                    rk = f"rl:onboarding:{client_ip}"
                    if not await _redis_fixed_window_allow(
                        rk, _ONBOARDING_STRICT_LIMIT, _ONBOARDING_STRICT_WINDOW
                    ):
                        response = JSONResponse(
                            {"detail": "Too many submissions. Please try again later."},
                            status_code=429,
                            headers={"Retry-After": str(_ONBOARDING_STRICT_WINDOW)},
                        )
                        await response(scope, receive, send)
                        return
                    await self.app(scope, receive, send)
                    return
                except Exception:
                    rate_limit_redis_fallback_total.labels("onboarding_strict").inc()
                    logger.warning(
                        "rate_limit_redis_onboarding_fallback",
                        extra={"tier": "onboarding_strict"},
                    )

            onboarding_times = self._onboarding_requests[client_ip]
            while (
                onboarding_times
                and onboarding_times[0] <= now - _ONBOARDING_STRICT_WINDOW
            ):
                onboarding_times.popleft()
            if len(onboarding_times) >= _ONBOARDING_STRICT_LIMIT:
                response = JSONResponse(
                    {"detail": "Too many submissions. Please try again later."},
                    status_code=429,
                    headers={"Retry-After": str(_ONBOARDING_STRICT_WINDOW)},
                )
                await response(scope, receive, send)
                return
            onboarding_times.append(now)
            await self.app(scope, receive, send)
            return

        # --- Admin tier ---
        if path.startswith(_ADMIN_PREFIX):
            admin_limit = settings.admin_rate_limit_requests
            admin_window = settings.admin_rate_limit_window_seconds
            admin_times = self._admin_requests[client_ip]
            while admin_times and admin_times[0] <= now - admin_window:
                admin_times.popleft()
            if len(admin_times) >= admin_limit:
                response = JSONResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(admin_window)},
                )
                await response(scope, receive, send)
                return
            admin_times.append(now)
            await self.app(scope, receive, send)
            return

        # --- Global tier ---
        api_key = request.headers.get("x-api-key")
        if api_key:
            window = settings.rate_limit_window_seconds_keyed
            limit = settings.rate_limit_requests_keyed
            bucket = self._keyed_requests[api_key]
        else:
            window = settings.rate_limit_window_seconds
            limit = settings.rate_limit_requests
            bucket = self._requests[client_ip]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            response = JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(window)},
            )
            await response(scope, receive, send)
            return
        bucket.append(now)
        await self.app(scope, receive, send)
