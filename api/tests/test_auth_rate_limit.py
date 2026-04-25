"""Tests for auth-specific rate limiting."""


import pytest

from app.config import settings
from app.middleware.rate_limit import (
    _AUTH_STRICT_LIMIT,
    RateLimitMiddleware,
)


def _make_scope(
    path: str,
    client_ip: str = "1.2.3.4",
    *,
    api_key: str | None = None,
) -> dict:
    """Build a minimal ASGI HTTP scope, optionally with an X-API-Key header."""
    headers: list[tuple[bytes, bytes]] = []
    if api_key is not None:
        headers.append((b"x-api-key", api_key.encode()))
    return {
        "type": "http",
        "path": path,
        "query_string": b"",
        "headers": headers,
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


class TestPerKeyRateLimiting:
    """Per-API-key bucket on the global tier."""

    async def _drive(self, middleware, scope, count: int) -> list[int]:
        statuses: list[int] = []
        last_status: list[int] = []

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                last_status.append(message.get("status"))

        for _ in range(count):
            last_status.clear()
            await middleware(scope, mock_receive, capture_send)
            # If the inner app didn't fire (and our mock_app doesn't send a
            # response), last_status will be empty — treat that as "passed".
            statuses.append(last_status[-1] if last_status else 200)
        return statuses

    @pytest.mark.asyncio
    async def test_keyed_bucket_isolated_from_ip_bucket(self, monkeypatch):
        """Same IP, different api_keys → independent buckets."""
        monkeypatch.setattr(settings, "rate_limit_requests", 3)
        monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
        monkeypatch.setattr(settings, "rate_limit_requests_keyed", 5)
        monkeypatch.setattr(settings, "rate_limit_window_seconds_keyed", 60)

        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)

        # Exhaust the IP bucket with no key (limit=3).
        ip_results = await self._drive(
            middleware, _make_scope("/api/games", client_ip="1.1.1.1"), 4
        )
        assert ip_results.count(429) == 1

        # A keyed request from the SAME IP should still pass: independent bucket.
        keyed_results = await self._drive(
            middleware,
            _make_scope("/api/games", client_ip="1.1.1.1", api_key="ci-key-1"),
            5,
        )
        assert 429 not in keyed_results

        # The 6th keyed request from the same key gets 429 (limit=5).
        sixth = await self._drive(
            middleware,
            _make_scope("/api/games", client_ip="1.1.1.1", api_key="ci-key-1"),
            1,
        )
        assert sixth == [429]

    @pytest.mark.asyncio
    async def test_same_key_shared_across_ips(self, monkeypatch):
        """One api_key used by N CI workers behind one IP shares the bucket
        across all of them — so the budget reflects key, not IP."""
        monkeypatch.setattr(settings, "rate_limit_requests_keyed", 4)
        monkeypatch.setattr(settings, "rate_limit_window_seconds_keyed", 60)

        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)

        # Two requests from IP A.
        results_a = await self._drive(
            middleware,
            _make_scope("/api/games", client_ip="10.0.0.1", api_key="ci-key-2"),
            2,
        )
        # Two from IP B with the SAME key.
        results_b = await self._drive(
            middleware,
            _make_scope("/api/games", client_ip="10.0.0.2", api_key="ci-key-2"),
            2,
        )
        assert 429 not in results_a + results_b

        # The 5th request anywhere on this key trips the limit.
        results_c = await self._drive(
            middleware,
            _make_scope("/api/games", client_ip="10.0.0.3", api_key="ci-key-2"),
            1,
        )
        assert results_c == [429]

    @pytest.mark.asyncio
    async def test_missing_key_falls_back_to_ip_bucket(self, monkeypatch):
        """No X-API-Key → keyed by IP at the standard limit."""
        monkeypatch.setattr(settings, "rate_limit_requests", 2)
        monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)

        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)

        results = await self._drive(
            middleware, _make_scope("/api/games", client_ip="2.2.2.2"), 3
        )
        assert results.count(429) == 1
