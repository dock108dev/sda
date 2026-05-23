"""Regression tests for abend-audit hardening changes."""

from __future__ import annotations

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
