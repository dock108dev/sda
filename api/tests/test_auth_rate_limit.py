"""Tests for auth-specific rate limiting."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.rate_limit import (
    RateLimitMiddleware,
    _AUTH_STRICT_LIMIT,
    _AUTH_STRICT_WINDOW,
)


def _make_scope(path: str, client_ip: str = "1.2.3.4") -> dict:
    """Build a minimal ASGI HTTP scope."""
    return {
        "type": "http",
        "path": path,
        "query_string": b"",
        "headers": [],
        "server": ("localhost", 8000),
        "client": (client_ip, 12345),
    }


class TestAuthStrictRateLimiting:
    """Verify stricter limits on auth endpoints."""

    @pytest.mark.asyncio
    async def test_login_blocked_after_limit(self):
        """POST /auth/login should be blocked after _AUTH_STRICT_LIMIT attempts."""
        captured_status = []

        async def mock_app(scope, receive, send):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                captured_status.append(message.get("status"))

        middleware = RateLimitMiddleware(mock_app)

        # Exhaust the auth limit
        for _ in range(_AUTH_STRICT_LIMIT):
            captured_status.clear()
            scope = _make_scope("/auth/login")
            await middleware(scope, mock_receive, capture_send)
            # Should pass (no 429)
            assert 429 not in captured_status

        # Next request should be blocked
        captured_status.clear()
        scope = _make_scope("/auth/login")
        await middleware(scope, mock_receive, capture_send)
        assert 429 in captured_status

    @pytest.mark.asyncio
    async def test_signup_blocked_after_limit(self):
        """POST /auth/signup should also be rate-limited."""
        captured_status = []

        async def mock_app(scope, receive, send):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                captured_status.append(message.get("status"))

        middleware = RateLimitMiddleware(mock_app)

        for _ in range(_AUTH_STRICT_LIMIT):
            scope = _make_scope("/auth/signup")
            captured_status.clear()
            await middleware(scope, mock_receive, capture_send)

        captured_status.clear()
        scope = _make_scope("/auth/signup")
        await middleware(scope, mock_receive, capture_send)
        assert 429 in captured_status

    @pytest.mark.asyncio
    async def test_forgot_password_blocked_after_limit(self):
        """POST /auth/forgot-password should be rate-limited."""
        captured_status = []

        async def mock_app(scope, receive, send):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                captured_status.append(message.get("status"))

        middleware = RateLimitMiddleware(mock_app)

        for _ in range(_AUTH_STRICT_LIMIT):
            scope = _make_scope("/auth/forgot-password")
            captured_status.clear()
            await middleware(scope, mock_receive, capture_send)

        captured_status.clear()
        scope = _make_scope("/auth/forgot-password")
        await middleware(scope, mock_receive, capture_send)
        assert 429 in captured_status

    @pytest.mark.asyncio
    async def test_different_ips_have_separate_limits(self):
        """Rate limits are per-IP, not global."""
        captured_status = []

        async def mock_app(scope, receive, send):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                captured_status.append(message.get("status"))

        middleware = RateLimitMiddleware(mock_app)

        # Exhaust limit for IP 1.2.3.4
        for _ in range(_AUTH_STRICT_LIMIT):
            scope = _make_scope("/auth/login", client_ip="1.2.3.4")
            await middleware(scope, mock_receive, capture_send)

        # IP 1.2.3.4 should be blocked
        captured_status.clear()
        scope = _make_scope("/auth/login", client_ip="1.2.3.4")
        await middleware(scope, mock_receive, capture_send)
        assert 429 in captured_status

        # IP 5.6.7.8 should still work
        captured_status.clear()
        scope = _make_scope("/auth/login", client_ip="5.6.7.8")
        await middleware(scope, mock_receive, capture_send)
        assert 429 not in captured_status

    @pytest.mark.asyncio
    async def test_non_auth_endpoint_uses_global_limit(self):
        """Regular endpoints should use the global limit, not the strict one."""
        captured_status = []

        async def mock_app(scope, receive, send):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                captured_status.append(message.get("status"))

        middleware = RateLimitMiddleware(mock_app)

        # Send _AUTH_STRICT_LIMIT + 5 requests to a non-auth endpoint
        # (should NOT be blocked since global limit is 120)
        for _ in range(_AUTH_STRICT_LIMIT + 5):
            captured_status.clear()
            scope = _make_scope("/api/sports/games")
            await middleware(scope, mock_receive, capture_send)
            assert 429 not in captured_status

    @pytest.mark.asyncio
    async def test_exempt_endpoints_bypass_all_limits(self):
        """SSE and /auth/me should never be rate-limited."""
        captured_status = []

        async def mock_app(scope, receive, send):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                captured_status.append(message.get("status"))

        middleware = RateLimitMiddleware(mock_app)

        for _ in range(200):
            captured_status.clear()
            scope = _make_scope("/v1/sse")
            await middleware(scope, mock_receive, capture_send)
            assert 429 not in captured_status

    @pytest.mark.asyncio
    async def test_429_includes_retry_after_header(self):
        """Rate-limited responses should include Retry-After header."""
        captured_headers = {}

        async def mock_app(scope, receive, send):
            pass

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                for k, v in message.get("headers", []):
                    captured_headers[k.decode() if isinstance(k, bytes) else k] = (
                        v.decode() if isinstance(v, bytes) else v
                    )

        middleware = RateLimitMiddleware(mock_app)

        for _ in range(_AUTH_STRICT_LIMIT + 1):
            captured_headers.clear()
            scope = _make_scope("/auth/login")
            await middleware(scope, mock_receive, capture_send)

        assert "retry-after" in captured_headers
