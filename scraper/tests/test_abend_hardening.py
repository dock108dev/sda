"""Regression tests for abend-audit hardening changes."""

from __future__ import annotations

import types
from unittest.mock import MagicMock


def test_task_hold_fails_closed_when_redis_unreadable(monkeypatch):
    from sports_scraper import celery_app

    def raise_connection_error(*_, **__):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(celery_app._redis, "from_url", raise_connection_error)

    assert celery_app._is_held() is True


def test_scraper_logging_redacts_flat_sensitive_fields():
    from sports_scraper.logging import _redact_sensitive_fields

    event = {
        "message": "provider_request",
        "api_key": "secret-key",
        "authorization": "Bearer token",
        "safe": "value",
    }

    result = _redact_sensitive_fields(MagicMock(), "info", event)

    assert result["api_key"] == "[REDACTED]"
    assert result["authorization"] == "[REDACTED]"
    assert result["safe"] == "value"


def test_redis_lock_status_distinguishes_contention_from_backend_error(monkeypatch):
    from sports_scraper.utils import redis_lock

    class ContendedRedis:
        def set(self, *_args, **_kwargs):
            return False

    class BrokenRedis:
        def set(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

    fake_redis = types.SimpleNamespace(
        from_url=lambda *_args, **_kwargs: ContendedRedis()
    )
    monkeypatch.setitem(__import__("sys").modules, "redis", fake_redis)
    token, reason = redis_lock.acquire_redis_lock_status("lock:test")
    assert token is None
    assert reason == "contended"

    fake_redis.from_url = lambda *_args, **_kwargs: BrokenRedis()
    token, reason = redis_lock.acquire_redis_lock_status("lock:test")
    assert token is None
    assert reason == "redis_error"
