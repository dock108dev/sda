"""Tests for services/live_odds_redis.py — API-side Redis reader."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import app.services.live_odds_redis as redis_mod
from app.services.live_odds_redis import (
    read_all_live_snapshots_for_game,
    read_live_history,
    read_live_snapshot,
)


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """Reset the circuit breaker before each test."""
    redis_mod._redis_error_until = 0.0
    yield
    redis_mod._redis_error_until = 0.0


class TestReadLiveSnapshot:
    @patch("app.services.live_odds_redis._get_redis")
    def test_reads_existing(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        data = {"provider": "dk", "selections": []}
        mock_r.get.return_value = json.dumps(data)
        mock_r.ttl.return_value = 3600

        result, error = read_live_snapshot("NBA", 42, "spread")
        assert result is not None
        assert error is None
        assert result["provider"] == "dk"
        assert result["ttl_seconds_remaining"] == 3600

    @patch("app.services.live_odds_redis._get_redis")
    def test_returns_none_on_miss(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        mock_r.get.return_value = None

        result, error = read_live_snapshot("NBA", 42, "spread")
        assert result is None
        assert error is None

    @patch("app.services.live_odds_redis._get_redis")
    def test_returns_none_on_error(self, mock_get_redis):
        mock_get_redis.side_effect = Exception("connection refused")
        result, error = read_live_snapshot("NBA", 42, "spread")
        assert result is None
        assert error is not None
        assert "redis_error" in error


class TestReadLiveHistory:
    @patch("app.services.live_odds_redis._get_redis")
    def test_reads_history(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        mock_r.lrange.return_value = [json.dumps({"t": 1})]

        result, error = read_live_history(42, "spread", count=10)
        assert len(result) == 1
        assert error is None
        mock_r.lrange.assert_called_with("live:odds:history:42:spread", 0, 9)

    @patch("app.services.live_odds_redis._get_redis")
    def test_returns_empty_on_error(self, mock_get_redis):
        mock_get_redis.side_effect = Exception("err")
        result, error = read_live_history(42, "spread")
        assert result == []
        assert error is not None


class TestReadAllLiveSnapshots:
    @patch("app.services.live_odds_redis._get_redis")
    def test_reads_all_snapshots(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        mock_r.scan_iter.return_value = iter(["live:odds:NBA:42:spread"])
        data = {"provider": "fd"}
        mock_r.get.return_value = json.dumps(data)
        mock_r.ttl.return_value = 1800

        result, error = read_all_live_snapshots_for_game("NBA", 42)
        assert error is None
        assert "spread" in result
        assert result["spread"]["provider"] == "fd"

    @patch("app.services.live_odds_redis._get_redis")
    def test_returns_empty_on_error(self, mock_get_redis):
        mock_get_redis.side_effect = Exception("err")
        result, error = read_all_live_snapshots_for_game("NBA", 42)
        assert result == {}
        assert error is not None

    @patch("app.services.live_odds_redis._get_redis")
    def test_skips_null_values(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        mock_r.scan_iter.return_value = iter(["live:odds:NBA:42:total"])
        mock_r.get.return_value = None

        result, error = read_all_live_snapshots_for_game("NBA", 42)
        assert result == {}
        assert error is None
