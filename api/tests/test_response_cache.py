"""Unit tests for the generic Redis-backed response cache helper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import response_cache as rc


def test_build_cache_key_is_stable_under_param_reordering():
    a = rc.build_cache_key("games_list", {"limit": 50, "offset": 0, "league": ["NBA"]})
    b = rc.build_cache_key("games_list", {"league": ["NBA"], "offset": 0, "limit": 50})
    assert a == b


def test_build_cache_key_distinguishes_different_params():
    a = rc.build_cache_key("games_list", {"limit": 50})
    b = rc.build_cache_key("games_list", {"limit": 51})
    assert a != b


def test_build_cache_key_drops_none_values():
    a = rc.build_cache_key("games_list", {"limit": 50, "team": None})
    b = rc.build_cache_key("games_list", {"limit": 50})
    assert a == b


def test_build_cache_key_distinguishes_prefixes():
    a = rc.build_cache_key("games_list", {"limit": 50})
    b = rc.build_cache_key("fairbet_live", {"limit": 50})
    assert a != b


def test_should_bypass_cache_with_authorization_header():
    request = MagicMock()
    request.headers = {"authorization": "Bearer xyz"}
    assert rc.should_bypass_cache(request) is True


def test_should_bypass_cache_with_cookie_header():
    request = MagicMock()
    request.headers = {"cookie": "session=abc"}
    assert rc.should_bypass_cache(request) is True


def test_should_bypass_cache_anonymous():
    request = MagicMock()
    request.headers = {}
    assert rc.should_bypass_cache(request) is False


def test_should_bypass_cache_no_request():
    assert rc.should_bypass_cache(None) is False


class TestRedisRoundTrip:
    """Round-trip get/set with a fake redis client."""

    @pytest.fixture(autouse=True)
    def _reset_circuit(self):
        # Make sure no prior failure left the circuit open.
        rc._reset_circuit()
        yield
        rc._reset_circuit()

    def test_get_returns_none_on_miss(self, monkeypatch):
        fake = MagicMock()
        fake.get.return_value = None
        monkeypatch.setattr(rc, "_get_redis_client", lambda: fake)
        assert rc.get_cached("missing") is None

    def test_set_then_get_returns_payload(self, monkeypatch):
        store: dict[str, str] = {}

        class FakeRedis:
            def get(self, key):
                return store.get(key)

            def setex(self, key, ttl, value):
                store[key] = value

        fake = FakeRedis()
        monkeypatch.setattr(rc, "_get_redis_client", lambda: fake)

        payload = {"games": [{"id": 1}], "total": 1}
        rc.set_cached("test:key", payload, ttl_seconds=15)
        assert rc.get_cached("test:key") == payload

    def test_redis_error_trips_circuit_and_returns_none(self, monkeypatch):
        fake = MagicMock()
        fake.get.side_effect = RuntimeError("redis down")
        monkeypatch.setattr(rc, "_get_redis_client", lambda: fake)

        # First call surfaces the error gracefully.
        assert rc.get_cached("anything") is None
        assert rc._circuit_open() is True

        # Subsequent calls short-circuit (no redis call attempted).
        fake.get.reset_mock()
        assert rc.get_cached("anything") is None
        fake.get.assert_not_called()
