"""Tests for split API key auth: consumer vs admin scoping and rate limits.

Covers ISSUE-018 acceptance criteria:
- Consumer key rejected 403 on /api/admin/ routes.
- Admin key rejected 403 on /api/v1/ routes.
- Rate limits enforced independently per key class.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.dependencies.auth import verify_api_key
from app.dependencies.consumer_auth import verify_consumer_api_key
from app.middleware.rate_limit import RateLimitMiddleware


_ADMIN_KEY = "admin-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_CONSUMER_KEY = "consumer-key-bbbbbbbbbbbbbbbbbbbbbbbbb"


def _make_request(path: str = "/api/admin/sports/games", client_ip: str = "1.2.3.4") -> MagicMock:
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = client_ip
    req.url = MagicMock()
    req.url.path = path
    req.state = MagicMock()
    return req


def _make_scope(path: str, client_ip: str = "1.2.3.4") -> dict:
    return {
        "type": "http",
        "path": path,
        "query_string": b"",
        "headers": [],
        "server": ("localhost", 8000),
        "client": (client_ip, 12345),
    }


def _settings_both_keys(**overrides):
    s = MagicMock()
    s.api_key = _ADMIN_KEY
    s.consumer_api_key = _CONSUMER_KEY
    s.environment = "development"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# verify_api_key (admin routes): consumer key must be rejected 403
# ---------------------------------------------------------------------------


class TestVerifyApiKeyScopeEnforcement:
    def test_consumer_key_rejected_on_admin_route(self):
        req = _make_request("/api/admin/sports/games")
        with patch("app.dependencies.auth.settings", _settings_both_keys()):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_api_key(request=req, api_key=_CONSUMER_KEY))
        assert exc_info.value.status_code == 403
        assert "consumer" in exc_info.value.detail.lower()

    def test_admin_key_accepted_on_admin_route(self):
        req = _make_request("/api/admin/sports/games")
        with patch("app.dependencies.auth.settings", _settings_both_keys()):
            result = asyncio.run(verify_api_key(request=req, api_key=_ADMIN_KEY))
        assert result == _ADMIN_KEY

    def test_single_key_setup_not_rejected(self):
        """When CONSUMER_API_KEY is unset, the single key works on admin routes."""
        req = _make_request("/api/admin/sports/games")
        s = MagicMock()
        s.api_key = _ADMIN_KEY
        s.consumer_api_key = None
        s.environment = "development"
        with patch("app.dependencies.auth.settings", s):
            result = asyncio.run(verify_api_key(request=req, api_key=_ADMIN_KEY))
        assert result == _ADMIN_KEY

    def test_same_key_value_not_rejected(self):
        """If both keys share the same value, allow through (single-key fallback)."""
        req = _make_request("/api/admin/sports/games")
        s = MagicMock()
        s.api_key = _ADMIN_KEY
        s.consumer_api_key = _ADMIN_KEY
        s.environment = "development"
        with patch("app.dependencies.auth.settings", s):
            result = asyncio.run(verify_api_key(request=req, api_key=_ADMIN_KEY))
        assert result == _ADMIN_KEY

    def test_wrong_key_still_401(self):
        req = _make_request("/api/admin/sports/games")
        with patch("app.dependencies.auth.settings", _settings_both_keys()):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_api_key(request=req, api_key="totally-wrong-key"))
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# verify_consumer_api_key (v1 routes): admin key must be rejected 403
# ---------------------------------------------------------------------------


class TestVerifyConsumerApiKeyScopeEnforcement:
    def test_admin_key_rejected_on_consumer_route(self):
        req = _make_request("/api/v1/games/42/flow")
        with patch("app.dependencies.consumer_auth.settings", _settings_both_keys()):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(request=req, api_key=_ADMIN_KEY))
        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail.lower()

    def test_consumer_key_accepted_on_consumer_route(self):
        req = _make_request("/api/v1/games/42/flow")
        with patch("app.dependencies.consumer_auth.settings", _settings_both_keys()):
            result = asyncio.run(verify_consumer_api_key(request=req, api_key=_CONSUMER_KEY))
        assert result == _CONSUMER_KEY

    def test_single_key_setup_not_rejected(self):
        """When only API_KEY is set, it works for consumer routes."""
        req = _make_request("/api/v1/games/42/flow")
        s = MagicMock()
        s.api_key = _ADMIN_KEY
        s.consumer_api_key = None
        s.environment = "development"
        with patch("app.dependencies.consumer_auth.settings", s):
            result = asyncio.run(verify_consumer_api_key(request=req, api_key=_ADMIN_KEY))
        assert result == _ADMIN_KEY

    def test_same_key_value_not_rejected(self):
        """If both keys share the same value, allow through on consumer route."""
        req = _make_request("/api/v1/games/42/flow")
        s = MagicMock()
        s.api_key = _ADMIN_KEY
        s.consumer_api_key = _ADMIN_KEY
        s.environment = "development"
        with patch("app.dependencies.consumer_auth.settings", s):
            result = asyncio.run(verify_consumer_api_key(request=req, api_key=_ADMIN_KEY))
        assert result == _ADMIN_KEY

    def test_missing_key_raises_401(self):
        req = _make_request("/api/v1/games/42/flow")
        with patch("app.dependencies.consumer_auth.settings", _settings_both_keys()):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(request=req, api_key=None))
        assert exc_info.value.status_code == 401

    def test_wrong_key_raises_401(self):
        req = _make_request("/api/v1/games/42/flow")
        with patch("app.dependencies.consumer_auth.settings", _settings_both_keys()):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(request=req, api_key="wrong-key"))
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# RateLimitMiddleware — independent admin rate limit tier
# ---------------------------------------------------------------------------


def _run_middleware(middleware, scope, limit_requests, limit_window):
    """Run middleware under a mocked settings and collect HTTP response status codes."""
    captured_status = []

    async def mock_receive():
        return {"type": "http.request", "body": b""}

    async def capture_send(message):
        if message.get("type") == "http.response.start":
            captured_status.append(message.get("status"))

    async def run():
        with patch("app.middleware.rate_limit.settings") as s:
            s.admin_rate_limit_requests = limit_requests
            s.admin_rate_limit_window_seconds = limit_window
            s.rate_limit_requests = 120
            s.rate_limit_window_seconds = 60
            s.fairbet_redis_limiter_enabled = False
            await middleware(scope, mock_receive, capture_send)

    asyncio.run(run())
    return captured_status


class TestAdminRateLimitTier:
    """Admin routes use a tighter limit, independent of consumer limits."""

    def test_admin_route_blocked_after_limit(self):
        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)
        admin_limit = 3

        async def run():
            captured = []

            async def mock_receive():
                return {"type": "http.request", "body": b""}

            async def capture_send(message):
                if message.get("type") == "http.response.start":
                    captured.append(message.get("status"))

            with patch("app.middleware.rate_limit.settings") as s:
                s.admin_rate_limit_requests = admin_limit
                s.admin_rate_limit_window_seconds = 60
                s.rate_limit_requests = 120
                s.rate_limit_window_seconds = 60
                s.fairbet_redis_limiter_enabled = False

                for _ in range(admin_limit):
                    captured.clear()
                    await middleware(_make_scope("/api/admin/sports/games"), mock_receive, capture_send)
                    assert 429 not in captured

                captured.clear()
                await middleware(_make_scope("/api/admin/sports/games"), mock_receive, capture_send)
                assert 429 in captured

        asyncio.run(run())

    def test_consumer_route_not_affected_by_admin_limit(self):
        """Exhausting the admin limit does not block consumer /api/v1/ routes."""
        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)
        admin_limit = 2

        async def run():
            captured = []

            async def mock_receive():
                return {"type": "http.request", "body": b""}

            async def capture_send(message):
                if message.get("type") == "http.response.start":
                    captured.append(message.get("status"))

            with patch("app.middleware.rate_limit.settings") as s:
                s.admin_rate_limit_requests = admin_limit
                s.admin_rate_limit_window_seconds = 60
                s.rate_limit_requests = 120
                s.rate_limit_window_seconds = 60
                s.fairbet_redis_limiter_enabled = False

                # Exhaust admin limit from IP 1.2.3.4
                for _ in range(admin_limit + 1):
                    await middleware(
                        _make_scope("/api/admin/sports/games", "1.2.3.4"), mock_receive, capture_send
                    )

                # Same IP can still hit consumer route
                captured.clear()
                await middleware(
                    _make_scope("/api/v1/games/1/flow", "1.2.3.4"), mock_receive, capture_send
                )
                assert 429 not in captured

        asyncio.run(run())

    def test_admin_route_has_retry_after_header(self):
        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)

        async def run():
            headers: dict[str, str] = {}

            async def mock_receive():
                return {"type": "http.request", "body": b""}

            async def capture_send(message):
                if message.get("type") == "http.response.start":
                    for k, v in message.get("headers", []):
                        key = k.decode() if isinstance(k, bytes) else k
                        headers[key] = v.decode() if isinstance(v, bytes) else v

            with patch("app.middleware.rate_limit.settings") as s:
                s.admin_rate_limit_requests = 1
                s.admin_rate_limit_window_seconds = 60
                s.rate_limit_requests = 120
                s.rate_limit_window_seconds = 60
                s.fairbet_redis_limiter_enabled = False

                for _ in range(2):
                    headers.clear()
                    await middleware(
                        _make_scope("/api/admin/sports/games"), mock_receive, capture_send
                    )

            assert "retry-after" in headers

        asyncio.run(run())

    def test_admin_limit_per_ip(self):
        """Admin rate limits are per-IP, not global."""
        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)
        admin_limit = 2

        async def run():
            captured = []

            async def mock_receive():
                return {"type": "http.request", "body": b""}

            async def capture_send(message):
                if message.get("type") == "http.response.start":
                    captured.append(message.get("status"))

            with patch("app.middleware.rate_limit.settings") as s:
                s.admin_rate_limit_requests = admin_limit
                s.admin_rate_limit_window_seconds = 60
                s.rate_limit_requests = 120
                s.rate_limit_window_seconds = 60
                s.fairbet_redis_limiter_enabled = False

                # Exhaust limit for IP A
                for _ in range(admin_limit + 1):
                    await middleware(
                        _make_scope("/api/admin/sports/games", "10.0.0.1"), mock_receive, capture_send
                    )

                # IP B is unaffected
                captured.clear()
                await middleware(
                    _make_scope("/api/admin/sports/games", "10.0.0.2"), mock_receive, capture_send
                )
                assert 429 not in captured

        asyncio.run(run())

    def test_exempt_endpoints_still_exempt(self):
        """SSE endpoint is still exempt from all rate limits."""
        async def mock_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(mock_app)

        async def run():
            captured = []

            async def mock_receive():
                return {"type": "http.request", "body": b""}

            async def capture_send(message):
                if message.get("type") == "http.response.start":
                    captured.append(message.get("status"))

            with patch("app.middleware.rate_limit.settings") as s:
                s.admin_rate_limit_requests = 1
                s.admin_rate_limit_window_seconds = 60
                s.rate_limit_requests = 120
                s.rate_limit_window_seconds = 60
                s.fairbet_redis_limiter_enabled = False

                for _ in range(10):
                    captured.clear()
                    await middleware(_make_scope("/v1/sse"), mock_receive, capture_send)
                    assert 429 not in captured

        asyncio.run(run())
