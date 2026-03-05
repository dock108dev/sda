"""Tests for the live odds infrastructure: Redis store, closing lines model, FairBet live endpoint."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.db.odds import ClosingLine


# ---------------------------------------------------------------------------
# ClosingLine model
# ---------------------------------------------------------------------------


class TestClosingLineModel:
    def test_table_name(self):
        assert ClosingLine.__tablename__ == "closing_lines"

    def test_columns_exist(self):
        cols = {c.name for c in ClosingLine.__table__.columns}
        expected = {
            "id", "game_id", "league", "market_key", "selection",
            "line_value", "price_american", "provider", "captured_at",
            "source_type", "created_at",
        }
        assert expected.issubset(cols)

    def test_unique_constraint(self):
        indexes = {idx.name for idx in ClosingLine.__table__.indexes}
        assert "uq_closing_lines_identity" in indexes


# ---------------------------------------------------------------------------
# Live odds Redis store (API reader side)
# ---------------------------------------------------------------------------


class TestLiveOddsRedisReader:
    @patch("app.services.live_odds_redis._get_redis")
    def test_read_live_snapshot_returns_data(self, mock_redis):
        from app.services.live_odds_redis import read_live_snapshot

        snapshot = {
            "last_updated_at": time.time(),
            "provider": "TestBook",
            "selections": [{"selection": "home", "line": -3.5, "price": -110}],
        }
        r = MagicMock()
        r.get.return_value = json.dumps(snapshot)
        r.ttl.return_value = 12345
        mock_redis.return_value = r

        result = read_live_snapshot("NBA", 123, "spread")

        assert result is not None
        assert result["provider"] == "TestBook"
        assert result["ttl_seconds_remaining"] == 12345
        assert len(result["selections"]) == 1

    @patch("app.services.live_odds_redis._get_redis")
    def test_read_live_snapshot_returns_none_when_missing(self, mock_redis):
        from app.services.live_odds_redis import read_live_snapshot

        r = MagicMock()
        r.get.return_value = None
        mock_redis.return_value = r

        result = read_live_snapshot("NBA", 999, "spread")
        assert result is None

    @patch("app.services.live_odds_redis._get_redis")
    def test_read_live_snapshot_handles_redis_error(self, mock_redis):
        from app.services.live_odds_redis import read_live_snapshot

        mock_redis.side_effect = Exception("connection refused")
        result = read_live_snapshot("NBA", 123, "spread")
        assert result is None

    @patch("app.services.live_odds_redis._get_redis")
    def test_read_live_history(self, mock_redis):
        from app.services.live_odds_redis import read_live_history

        entries = [
            json.dumps({"t": int(time.time()), "selections": [{"s": "home", "p": -110}]}),
            json.dumps({"t": int(time.time()) - 10, "selections": [{"s": "home", "p": -105}]}),
        ]
        r = MagicMock()
        r.lrange.return_value = entries
        mock_redis.return_value = r

        result = read_live_history(123, "spread", count=10)
        assert len(result) == 2
        assert result[0]["selections"][0]["p"] == -110

    @patch("app.services.live_odds_redis._get_redis")
    def test_read_all_live_snapshots_for_game(self, mock_redis):
        from app.services.live_odds_redis import read_all_live_snapshots_for_game

        snapshot_data = json.dumps({
            "last_updated_at": time.time(),
            "provider": "TestBook",
            "selections": [],
        })

        r = MagicMock()
        r.scan_iter.return_value = ["live:odds:NBA:123:spread", "live:odds:NBA:123:total"]
        r.get.return_value = snapshot_data
        r.ttl.return_value = 5000
        mock_redis.return_value = r

        result = read_all_live_snapshots_for_game("NBA", 123)
        assert len(result) == 2
        assert "spread" in result or "total" in result


# ---------------------------------------------------------------------------
# FairBet Live endpoint structure
# ---------------------------------------------------------------------------


class TestFairbetLiveEndpoint:
    def test_response_models_importable(self):
        from app.routers.fairbet.live import (
            ClosingLineResponse,
            FairbetLiveResponse,
            LiveSnapshotResponse,
        )
        # Verify the models can be instantiated
        closing = ClosingLineResponse(
            provider="TestBook",
            market_key="spread",
            selection="home",
            line_value=-3.5,
            price_american=-110,
            captured_at="2026-03-05T00:00:00",
            source_type="closing",
        )
        assert closing.provider == "TestBook"

        live = LiveSnapshotResponse(
            last_updated_at=time.time(),
            provider="TestBook",
            selections=[{"selection": "home", "price": -110}],
            ttl_seconds_remaining=12345,
        )
        assert live.provider == "TestBook"

    def test_router_registered(self):
        from app.routers.fairbet import router
        paths = [route.path for route in router.routes]
        assert "/api/fairbet/live" in paths


# ---------------------------------------------------------------------------
# Task registry includes new tasks
# ---------------------------------------------------------------------------


class TestTaskRegistryUpdated:
    def test_new_tasks_in_registry(self):
        from app.routers.admin.task_control import TASK_REGISTRY

        assert "live_orchestrator_tick" in TASK_REGISTRY
        assert "poll_live_odds_mainline" in TASK_REGISTRY
        assert "poll_live_odds_props" in TASK_REGISTRY

    def test_new_tasks_on_correct_queue(self):
        from app.routers.admin.task_control import TASK_REGISTRY

        assert TASK_REGISTRY["live_orchestrator_tick"].queue == "sports-scraper"
        assert TASK_REGISTRY["poll_live_odds_mainline"].queue == "sports-scraper"
        assert TASK_REGISTRY["poll_live_odds_props"].queue == "sports-scraper"
