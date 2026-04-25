"""In-memory rate limiting middleware with per-path tiers.

Provides three tiers:
- **Admin**: Tighter limit for `/api/admin/` routes (default 20 req/min).
  Configurable via ``ADMIN_RATE_LIMIT_REQUESTS`` / ``ADMIN_RATE_LIMIT_WINDOW_SECONDS``.
- **Global**: Default rate limit for all other non-exempt endpoints. Two
  buckets:
  - Requests with an ``X-API-Key`` header are keyed on the API key with a
    higher budget (``RATE_LIMIT_REQUESTS_KEYED``, default 600/min). Lets
    multiple workers behind one CI key share a single bucket without
    throttling each other off the per-IP one.
  - Requests without a key fall back to per-IP keying with the standard
    budget (``RATE_LIMIT_REQUESTS``, default 120/min).
- **Auth-strict**: Tightest limit for authentication endpoints that are
  vulnerable to brute-force attacks (login, signup, forgot-password,
  magic-link, reset-password).

All tiers use a sliding-window counter. The store is in-memory, suitable
for single-instance deployments. For horizontal scaling, replace with a
Redis-backed limiter (the per-key keying here is the prerequisite).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request
from starlette.responses import JSONResponse

from app.config import settings

_EXEMPT_PREFIXES = ("/v1/sse",)

# Auth endpoints with stricter limits to prevent brute-force attacks.
_AUTH_STRICT_PREFIXES = (
    "/auth/login",
    "/auth/signup",
    "/auth/forgot-password",
    "/auth/magic-link",
    "/auth/reset-password",
)

# 10 requests per 60 seconds for auth endpoints.
_AUTH_STRICT_LIMIT = 10
_AUTH_STRICT_WINDOW = 60

# Onboarding endpoints are publicly reachable (no API key) and accept
# prospect submissions, so we cap them aggressively to deter bot floods.
_ONBOARDING_STRICT_PREFIXES = ("/api/onboarding/",)
_ONBOARDING_STRICT_LIMIT = 5
_ONBOARDING_STRICT_WINDOW = 3600  # 5 requests per hour per IP

_ADMIN_PREFIX = "/api/admin/"


class RateLimitMiddleware:
    """Sliding-window rate limiter with auth-specific tightening."""

    def __init__(self, app: Callable) -> None:
        self.app = app
        # Global rate limit buckets, keyed by client IP (requests without a key).
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        # Global rate limit buckets, keyed by api_key (requests presenting one).
        self._keyed_requests: dict[str, deque[float]] = defaultdict(deque)
        # Auth-specific buckets (keyed by "ip:path_prefix").
        self._auth_requests: dict[str, deque[float]] = defaultdict(deque)
        # Admin-specific buckets (keyed by client IP).
        self._admin_requests: dict[str, deque[float]] = defaultdict(deque)
        # Onboarding-specific buckets (keyed by client IP).
        self._onboarding_requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # --- Auth-strict tier ---
        if any(path.startswith(p) for p in _AUTH_STRICT_PREFIXES):
            bucket_key = f"{client_ip}:{path}"
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

        # --- Onboarding-strict tier (public, prospect-facing forms) ---
        if any(path.startswith(p) for p in _ONBOARDING_STRICT_PREFIXES):
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

        # --- Admin tier (separate from global; does not fall through) ---
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

        # --- Global tier (consumer + all other routes) ---
        # Requests with an X-API-Key get their own keyed bucket with a
        # higher budget; unkeyed requests fall back to per-IP. Lets a single
        # CI key burst across many workers without per-IP throttling.
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
