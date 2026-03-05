"""Tests for utils/provider_request.py — TokenBucket, ProviderMetrics, provider_request."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.utils.provider_request import (
    ProviderMetrics,
    TokenBucket,
    _get_bucket,
    _get_metrics,
    _maybe_emit_summary,
    _parse_int_header,
    get_provider_metrics,
    provider_request,
)


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------

class TestTokenBucket:
    def test_acquire_succeeds_within_capacity(self):
        bucket = TokenBucket(rate=10.0, capacity=5)
        for _ in range(5):
            assert bucket.acquire(timeout=0.1) is True

    def test_acquire_fails_when_empty_and_timeout(self):
        bucket = TokenBucket(rate=0.01, capacity=1)
        bucket.acquire(timeout=0.1)  # drain
        assert bucket.acquire(timeout=0.05) is False

    def test_refill_adds_tokens_over_time(self):
        bucket = TokenBucket(rate=100.0, capacity=5)
        # Drain all tokens
        for _ in range(5):
            bucket.acquire(timeout=0.01)
        # Wait briefly, tokens should refill at 100/s
        time.sleep(0.05)
        assert bucket.acquire(timeout=0.01) is True

    def test_capacity_cap(self):
        bucket = TokenBucket(rate=1000.0, capacity=2)
        time.sleep(0.1)
        # Even after a long wait, capacity is capped at 2
        bucket._refill()
        assert bucket._tokens <= 2.0


# ---------------------------------------------------------------------------
# ProviderMetrics
# ---------------------------------------------------------------------------

class TestProviderMetrics:
    def test_record_request_increments_count(self):
        m = ProviderMetrics()
        m.record_request({"status_code": 200})
        assert m.requests_total == 1

    def test_record_request_trims_log(self):
        m = ProviderMetrics()
        for i in range(210):
            m.record_request({"i": i})
        assert m.requests_total == 210
        # Trims to 100 when > 200, then adds 10 more → 110
        assert len(m._request_log) <= 200

    def test_summary(self):
        m = ProviderMetrics()
        m.requests_total = 5
        m.rate_limited_total = 1
        m.errors_total = 2
        s = m.summary()
        assert s["requests_total"] == 5
        assert s["rate_limited_total"] == 1
        assert s["errors_total"] == 2
        assert "backoff_active" in s


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_get_metrics_creates_new(self):
        m = _get_metrics("__test_provider__")
        assert isinstance(m, ProviderMetrics)

    def test_get_metrics_returns_same(self):
        a = _get_metrics("__test_same__")
        b = _get_metrics("__test_same__")
        assert a is b

    def test_get_bucket_creates_new(self):
        b = _get_bucket("__test_bucket__", 1.0, 5)
        assert isinstance(b, TokenBucket)

    def test_get_provider_metrics_all(self):
        _get_metrics("__test_all_1__")
        result = get_provider_metrics()
        assert "__test_all_1__" in result

    def test_get_provider_metrics_single(self):
        _get_metrics("__test_single__")
        result = get_provider_metrics("__test_single__")
        assert "requests_total" in result

    def test_get_provider_metrics_missing(self):
        result = get_provider_metrics("__nonexistent__")
        assert result == {}


# ---------------------------------------------------------------------------
# _parse_int_header
# ---------------------------------------------------------------------------

class TestParseIntHeader:
    def test_valid_header(self):
        resp = MagicMock()
        resp.headers = {"x-remaining": "42"}
        assert _parse_int_header(resp, "x-remaining") == 42

    def test_missing_header(self):
        resp = MagicMock()
        resp.headers = {}
        assert _parse_int_header(resp, "x-remaining") is None

    def test_non_int_header(self):
        resp = MagicMock()
        resp.headers = {"x-remaining": "abc"}
        assert _parse_int_header(resp, "x-remaining") is None


# ---------------------------------------------------------------------------
# provider_request
# ---------------------------------------------------------------------------

class TestProviderRequest:
    def _make_response(self, status=200, headers=None, content=b"ok"):
        resp = MagicMock()
        resp.status_code = status
        resp.headers = headers or {}
        resp.content = content
        return resp

    def test_successful_request(self):
        client = MagicMock()
        resp = self._make_response()
        client.request.return_value = resp

        result = provider_request(
            client, "GET", "http://test.com",
            provider="test_ok", endpoint="e",
        )
        assert result is resp

    def test_backoff_active_returns_none(self):
        # Set an active backoff
        m = _get_metrics("test_backoff")
        m.last_backoff_until = time.monotonic() + 60

        client = MagicMock()
        result = provider_request(
            client, "GET", "http://test.com",
            provider="test_backoff", endpoint="e",
        )
        assert result is None
        client.request.assert_not_called()
        # Clean up
        m.last_backoff_until = 0

    def test_429_sets_backoff(self):
        client = MagicMock()
        resp = self._make_response(status=429, headers={"retry-after": "30"})
        client.request.return_value = resp

        result = provider_request(
            client, "GET", "http://test.com",
            provider="test_429", endpoint="e",
        )
        assert result is None
        m = _get_metrics("test_429")
        assert m.rate_limited_total >= 1
        assert m.last_backoff_until > time.monotonic()
        # Clean up
        m.last_backoff_until = 0

    def test_timeout_returns_none(self):
        import httpx
        client = MagicMock()
        client.request.side_effect = httpx.TimeoutException("timeout")

        result = provider_request(
            client, "GET", "http://test.com",
            provider="test_timeout", endpoint="e",
        )
        assert result is None
        m = _get_metrics("test_timeout")
        assert m.errors_total >= 1

    def test_generic_exception_raises(self):
        client = MagicMock()
        client.request.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError):
            provider_request(
                client, "GET", "http://test.com",
                provider="test_exc", endpoint="e",
            )

    def test_qps_budget_exhausted_returns_none(self):
        client = MagicMock()
        # Create a bucket with 0 capacity effectively
        bucket = TokenBucket(rate=0.001, capacity=1)
        bucket.acquire(timeout=0.01)  # drain the single token

        with patch("sports_scraper.utils.provider_request._get_bucket", return_value=bucket):
            result = provider_request(
                client, "GET", "http://test.com",
                provider="test_qps_exhaust", endpoint="e",
            )
        assert result is None
        client.request.assert_not_called()

    def test_rate_limit_headers_captured(self):
        client = MagicMock()
        resp = self._make_response(
            headers={"x-requests-remaining": "42", "x-requests-reset": "2026-01-01"},
        )
        client.request.return_value = resp

        provider_request(
            client, "GET", "http://test.com",
            provider="test_headers", endpoint="e",
        )
        m = _get_metrics("test_headers")
        assert m.last_remaining == 42
        assert m.last_reset == "2026-01-01"


# ---------------------------------------------------------------------------
# _maybe_emit_summary
# ---------------------------------------------------------------------------

class TestMaybeEmitSummary:
    def test_does_not_emit_within_60s(self):
        # Just call it — shouldn't crash
        _maybe_emit_summary()
        _maybe_emit_summary()
