"""Tests for the realtime layer: models, manager, WS, SSE."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.realtime.manager import RealtimeManager, SSEConnection, WSConnection
from app.realtime.models import (
    EASTERN,
    MAX_CHANNELS_PER_CONNECTION,
    RealtimeEvent,
    is_valid_channel,
    parse_channel,
    to_et_date,
)


# ---------------------------------------------------------------------------
# Channel validation
# ---------------------------------------------------------------------------


class TestChannelValidation:
    """Channel format parsing and validation."""

    def test_valid_games_list_channel(self):
        assert is_valid_channel("games:NBA:2026-03-05")
        assert is_valid_channel("games:NCAAB:2026-12-31")
        assert is_valid_channel("games:NHL:2026-01-01")
        assert is_valid_channel("games:MLB:2026-06-15")

    def test_valid_game_summary_channel(self):
        assert is_valid_channel("game:12345:summary")
        assert is_valid_channel("game:1:summary")

    def test_valid_game_pbp_channel(self):
        assert is_valid_channel("game:12345:pbp")

    def test_valid_fairbet_channel(self):
        assert is_valid_channel("fairbet:odds")

    def test_invalid_channels(self):
        assert not is_valid_channel("")
        assert not is_valid_channel("games:nba:2026-03-05")  # lowercase league
        assert not is_valid_channel("game:abc:summary")       # non-numeric id
        assert not is_valid_channel("game:123:unknown")        # unknown sub-type
        assert not is_valid_channel("foo:bar")
        assert not is_valid_channel("games:NBA:not-a-date")

    def test_parse_games_list(self):
        parsed = parse_channel("games:NBA:2026-03-05")
        assert parsed == {"type": "games_list", "league": "NBA", "date": "2026-03-05"}

    def test_parse_game_summary(self):
        parsed = parse_channel("game:42:summary")
        assert parsed == {"type": "game_summary", "game_id": "42"}

    def test_parse_game_pbp(self):
        parsed = parse_channel("game:99:pbp")
        assert parsed == {"type": "game_pbp", "game_id": "99"}

    def test_parse_fairbet(self):
        parsed = parse_channel("fairbet:odds")
        assert parsed == {"type": "fairbet_odds"}

    def test_parse_invalid_returns_empty(self):
        assert parse_channel("garbage") == {}


# ---------------------------------------------------------------------------
# to_et_date helper
# ---------------------------------------------------------------------------


class TestToEtDate:
    def test_utc_evening_maps_to_same_et_date(self):
        # 2026-03-05 22:00 UTC = 2026-03-05 17:00 ET (same day)
        dt = datetime(2026, 3, 5, 22, 0, tzinfo=timezone.utc)
        assert to_et_date(dt) == "2026-03-05"

    def test_utc_late_night_maps_to_previous_et_date(self):
        # 2026-03-06 03:00 UTC = 2026-03-05 22:00 ET (previous day)
        dt = datetime(2026, 3, 6, 3, 0, tzinfo=timezone.utc)
        assert to_et_date(dt) == "2026-03-05"

    def test_utc_early_morning_maps_correctly(self):
        # 2026-03-05 06:00 UTC = 2026-03-05 01:00 ET (same day)
        dt = datetime(2026, 3, 5, 6, 0, tzinfo=timezone.utc)
        assert to_et_date(dt) == "2026-03-05"


# ---------------------------------------------------------------------------
# RealtimeEvent serialization
# ---------------------------------------------------------------------------


class TestRealtimeEvent:
    def test_to_dict_merges_payload(self):
        event = RealtimeEvent(
            type="game_patch",
            channel="game:1:summary",
            seq=5,
            payload={"gameId": "1", "patch": {"status": "LIVE"}},
            boot_epoch=1000000,
            ts=1000,
        )
        d = event.to_dict()
        assert d["type"] == "game_patch"
        assert d["channel"] == "game:1:summary"
        assert d["seq"] == 5
        assert d["ts"] == 1000
        assert d["boot_epoch"] == 1000000
        assert d["gameId"] == "1"
        assert d["patch"] == {"status": "LIVE"}

    def test_boot_epoch_present_in_envelope(self):
        event = RealtimeEvent(
            type="game_patch",
            channel="game:1:summary",
            seq=1,
            payload={},
            boot_epoch=12345,
        )
        d = event.to_dict()
        assert "boot_epoch" in d
        assert d["boot_epoch"] == 12345


# ---------------------------------------------------------------------------
# RealtimeManager
# ---------------------------------------------------------------------------


class TestRealtimeManager:
    def test_subscribe_valid_channel(self):
        mgr = RealtimeManager()
        conn = MagicMock()
        conn.id = "test-1"
        assert mgr.subscribe(conn, "game:1:summary") is True

    def test_subscribe_invalid_channel(self):
        mgr = RealtimeManager()
        conn = MagicMock()
        conn.id = "test-1"
        assert mgr.subscribe(conn, "invalid") is False

    def test_channel_limit(self):
        mgr = RealtimeManager()
        conn = MagicMock()
        conn.id = "test-1"

        # Subscribe up to limit
        for i in range(MAX_CHANNELS_PER_CONNECTION):
            assert mgr.subscribe(conn, f"game:{i}:summary") is True

        # One more should fail
        assert mgr.subscribe(conn, f"game:{MAX_CHANNELS_PER_CONNECTION}:summary") is False

    def test_unsubscribe(self):
        mgr = RealtimeManager()
        conn = MagicMock()
        conn.id = "test-1"
        mgr.subscribe(conn, "game:1:summary")
        mgr.unsubscribe(conn, "game:1:summary")
        assert not mgr.has_subscribers("game:1:summary")

    def test_disconnect_removes_all(self):
        mgr = RealtimeManager()
        conn = MagicMock()
        conn.id = "test-1"
        mgr.subscribe(conn, "game:1:summary")
        mgr.subscribe(conn, "game:2:summary")
        mgr.disconnect(conn)
        assert not mgr.has_subscribers("game:1:summary")
        assert not mgr.has_subscribers("game:2:summary")

    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscriber(self):
        mgr = RealtimeManager()
        conn = AsyncMock()
        conn.id = "test-1"
        mgr.subscribe(conn, "game:1:summary")

        seq = await mgr.publish("game:1:summary", "game_patch", {"gameId": "1", "patch": {}})
        assert seq == 1

        conn.send_event.assert_called_once()
        data = json.loads(conn.send_event.call_args[0][0])
        assert data["type"] == "game_patch"
        assert data["seq"] == 1
        assert data["channel"] == "game:1:summary"
        assert "boot_epoch" in data

    @pytest.mark.asyncio
    async def test_publish_includes_boot_epoch(self):
        mgr = RealtimeManager()
        conn = AsyncMock()
        conn.id = "test-1"
        mgr.subscribe(conn, "game:1:summary")

        await mgr.publish("game:1:summary", "game_patch", {})

        data = json.loads(conn.send_event.call_args[0][0])
        assert data["boot_epoch"] == mgr.boot_epoch

    @pytest.mark.asyncio
    async def test_seq_increments_per_channel(self):
        mgr = RealtimeManager()
        conn = AsyncMock()
        conn.id = "test-1"
        mgr.subscribe(conn, "game:1:summary")
        mgr.subscribe(conn, "game:2:summary")

        seq1 = await mgr.publish("game:1:summary", "game_patch", {})
        seq2 = await mgr.publish("game:1:summary", "game_patch", {})
        seq3 = await mgr.publish("game:2:summary", "game_patch", {})

        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 1  # Independent channel

    @pytest.mark.asyncio
    async def test_publish_drops_broken_subscriber(self):
        mgr = RealtimeManager()
        good_conn = AsyncMock()
        good_conn.id = "good"
        bad_conn = AsyncMock()
        bad_conn.id = "bad"
        bad_conn.send_event.side_effect = ConnectionError("broken pipe")

        mgr.subscribe(good_conn, "game:1:summary")
        mgr.subscribe(bad_conn, "game:1:summary")

        await mgr.publish("game:1:summary", "game_patch", {})

        # Good conn received it
        good_conn.send_event.assert_called_once()
        # Bad conn was disconnected
        assert not mgr.has_subscribers("game:1:summary") or "bad" not in {
            c.id for c in mgr._subscribers.get("game:1:summary", set())
        }

    @pytest.mark.asyncio
    async def test_publish_drops_timeout_subscriber(self):
        mgr = RealtimeManager()
        good_conn = AsyncMock()
        good_conn.id = "good"
        slow_conn = AsyncMock()
        slow_conn.id = "slow"
        slow_conn.send_event.side_effect = asyncio.TimeoutError()

        mgr.subscribe(good_conn, "game:1:summary")
        mgr.subscribe(slow_conn, "game:1:summary")

        await mgr.publish("game:1:summary", "game_patch", {})

        good_conn.send_event.assert_called_once()
        assert "slow" not in {
            c.id for c in mgr._subscribers.get("game:1:summary", set())
        }
        assert mgr._error_count == 1

    @pytest.mark.asyncio
    async def test_sse_queue_overflow_disconnects(self):
        mgr = RealtimeManager()
        conn = SSEConnection()
        mgr.subscribe(conn, "game:1:summary")

        # Fill the queue
        for _ in range(200):
            await conn.queue.put("x")

        # Next publish should overflow and disconnect
        await mgr.publish("game:1:summary", "game_patch", {})
        assert not mgr.has_subscribers("game:1:summary")

    def test_status_includes_boot_epoch(self):
        mgr = RealtimeManager()
        st = mgr.status()
        assert "boot_epoch" in st
        assert st["boot_epoch"] == mgr.boot_epoch
        assert "publish_count" in st
        assert "error_count" in st

    def test_status(self):
        mgr = RealtimeManager()
        c1 = MagicMock()
        c1.id = "c1"
        c2 = MagicMock()
        c2.id = "c2"
        mgr.subscribe(c1, "game:1:summary")
        mgr.subscribe(c2, "game:1:summary")
        mgr.subscribe(c1, "game:2:pbp")

        st = mgr.status()
        assert st["total_connections"] == 2
        assert st["total_channels"] == 2
        assert st["channels"]["game:1:summary"] == 2
        assert st["channels"]["game:2:pbp"] == 1

    def test_active_channels(self):
        mgr = RealtimeManager()
        conn = MagicMock()
        conn.id = "c1"
        mgr.subscribe(conn, "game:1:summary")
        mgr.subscribe(conn, "game:2:pbp")

        assert mgr.active_channels() == {"game:1:summary", "game:2:pbp"}

    @pytest.mark.asyncio
    async def test_first_subscriber_callback_fires(self):
        mgr = RealtimeManager()
        callback = AsyncMock()
        mgr.set_on_first_subscriber(callback)

        conn = MagicMock()
        conn.id = "test-1"
        mgr.subscribe(conn, "game:1:summary")

        # Give the asyncio.ensure_future a chance to run
        await asyncio.sleep(0.01)
        callback.assert_called_once_with("game:1:summary")

    @pytest.mark.asyncio
    async def test_first_subscriber_callback_does_not_fire_on_second(self):
        mgr = RealtimeManager()
        callback = AsyncMock()
        mgr.set_on_first_subscriber(callback)

        c1 = MagicMock()
        c1.id = "c1"
        c2 = MagicMock()
        c2.id = "c2"

        mgr.subscribe(c1, "game:1:summary")
        await asyncio.sleep(0.01)

        callback.reset_mock()
        mgr.subscribe(c2, "game:1:summary")
        await asyncio.sleep(0.01)

        callback.assert_not_called()


# ---------------------------------------------------------------------------
# SSEConnection
# ---------------------------------------------------------------------------


class TestSSEConnection:
    @pytest.mark.asyncio
    async def test_send_event_puts_on_queue(self):
        conn = SSEConnection()
        await conn.send_event("hello")
        assert conn.queue.qsize() == 1
        assert await conn.queue.get() == "hello"

    @pytest.mark.asyncio
    async def test_overflow_raises(self):
        conn = SSEConnection()
        for _ in range(200):
            await conn.queue.put("x")
        with pytest.raises(OverflowError):
            await conn.send_event("boom")


# ---------------------------------------------------------------------------
# WSConnection send timeout
# ---------------------------------------------------------------------------


class TestWSConnection:
    @pytest.mark.asyncio
    async def test_send_event_calls_send_text(self):
        ws = AsyncMock()
        conn = WSConnection(ws)
        await conn.send_event("hello")
        ws.send_text.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_send_event_timeout_raises(self):
        ws = AsyncMock()

        async def slow_send(data):
            await asyncio.sleep(10)

        ws.send_text.side_effect = slow_send
        conn = WSConnection(ws)

        with pytest.raises(asyncio.TimeoutError):
            await conn.send_event("hello")


# ---------------------------------------------------------------------------
# Poller LRU set
# ---------------------------------------------------------------------------


class TestLRUSet:
    def test_bounded_eviction(self):
        from app.realtime.poller import _LRUSet

        lru = _LRUSet(maxsize=3)
        lru.add(1)
        lru.add(2)
        lru.add(3)
        assert 1 in lru
        assert len(lru) == 3

        # Adding 4th should evict 1
        lru.add(4)
        assert 1 not in lru
        assert 4 in lru
        assert len(lru) == 3

    def test_access_refreshes(self):
        from app.realtime.poller import _LRUSet

        lru = _LRUSet(maxsize=3)
        lru.add(1)
        lru.add(2)
        lru.add(3)

        # Re-add 1 to refresh it
        lru.add(1)

        # Adding 4 should now evict 2 (oldest untouched)
        lru.add(4)
        assert 1 in lru
        assert 2 not in lru
        assert 3 in lru
        assert 4 in lru
