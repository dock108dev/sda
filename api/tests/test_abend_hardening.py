"""Regression tests for abend-audit hardening changes."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_playwright_health_fails_conservative_when_redis_unreadable(monkeypatch):
    from app.routers.admin import circuit_breakers

    def raise_connection_error():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(circuit_breakers, "_get_redis", raise_connection_error)

    response = await circuit_breakers.get_playwright_health()

    assert response.circuit_open is True
    assert response.consecutive_failures == circuit_breakers._CIRCUIT_BREAKER_THRESHOLD
    assert response.last_check is not None
    assert response.last_check["status"] == "unknown"
