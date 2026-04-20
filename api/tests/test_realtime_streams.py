"""Tests for Redis Streams bridge (ISSUE-039).

All Redis interactions are mocked; no live Redis required.
Tests use asyncio.new_event_loop() to match the project's existing test style
(pytest-asyncio is not installed in this project).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.realtime.streams import (
    GROUP_NAME,
    SEQ_HASH,
    STREAM_KEY,
    STREAM_MAXLEN,
    RedisStreamsBridge,
)
from app.realtime.manager import RealtimeManager, SSEConnection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bridge(redis_url: str = "redis://localhost:6379/2") -> RedisStreamsBridge:
    return RedisStreamsBridge(redis_url=redis_url, boot_epoch="test-boot-epoch")


def _make_mock_redis() -> AsyncMock:
    r = AsyncMock()
    r.hincrby = AsyncMock(return_value=1)
    r.xadd = AsyncMock(return_value="1000000-0")
    r.xgroup_create = AsyncMock(return_value=True)
    r.xreadgroup = AsyncMock(return_value=None)
    r.xack = AsyncMock(return_value=1)
    r.hget = AsyncMock(return_value=None)
    r.aclose = AsyncMock()
    return r


def _run(coro):
    """Run a coroutine to completion in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Consumer ID
# ---------------------------------------------------------------------------


class TestConsumerId:
    def test_consumer_id_includes_hostname_and_pid(self):
        bridge = _make_bridge()
        parts = bridge.consumer_id.split("-")
        assert len(parts) >= 2
        assert parts[-1].isdigit()  # PID is numeric

    def test_group_name_prefixed_with_realtime_api(self):
        bridge = _make_bridge()
        assert bridge.group_name.startswith(GROUP_NAME + ":")


# ---------------------------------------------------------------------------
# Start: group creation
# ---------------------------------------------------------------------------


class TestStart:
    def test_start_creates_shared_and_per_process_groups(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())
                await bridge.stop()

        _run(run())

        calls = mock_redis.xgroup_create.call_args_list
        group_names = [c.args[1] for c in calls]
        assert GROUP_NAME in group_names
        assert bridge.group_name in group_names

    def test_start_ignores_busygroup_error(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        import redis.asyncio as aioredis

        mock_redis.xgroup_create.side_effect = aioredis.ResponseError(
            "BUSYGROUP Consumer Group name already exists"
        )

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())
                await bridge.stop()

        # Should not raise
        _run(run())

    def test_start_raises_non_busygroup_errors(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        import redis.asyncio as aioredis

        mock_redis.xgroup_create.side_effect = aioredis.ResponseError(
            "WRONGTYPE Operation on a key holding a wrong type of value"
        )

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())

        with pytest.raises(aioredis.ResponseError):
            _run(run())


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class TestPublish:
    def test_publish_increments_seq_in_redis(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        mock_redis.hincrby = AsyncMock(return_value=7)

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())
                seq = await bridge.publish("game:1:summary", "game_patch", {"gameId": "1"})
                await bridge.stop()
                return seq

        seq = _run(run())
        mock_redis.hincrby.assert_called_once_with(SEQ_HASH, "game:1:summary", 1)
        assert seq == 7

    def test_publish_writes_to_stream(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())
                await bridge.publish("game:42:summary", "game_patch", {"k": "v"})
                await bridge.stop()

        _run(run())

        call = mock_redis.xadd.call_args
        assert call.args[0] == STREAM_KEY
        fields = call.args[1]
        assert fields["channel"] == "game:42:summary"
        assert fields["type"] == "game_patch"
        assert json.loads(fields["payload"]) == {"k": "v"}
        assert fields["boot_epoch"] == "test-boot-epoch"

    def test_publish_uses_minid_trim(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())
                await bridge.publish("fairbet:odds", "fairbet_patch", {})
                await bridge.stop()

        _run(run())

        call = mock_redis.xadd.call_args
        # Time-based retention via MINID (not MAXLEN — see docs/research/redis-pubsub-vs-streams)
        assert call.kwargs.get("maxlen") is None
        assert call.kwargs.get("minid") is not None
        assert call.kwargs.get("approximate") is True

    def test_publish_raises_when_not_started(self):
        bridge = _make_bridge()
        with pytest.raises(RuntimeError, match="not started"):
            _run(bridge.publish("game:1:summary", "game_patch", {}))


