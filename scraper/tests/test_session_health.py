"""Tests for Playwright session health probe."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

# ---------------------------------------------------------------------------
# Load session_health directly from its file path so we bypass the
# sports_scraper.social __init__.py which pulls in heavy DB dependencies
# not present in the test venv (structlog, sqlalchemy, etc.).
# ---------------------------------------------------------------------------
_SH_PATH = SCRAPER_ROOT / "sports_scraper" / "social" / "session_health.py"

# We need sports_scraper.logging to be importable. Stub it.
if "sports_scraper.logging" not in sys.modules:
    _log_stub = MagicMock()
    _log_stub.logger = MagicMock()
    sys.modules["sports_scraper.logging"] = _log_stub

# Also stub structlog since logging.py imports it
if "structlog" not in sys.modules:
    sys.modules["structlog"] = MagicMock()

spec = importlib.util.spec_from_file_location(
    "sports_scraper.social.session_health", _SH_PATH
)
sh_mod = importlib.util.module_from_spec(spec)
sys.modules["sports_scraper.social.session_health"] = sh_mod
spec.loader.exec_module(sh_mod)

SessionHealthResult = sh_mod.SessionHealthResult
HEALTH_KEY = sh_mod.HEALTH_KEY
CIRCUIT_OPEN_KEY = sh_mod.CIRCUIT_OPEN_KEY
CONSECUTIVE_FAILURES_KEY = sh_mod.CONSECUTIVE_FAILURES_KEY
CIRCUIT_BREAKER_THRESHOLD = sh_mod.CIRCUIT_BREAKER_THRESHOLD
record_health = sh_mod.record_health
get_cached_health = sh_mod.get_cached_health
get_consecutive_failures = sh_mod.get_consecutive_failures
is_circuit_open = sh_mod.is_circuit_open
probe_session_health = sh_mod.probe_session_health


# ============================================================================
# SessionHealthResult
# ============================================================================


class TestSessionHealthResult:
    def test_valid(self):
        r = SessionHealthResult(
            is_valid=True,
            checked_at="2026-04-18T12:00:00+00:00",
            auth_token_present=True,
            ct0_present=True,
        )
        assert r.is_valid is True
        assert r.failure_reason is None

    def test_invalid_with_reason(self):
        r = SessionHealthResult(
            is_valid=False,
            checked_at="2026-04-18T12:00:00+00:00",
            failure_reason="redirected to /login — session expired",
        )
        assert r.is_valid is False
        assert "session expired" in r.failure_reason


# ============================================================================
# record_health / get_cached_health / is_circuit_open
# ============================================================================


def _make_redis():
    store: dict = {}
    mock = MagicMock()
    mock.set.side_effect = lambda key, val, ex=None: store.update({key: val})
    mock.get.side_effect = lambda key: store.get(key)
    mock.delete.side_effect = lambda key: store.pop(key, None)
    mock.expire.side_effect = lambda key, ttl: None  # no-op in tests

    def _incr(key):
        current = int(store.get(key, 0))
        store[key] = str(current + 1)
        return current + 1

    mock.incr.side_effect = _incr
    return mock, store


def _invalid_result(reason="redirected to /login"):
    return SessionHealthResult(
        is_valid=False,
        checked_at="2026-04-18T12:00:00+00:00",
        failure_reason=reason,
    )


def _valid_result():
    return SessionHealthResult(
        is_valid=True,
        checked_at="2026-04-18T12:00:00+00:00",
        auth_token_present=True,
        ct0_present=True,
    )


class TestRedisHelpers:
    def test_record_health_valid_clears_circuit(self):
        r, store = _make_redis()
        store[CIRCUIT_OPEN_KEY] = "1"
        store[CONSECUTIVE_FAILURES_KEY] = "3"

        returned = record_health(r, _valid_result())

        assert json.loads(store[HEALTH_KEY])["is_valid"] is True
        assert CIRCUIT_OPEN_KEY not in store
        assert CONSECUTIVE_FAILURES_KEY not in store
        assert returned is False

    def test_record_health_single_failure_does_not_trip_circuit(self):
        r, store = _make_redis()

        returned = record_health(r, _invalid_result())

        assert json.loads(store[HEALTH_KEY])["is_valid"] is False
        assert CIRCUIT_OPEN_KEY not in store
        assert int(store[CONSECUTIVE_FAILURES_KEY]) == 1
        assert returned is False

    def test_record_health_two_failures_do_not_trip_circuit(self):
        r, store = _make_redis()

        record_health(r, _invalid_result())
        returned = record_health(r, _invalid_result())

        assert CIRCUIT_OPEN_KEY not in store
        assert int(store[CONSECUTIVE_FAILURES_KEY]) == 2
        assert returned is False

    def test_record_health_third_failure_trips_circuit(self):
        r, store = _make_redis()

        record_health(r, _invalid_result())
        record_health(r, _invalid_result())
        returned = record_health(r, _invalid_result())

        assert store.get(CIRCUIT_OPEN_KEY) == "1"
        assert int(store[CONSECUTIVE_FAILURES_KEY]) == CIRCUIT_BREAKER_THRESHOLD
        assert returned is True

    def test_record_health_fourth_failure_does_not_re_trip(self):
        """Circuit is already open — newly_tripped should be False after the 3rd."""
        r, store = _make_redis()

        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            record_health(r, _invalid_result())

        returned = record_health(r, _invalid_result())

        assert store.get(CIRCUIT_OPEN_KEY) == "1"
        assert returned is False  # only True on exactly the 3rd

    def test_record_health_valid_after_failures_resets_counter(self):
        r, store = _make_redis()

        record_health(r, _invalid_result())
        record_health(r, _invalid_result())
        record_health(r, _valid_result())

        assert CIRCUIT_OPEN_KEY not in store
        assert CONSECUTIVE_FAILURES_KEY not in store

    def test_get_consecutive_failures_returns_zero_when_absent(self):
        r, _ = _make_redis()
        assert get_consecutive_failures(r) == 0

    def test_get_consecutive_failures_returns_count(self):
        r, store = _make_redis()
        store[CONSECUTIVE_FAILURES_KEY] = "2"
        assert get_consecutive_failures(r) == 2

    def test_get_consecutive_failures_handles_corrupted_value(self):
        r, store = _make_redis()
        store[CONSECUTIVE_FAILURES_KEY] = "not-a-number"
        assert get_consecutive_failures(r) == 0

    def test_get_cached_health_returns_none_when_missing(self):
        r, _ = _make_redis()
        assert get_cached_health(r) is None

    def test_get_cached_health_returns_dict(self):
        r, store = _make_redis()
        store[HEALTH_KEY] = json.dumps({"is_valid": True, "checked_at": "2026-04-18T12:00:00+00:00"})
        data = get_cached_health(r)
        assert data is not None
        assert data["is_valid"] is True

    def test_get_cached_health_handles_malformed_json(self):
        r, store = _make_redis()
        store[HEALTH_KEY] = "not-json"
        assert get_cached_health(r) is None

    def test_is_circuit_open_true(self):
        r, store = _make_redis()
        store[CIRCUIT_OPEN_KEY] = "1"
        assert is_circuit_open(r) is True

    def test_is_circuit_open_false_when_absent(self):
        r, _ = _make_redis()
        assert is_circuit_open(r) is False


# ============================================================================
# probe_session_health — _probe_impl mocked via monkeypatch on the module
# ============================================================================


class TestProbeSessionHealth:
    def test_no_auth_tokens_returns_invalid(self, monkeypatch):
        monkeypatch.delenv("X_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("X_CT0", raising=False)
        result = probe_session_health(auth_token=None, ct0=None)
        assert result.is_valid is False
        assert "not configured" in result.failure_reason

    def test_valid_session_returns_is_valid_true(self, monkeypatch):
        monkeypatch.setattr(
            sh_mod,
            "_probe_impl",
            lambda tok, ct0: SessionHealthResult(
                is_valid=True,
                checked_at="2026-04-18T12:00:00+00:00",
                auth_token_present=True,
                ct0_present=True,
            ),
        )
        result = probe_session_health(auth_token="tok", ct0="ct0val")
        assert result.is_valid is True
        assert result.failure_reason is None

    def test_login_redirect_returns_invalid(self, monkeypatch):
        monkeypatch.setattr(
            sh_mod,
            "_probe_impl",
            lambda tok, ct0: SessionHealthResult(
                is_valid=False,
                checked_at="2026-04-18T12:00:00+00:00",
                failure_reason="redirected to /login — session expired",
            ),
        )
        result = probe_session_health(auth_token="tok", ct0="ct0val")
        assert result.is_valid is False
        assert "session expired" in result.failure_reason

    def test_login_button_present_returns_invalid(self, monkeypatch):
        monkeypatch.setattr(
            sh_mod,
            "_probe_impl",
            lambda tok, ct0: SessionHealthResult(
                is_valid=False,
                checked_at="2026-04-18T12:00:00+00:00",
                failure_reason="login button present — not authenticated",
            ),
        )
        result = probe_session_health(auth_token="tok", ct0="ct0val")
        assert result.is_valid is False

    def test_thread_timeout_returns_invalid(self, monkeypatch):
        def _slow(*_):
            time.sleep(1)  # longer than the 0.1s probe timeout
            return SessionHealthResult(is_valid=True, checked_at="2026-04-18T12:00:00+00:00")

        monkeypatch.setattr(sh_mod, "_probe_impl", _slow)
        monkeypatch.setattr(sh_mod, "_PROBE_THREAD_TIMEOUT_SECONDS", 0.1)
        result = probe_session_health(auth_token="tok", ct0="ct0val")
        assert result.is_valid is False
        assert "timed out" in result.failure_reason
