"""Tests for live_odds/redis_store.py and live_odds/closing_lines.py."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.live_odds.redis_store import (
    LIVE_SNAPSHOT_TTL_S,
    _history_key,
    _snapshot_key,
    get_all_live_keys_for_game,
    read_live_history,
    read_live_snapshot,
    write_live_snapshot,
)


# ===========================================================================
# redis_store key helpers
# ===========================================================================

class TestKeyHelpers:
    def test_snapshot_key(self):
        assert _snapshot_key("NBA", 123, "spread") == "live:odds:NBA:123:spread"

    def test_history_key(self):
        assert _history_key(123, "total") == "live:odds:history:123:total"


# ===========================================================================
# write_live_snapshot
# ===========================================================================

class TestWriteLiveSnapshot:
    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_writes_snapshot_and_history(self, mock_get_redis):
        mock_r = MagicMock()
        mock_pipe = MagicMock()
        mock_r.pipeline.return_value = mock_pipe
        mock_get_redis.return_value = mock_r

        books = {
            "DraftKings": [{"selection": "Over", "line": 220.5, "price": -110}],
        }
        write_live_snapshot(
            "NBA", 42, "total", books,
            source_request_id="req123", rate_remaining=99,
        )

        # Snapshot written
        mock_r.set.assert_called_once()
        key_arg = mock_r.set.call_args[0][0]
        assert key_arg == "live:odds:NBA:42:total"
        json_arg = json.loads(mock_r.set.call_args[0][1])
        assert "DraftKings" in json_arg["books"]
        assert json_arg["meta"]["source_request_id"] == "req123"
        assert json_arg["meta"]["rate_remaining"] == 99
        assert mock_r.set.call_args[1]["ex"] == LIVE_SNAPSHOT_TTL_S

        # History pipeline executed
        mock_pipe.lpush.assert_called_once()
        mock_pipe.ltrim.assert_called_once()
        mock_pipe.expire.assert_called_once()
        mock_pipe.execute.assert_called_once()

    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_write_handles_redis_error(self, mock_get_redis):
        mock_get_redis.side_effect = Exception("connection refused")
        # Should not raise
        write_live_snapshot("NBA", 1, "spread", {})


# ===========================================================================
# read_live_snapshot
# ===========================================================================

class TestReadLiveSnapshot:
    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_reads_existing_snapshot(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        snapshot = {"provider": "fanduel", "selections": []}
        mock_r.get.return_value = json.dumps(snapshot)
        mock_r.ttl.return_value = 3600

        result = read_live_snapshot("NBA", 42, "spread")
        assert result is not None
        assert result["provider"] == "fanduel"
        assert result["ttl_seconds_remaining"] == 3600

    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_returns_none_when_missing(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        mock_r.get.return_value = None

        assert read_live_snapshot("NBA", 42, "spread") is None

    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_read_handles_redis_error(self, mock_get_redis):
        mock_get_redis.side_effect = Exception("timeout")
        assert read_live_snapshot("NBA", 42, "spread") is None


# ===========================================================================
# read_live_history
# ===========================================================================

class TestReadLiveHistory:
    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_reads_history(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        items = [json.dumps({"t": 1, "selections": []})]
        mock_r.lrange.return_value = items

        result = read_live_history(42, "spread", count=10)
        assert len(result) == 1
        assert result[0]["t"] == 1
        mock_r.lrange.assert_called_with("live:odds:history:42:spread", 0, 9)

    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_returns_empty_on_error(self, mock_get_redis):
        mock_get_redis.side_effect = Exception("down")
        assert read_live_history(42, "spread") == []


# ===========================================================================
# get_all_live_keys_for_game
# ===========================================================================

class TestGetAllLiveKeys:
    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_returns_keys(self, mock_get_redis):
        mock_r = MagicMock()
        mock_get_redis.return_value = mock_r
        mock_r.scan_iter.return_value = iter(["live:odds:NBA:42:spread"])

        result = get_all_live_keys_for_game(42)
        assert result == ["live:odds:NBA:42:spread"]

    @patch("sports_scraper.live_odds.redis_store._get_redis")
    def test_returns_empty_on_error(self, mock_get_redis):
        mock_get_redis.side_effect = Exception("err")
        assert get_all_live_keys_for_game(42) == []


# ===========================================================================
# closing_lines.py
# ===========================================================================

from sports_scraper.live_odds.closing_lines import (
    capture_closing_lines,
    capture_closing_lines_from_provider,
)


class TestCaptureClosingLines:
    @patch("sports_scraper.live_odds.closing_lines.get_session")
    def test_skips_when_already_captured(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        # Already captured
        mock_session.execute.return_value.scalar_one_or_none.return_value = 1

        result = capture_closing_lines(42, "NBA")
        assert result == 0

    @patch("sports_scraper.live_odds.closing_lines.get_session")
    def test_returns_zero_when_no_odds(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        # No existing closing lines
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        # No pregame odds
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        result = capture_closing_lines(42, "NBA")
        assert result == 0

    @patch("sports_scraper.live_odds.closing_lines.get_session")
    def test_inserts_closing_lines(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        # First execute: no existing closing lines
        # Second execute: has odds rows
        mock_odds_row = MagicMock()
        mock_odds_row.source_key = "spread"
        mock_odds_row.market_type = "spread"
        mock_odds_row.side = "home"
        mock_odds_row.line = -3.5
        mock_odds_row.price = -110
        mock_odds_row.book = "FanDuel"

        call_count = [0]
        def side_effect(stmt):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = None
            elif call_count[0] == 2:
                result.scalars.return_value.all.return_value = [mock_odds_row]
            else:
                result.rowcount = 1
            return result
        mock_session.execute.side_effect = side_effect

        result = capture_closing_lines(42, "NBA")
        assert result == 1
        mock_session.commit.assert_called_once()


class TestCaptureClosingLinesFromProvider:
    @patch("sports_scraper.live_odds.closing_lines.capture_closing_lines")
    @patch("sports_scraper.live_odds.closing_lines.get_session")
    @patch("sports_scraper.odds.synchronizer.OddsSynchronizer")
    def test_late_capture_updates_source_type(self, mock_sync_cls, mock_get_session, mock_capture):
        mock_capture.return_value = 2
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_sync = MagicMock()
        mock_sync_cls.return_value = mock_sync

        result = capture_closing_lines_from_provider(42, "NBA")
        assert result == 2
        mock_sync.sync.assert_called_once()
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @patch("sports_scraper.live_odds.closing_lines.capture_closing_lines")
    @patch("sports_scraper.odds.synchronizer.OddsSynchronizer")
    def test_late_capture_sync_failure_still_tries(self, mock_sync_cls, mock_capture):
        mock_capture.return_value = 0
        mock_sync = MagicMock()
        mock_sync.sync.side_effect = Exception("api down")
        mock_sync_cls.return_value = mock_sync

        result = capture_closing_lines_from_provider(42, "NBA")
        assert result == 0
