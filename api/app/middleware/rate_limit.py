"""In-memory rate limiting middleware with per-path tiers.

Provides two tiers:
- **Global**: Default rate limit for all endpoints (configurable via
  ``RATE_LIMIT_REQUESTS`` / ``RATE_LIMIT_WINDOW_SECONDS``).
- **Auth-strict**: Tighter limit for authentication endpoints that are
  vulnerable to brute-force attacks (login, signup, forgot-password,
  magic-link, reset-password).

Both tiers use a sliding-window counter keyed by client IP. This is
an in-memory implementation suitable for single-instance deployments.
For horizontal scaling, replace with a Redis-backed limiter.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request
from starlette.responses import JSONResponse

from app.config import settings


_EXEMPT_PREFIXES = ("/v1/sse", "/auth/me")

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


class RateLimitMiddleware:
    """Sliding-window rate limiter with auth-specific tightening."""

    def __init__(self, app: Callable) -> None:
        self.app = app
        # Global rate limit buckets (keyed by client IP).
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        # Auth-specific buckets (keyed by "ip:path_prefix").
        self._auth_requests: dict[str, deque[float]] = defaultdict(deque)

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

        # --- Global tier ---
        window = settings.rate_limit_window_seconds
        limit = settings.rate_limit_requests

        request_times = self._requests[client_ip]
        while request_times and request_times[0] <= now - window:
            request_times.popleft()

        if len(request_times) >= limit:
            response = JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(window)},
            )
            await response(scope, receive, send)
            return

        request_times.append(now)
        await self.app(scope, receive, send)