# ---------------------------------------------------------------------------
# get_seq
# ---------------------------------------------------------------------------


class TestGetSeq:
    def test_get_seq_returns_zero_when_no_value(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        mock_redis.hget = AsyncMock(return_value=None)

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())
                seq = await bridge.get_seq("game:1:summary")
                await bridge.stop()
                return seq

        assert _run(run()) == 0

    def test_get_seq_returns_stored_value(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        mock_redis.hget = AsyncMock(return_value="42")

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(AsyncMock())
                seq = await bridge.get_seq("game:1:summary")
                await bridge.stop()
                return seq

        assert _run(run()) == 42

    def test_get_seq_returns_zero_when_not_started(self):
        bridge = _make_bridge()
        assert _run(bridge.get_seq("game:1:summary")) == 0


# ---------------------------------------------------------------------------
# _handle_entry
# ---------------------------------------------------------------------------


class TestHandleEntry:
    def test_handle_entry_calls_dispatch_fn(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        dispatch_fn = AsyncMock()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(dispatch_fn)
                fields = {
                    "channel": "game:1:summary",
                    "type": "game_patch",
                    "payload": json.dumps({"gameId": "1"}),
                    "boot_epoch": "1000000",
                    "seq": "5",
                }
                await bridge._handle_entry("1000000-0", fields)
                await bridge.stop()

        _run(run())
        dispatch_fn.assert_called_once_with(
            "game:1:summary", "game_patch", 5, {"gameId": "1"}
        )

    def test_handle_entry_acks_after_dispatch(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        dispatch_fn = AsyncMock()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(dispatch_fn)
                fields = {
                    "channel": "game:1:summary",
                    "type": "game_patch",
                    "payload": "{}",
                    "boot_epoch": "1000000",
                    "seq": "1",
                }
                await bridge._handle_entry("1000-0", fields)
                await bridge.stop()

        _run(run())
        mock_redis.xack.assert_called_once_with(STREAM_KEY, bridge.group_name, "1000-0")

    def test_handle_entry_acks_bad_entry_and_does_not_raise(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        dispatch_fn = AsyncMock()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(dispatch_fn)
                await bridge._handle_entry("bad-0", {"junk": "data"})
                await bridge.stop()

        _run(run())
        dispatch_fn.assert_not_called()
        mock_redis.xack.assert_called_once_with(STREAM_KEY, bridge.group_name, "bad-0")

    def test_handle_entry_acks_even_if_dispatch_raises(self):
        bridge = _make_bridge()
        mock_redis = _make_mock_redis()
        dispatch_fn = AsyncMock(side_effect=RuntimeError("boom"))

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis):
                await bridge.start(dispatch_fn)
                fields = {
                    "channel": "game:1:summary",
                    "type": "game_patch",
                    "payload": "{}",
                    "boot_epoch": "1000000",
                    "seq": "1",
                }
                await bridge._handle_entry("1000-0", fields)
                await bridge.stop()

        _run(run())
        # Must still ACK despite dispatch error
        mock_redis.xack.assert_called()


# ---------------------------------------------------------------------------
# Manager integration
# ---------------------------------------------------------------------------


class TestManagerWithBridge:
    def test_publish_delegates_to_bridge(self):
        mgr = RealtimeManager()
        mock_bridge = AsyncMock()
        mock_bridge.publish = AsyncMock(return_value=3)
        mock_bridge.consumer_id = "host-1234"
        mock_bridge.group_name = f"{GROUP_NAME}:host-1234"
        mgr.set_streams_bridge(mock_bridge)

        seq = _run(mgr.publish("game:1:summary", "game_patch", {"x": 1}))

        assert seq == 3
        mock_bridge.publish.assert_called_once_with(
            "game:1:summary", "game_patch", {"x": 1}
        )

    def test_dispatch_local_fans_out_to_subscribers(self):
        mgr = RealtimeManager()
        conn = AsyncMock()
        conn.id = "ws-test"
        mgr.subscribe(conn, "game:1:summary")

        _run(mgr._dispatch_local("game:1:summary", "game_patch", 7, {"gameId": "1"}))

        conn.send_event.assert_called_once()
        data = json.loads(conn.send_event.call_args[0][0])
        assert data["type"] == "game_patch"
        assert data["seq"] == 7
        assert data["channel"] == "game:1:summary"
        assert data["boot_epoch"] == mgr.boot_epoch
        assert data["gameId"] == "1"

    def test_dispatch_local_uses_local_boot_epoch(self):
        """Boot epoch in outbound events must be the local process's value."""
        mgr = RealtimeManager()
        conn = AsyncMock()
        conn.id = "ws-test"
        mgr.subscribe(conn, "game:1:summary")

        _run(mgr._dispatch_local("game:1:summary", "game_patch", 1, {}))

        data = json.loads(conn.send_event.call_args[0][0])
        assert data["boot_epoch"] == mgr.boot_epoch

    def test_end_to_end_bridge_consumer_to_local_dispatch(self):
        """Consumer loop delivers to SSE connection via _dispatch_local."""
        mgr = RealtimeManager()
        sse_conn = SSEConnection()
        mgr.subscribe(sse_conn, "game:99:summary")

        _run(
            mgr._dispatch_local(
                "game:99:summary",
                "game_patch",
                12,
                {"gameId": "99", "patch": {"status": "LIVE"}},
            )
        )

        assert sse_conn.queue.qsize() == 1

        async def get():
            return await sse_conn.queue.get()

        raw = _run(get())
        event = json.loads(raw)
        assert event["seq"] == 12
        assert event["type"] == "game_patch"
        assert event["patch"] == {"status": "LIVE"}

    def test_status_includes_streams_info_when_bridge_set(self):
        mgr = RealtimeManager()
        mock_bridge = MagicMock()
        mock_bridge.consumer_id = "myhost-5678"
        mock_bridge.group_name = f"{GROUP_NAME}:myhost-5678"
        mgr.set_streams_bridge(mock_bridge)

        st = mgr.status()
        assert st["streams_consumer_id"] == "myhost-5678"
        assert "streams_group" in st

    def test_status_no_bridge_omits_streams_keys(self):
        mgr = RealtimeManager()
        st = mgr.status()
        assert "streams_consumer_id" not in st
        assert "streams_group" not in st

    def test_fallback_publish_when_no_bridge(self):
        """Without bridge, publish() still delivers in-process (unit-test path)."""
        mgr = RealtimeManager()
        conn = AsyncMock()
        conn.id = "ws-1"
        mgr.subscribe(conn, "game:1:summary")

        seq = _run(mgr.publish("game:1:summary", "game_patch", {}))
        assert seq == 1
        conn.send_event.assert_called_once()


# ---------------------------------------------------------------------------
# Multi-process fanout (acceptance criterion 2)
# ---------------------------------------------------------------------------


class TestMultiProcessFanout:
    """Two API worker processes both receive the same event from the shared stream.

    Simulated by creating two independent RealtimeManager + RedisStreamsBridge
    instances (each with its own per-process consumer group) and delivering the
    same stream entry to both via _handle_entry.
    """

    def test_two_processes_both_receive_same_entry(self):
        """Publish one entry; both process-A and process-B managers deliver it
        to their respective local SSE subscribers."""
        channel = "game:7:summary"
        entry_id = "1713400000000-0"
        fields = {
            "channel": channel,
            "type": "game_patch",
            "payload": json.dumps({"gameId": "7", "patch": {"status": "LIVE"}}),
            "boot_epoch": "shared-epoch",
            "seq": "5",
        }

        mgr_a = RealtimeManager()
        mgr_b = RealtimeManager()
        conn_a = SSEConnection()
        conn_b = SSEConnection()
        mgr_a.subscribe(conn_a, channel)
        mgr_b.subscribe(conn_b, channel)

        bridge_a = _make_bridge()
        bridge_b = _make_bridge()

        mock_redis_a = _make_mock_redis()
        mock_redis_b = _make_mock_redis()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis_a):
                await bridge_a.start(mgr_a._dispatch_local)
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis_b):
                await bridge_b.start(mgr_b._dispatch_local)

            # Both processes independently consume the same stream entry.
            await bridge_a._handle_entry(entry_id, fields)
            await bridge_b._handle_entry(entry_id, fields)

            await bridge_a.stop()
            await bridge_b.stop()

        _run(run())

        assert conn_a.queue.qsize() == 1
        assert conn_b.queue.qsize() == 1

        async def drain():
            ev_a = json.loads(await conn_a.queue.get())
            ev_b = json.loads(await conn_b.queue.get())
            return ev_a, ev_b

        ev_a, ev_b = _run(drain())
        assert ev_a["seq"] == 5
        assert ev_b["seq"] == 5
        assert ev_a["type"] == "game_patch"
        assert ev_b["type"] == "game_patch"
        # Each process stamps its own boot_epoch on outbound events.
        assert ev_a["boot_epoch"] == mgr_a.boot_epoch
        assert ev_b["boot_epoch"] == mgr_b.boot_epoch

    def test_per_process_consumer_groups_are_distinct(self):
        """Each bridge gets a unique consumer group; both see every event."""
        bridge_a = _make_bridge()
        bridge_b = _make_bridge()

        assert bridge_a.group_name != bridge_b.group_name
        assert bridge_a.consumer_id != bridge_b.consumer_id
        # Both group names are prefixed with the shared group name.
        assert bridge_a.group_name.startswith(GROUP_NAME + ":")
        assert bridge_b.group_name.startswith(GROUP_NAME + ":")

    def test_bridge_consumer_id_includes_pid(self):
        """Consumer ID embeds hostname + PID so each process is unique."""
        import os
        bridge = _make_bridge()
        pid = str(os.getpid())
        assert pid in bridge.consumer_id


# ---------------------------------------------------------------------------
# 500-subscriber load test (acceptance criterion 5)
# ---------------------------------------------------------------------------


class TestLoadFanout:
    """500 concurrent SSE subscribers on two simulated worker processes.

    All subscribers must receive the event within 2 seconds.
    Redis is mocked; this measures in-process fan-out throughput.
    """

    def test_500_subscribers_receive_event_within_2s(self):
        import time

        channel = "game:99:summary"
        n_per_process = 250  # 250 x 2 = 500 total subscribers

        mgr_a = RealtimeManager()
        mgr_b = RealtimeManager()

        conns_a = []
        conns_b = []
        for i in range(n_per_process):
            c = SSEConnection()
            mgr_a.subscribe(c, channel)
            conns_a.append(c)
        for i in range(n_per_process):
            c = SSEConnection()
            mgr_b.subscribe(c, channel)
            conns_b.append(c)

        entry_fields = {
            "channel": channel,
            "type": "game_patch",
            "payload": json.dumps({"gameId": "99"}),
            "boot_epoch": "load-epoch",
            "seq": "1",
        }

        bridge_a = _make_bridge()
        bridge_b = _make_bridge()
        mock_redis_a = _make_mock_redis()
        mock_redis_b = _make_mock_redis()

        async def run():
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis_a):
                await bridge_a.start(mgr_a._dispatch_local)
            with patch("app.realtime.streams.aioredis.from_url", return_value=mock_redis_b):
                await bridge_b.start(mgr_b._dispatch_local)

            start = time.monotonic()
            # Simulate both processes consuming the same event concurrently.
            await asyncio.gather(
                bridge_a._handle_entry("1000-0", entry_fields),
                bridge_b._handle_entry("1000-0", entry_fields),
            )
            elapsed = time.monotonic() - start

            await bridge_a.stop()
            await bridge_b.stop()
            return elapsed

        elapsed = _run(run())

        assert elapsed < 2.0, f"Fan-out took {elapsed:.3f}s, expected < 2s"

        delivered_a = sum(1 for c in conns_a if c.queue.qsize() == 1)
        delivered_b = sum(1 for c in conns_b if c.queue.qsize() == 1)
        assert delivered_a == n_per_process, f"Process A: only {delivered_a}/{n_per_process} delivered"
        assert delivered_b == n_per_process, f"Process B: only {delivered_b}/{n_per_process} delivered"
