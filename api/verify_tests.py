"""Quick smoke test to verify key ISSUE-022 implementations."""
import asyncio
import json
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, ".")

from app.realtime.streams import RedisStreamsBridge, GROUP_NAME, STREAM_KEY, SEQ_HASH
from app.realtime.manager import RealtimeManager, SSEConnection


def make_bridge(epoch="test-epoch"):
    return RedisStreamsBridge("redis://localhost", epoch)


def make_redis():
    r = AsyncMock()
    r.hincrby = AsyncMock(return_value=1)
    r.xadd = AsyncMock(return_value="1000000-0")
    r.xgroup_create = AsyncMock(return_value=True)
    r.xreadgroup = AsyncMock(return_value=None)
    r.xack = AsyncMock(return_value=1)
    r.hget = AsyncMock(return_value=None)
    r.aclose = AsyncMock()
    return r


async def test_minid_trim():
    bridge = make_bridge()
    mr = make_redis()
    with patch("app.realtime.streams.aioredis.from_url", return_value=mr):
        await bridge.start(AsyncMock())
        await bridge.publish("game:1:summary", "patch", {})
        await bridge.stop()
    call = mr.xadd.call_args
    assert call.kwargs.get("maxlen") is None, f"maxlen should not be set; got {call.kwargs.get('maxlen')}"
    assert call.kwargs.get("minid") is not None, "minid must be set"
    assert call.kwargs.get("approximate") is True
    print("test_minid_trim: PASS")


async def test_multiprocess_fanout():
    ch = "game:7:summary"
    fields = {
        "channel": ch, "type": "patch",
        "payload": json.dumps({"gameId": "7"}),
        "boot_epoch": "e1", "seq": "5",
    }
    ma, mb = RealtimeManager(), RealtimeManager()
    ca, cb = SSEConnection(), SSEConnection()
    ma.subscribe(ca, ch)
    mb.subscribe(cb, ch)
    ba, bb = make_bridge(), make_bridge()
    with patch("app.realtime.streams.aioredis.from_url", return_value=make_redis()):
        await ba.start(ma._dispatch_local)
    with patch("app.realtime.streams.aioredis.from_url", return_value=make_redis()):
        await bb.start(mb._dispatch_local)
    await ba._handle_entry("1-0", fields)
    await bb._handle_entry("1-0", fields)
    await ba.stop()
    await bb.stop()
    assert ca.queue.qsize() == 1, f"process A: {ca.queue.qsize()} events"
    assert cb.queue.qsize() == 1, f"process B: {cb.queue.qsize()} events"
    ea = json.loads(await ca.queue.get())
    eb = json.loads(await cb.queue.get())
    assert ea["seq"] == 5 and eb["seq"] == 5
    assert ea["boot_epoch"] == ma.boot_epoch
    assert eb["boot_epoch"] == mb.boot_epoch
    print("test_multiprocess_fanout: PASS")


async def test_load_500_subscribers():
    import time
    ch = "game:99:summary"
    n = 250
    ma, mb = RealtimeManager(), RealtimeManager()
    conns_a = [SSEConnection() for _ in range(n)]
    conns_b = [SSEConnection() for _ in range(n)]
    for c in conns_a:
        ma.subscribe(c, ch)
    for c in conns_b:
        mb.subscribe(c, ch)
    fields = {"channel": ch, "type": "patch", "payload": json.dumps({}), "boot_epoch": "e", "seq": "1"}
    ba, bb = make_bridge(), make_bridge()
    with patch("app.realtime.streams.aioredis.from_url", return_value=make_redis()):
        await ba.start(ma._dispatch_local)
    with patch("app.realtime.streams.aioredis.from_url", return_value=make_redis()):
        await bb.start(mb._dispatch_local)
    start = time.monotonic()
    await asyncio.gather(
        ba._handle_entry("1-0", fields),
        bb._handle_entry("1-0", fields),
    )
    elapsed = time.monotonic() - start
    await ba.stop()
    await bb.stop()
    assert elapsed < 2.0, f"Fan-out took {elapsed:.3f}s"
    da = sum(1 for c in conns_a if c.queue.qsize() == 1)
    db = sum(1 for c in conns_b if c.queue.qsize() == 1)
    assert da == n, f"A: {da}/{n}"
    assert db == n, f"B: {db}/{n}"
    print(f"test_load_500_subscribers: PASS ({elapsed*1000:.1f}ms for 500 subscribers)")


async def test_manager_delegates_to_bridge():
    mgr = RealtimeManager()
    mock_bridge = AsyncMock()
    mock_bridge.publish = AsyncMock(return_value=7)
    mock_bridge.consumer_id = "host-123"
    mock_bridge.group_name = f"{GROUP_NAME}:host-123"
    mgr.set_streams_bridge(mock_bridge)
    seq = await mgr.publish("game:1:summary", "patch", {})
    assert seq == 7
    print("test_manager_delegates_to_bridge: PASS")


async def test_no_in_memory_seqs_survive_restart():
    """In-memory seq counter is only used when no bridge; with bridge, Redis HINCRBY is authoritative."""
    mgr = RealtimeManager()
    mock_bridge = AsyncMock()
    mock_bridge.publish = AsyncMock(side_effect=[1, 2, 3])
    mock_bridge.consumer_id = "h"
    mock_bridge.group_name = "rg:h"
    mgr.set_streams_bridge(mock_bridge)
    for _ in range(3):
        await mgr.publish("game:1:summary", "patch", {})
    # _seq dict should remain empty (bridge handles sequencing)
    assert mgr._seq == {}, f"In-memory seq leaked: {mgr._seq}"
    print("test_no_in_memory_seqs_survive_restart: PASS")


async def main():
    tests = [
        test_minid_trim,
        test_multiprocess_fanout,
        test_load_500_subscribers,
        test_manager_delegates_to_bridge,
        test_no_in_memory_seqs_survive_restart,
    ]
    failed = []
    for t in tests:
        try:
            await t()
        except Exception as e:
            print(f"{t.__name__}: FAIL — {e}")
            import traceback; traceback.print_exc()
            failed.append(t.__name__)
    if failed:
        print(f"\nFAILED: {failed}")
        sys.exit(1)
    else:
        print("\nAll ISSUE-022 smoke tests passed.")


asyncio.run(main())
