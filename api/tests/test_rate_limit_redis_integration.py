"""Redis-backed rate limit tiers (optional RATE_LIMIT_USE_REDIS)."""

from __future__ import annotations

from collections import defaultdict

import pytest

import app.middleware.rate_limit as rl_mod
from app.middleware.rate_limit import (
    _ONBOARDING_STRICT_LIMIT,
    RateLimitMiddleware,
)


@pytest.mark.asyncio
async def test_onboarding_redis_enforces_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    counts: dict[str, int] = defaultdict(int)

    class _FakeRedis:
        async def incr(self, key: str) -> int:
            counts[key] += 1
            return counts[key]

        async def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002
            return True

    fake = _FakeRedis()

    async def _get_rl() -> _FakeRedis:
        return fake

    monkeypatch.setattr("app.middleware.rate_limit.settings.rate_limit_use_redis", True)
    monkeypatch.setattr("app.middleware.rate_limit._get_rl_redis", _get_rl)

    async def mock_app(scope, receive, send) -> None:  # noqa: ARG001
        pass

    middleware = RateLimitMiddleware(mock_app)

    async def mock_receive() -> dict:
        return {"type": "http.request", "body": b""}

    captured: list[int] = []

    async def capture_send(message: dict) -> None:
        if message.get("type") == "http.response.start":
            captured.append(message.get("status"))

    scope = {
        "type": "http",
        "path": "/api/onboarding/club-claims",
        "query_string": b"",
        "headers": [],
        "server": ("localhost", 8000),
        "client": ("5.5.5.5", 12345),
    }

    for i in range(_ONBOARDING_STRICT_LIMIT):
        captured.clear()
        await middleware(scope, mock_receive, capture_send)
        assert 429 not in captured, f"unexpected 429 on request {i + 1}"

    captured.clear()
    await middleware(scope, mock_receive, capture_send)
    assert 429 in captured

    rl_mod._rl_redis = None
