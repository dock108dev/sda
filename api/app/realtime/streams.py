"""Redis Streams bridge for multi-process realtime fan-out.

Architecture:
  Writers → XADD realtime:events → per-process consumer group
  → consumer loop → dispatch_fn() → WS/SSE connections

Each API process creates its own consumer group (`realtime-api:{consumer_id}`)
starting from `$` so it only receives events generated after boot. A shared
group `realtime-api` is also created for operational monitoring (XINFO, etc.).

Sequence numbers are stored in Redis hash `realtime:seq` via HINCRBY so they
are consistent across processes and survive restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

STREAM_KEY = "realtime:events"
GROUP_NAME = "realtime-api"  # shared monitoring group
SEQ_HASH = "realtime:seq"
STREAM_MAXLEN = 10_000  # used as scan limit in fetch_backlog
# Time-based retention window; controls MINID trim on XADD and backfill scan start.
STREAM_RETENTION_MS = int(os.getenv("REALTIME_STREAM_RETENTION_MS", str(3_600_000)))

# Dispatch function type: (channel, event_type, seq, payload) -> None
DispatchFn = Callable[[str, str, int, dict[str, Any]], Coroutine[Any, Any, None]]


def _make_consumer_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class RedisStreamsBridge:
    """Publish to and consume from a Redis Stream for multi-process fanout.

    One instance per API process.  The per-process consumer group guarantees
    broadcast semantics: every process receives every event independently.
    """

    _BLOCK_MS = 5_000
    _READ_COUNT = 100
    _INITIAL_BACKOFF = 1.0
    _MAX_BACKOFF = 60.0
    # After this many consecutive ack failures the consumer escalates to an
    # ERROR log and resets the counter. Tunable via the constant rather than
    # env because failure escalation should be deterministic across deploys.
    _ACK_FAILURE_ESCALATE_AT = 10

    def __init__(self, redis_url: str, boot_epoch: str) -> None:
        self._redis_url = redis_url
        self._boot_epoch = boot_epoch
        self._consumer_id = _make_consumer_id()
        # Per-process consumer group for broadcast (each process gets all msgs)
        self._group_name = f"{GROUP_NAME}:{self._consumer_id}"
        self._publish_client: aioredis.Redis | None = None
        self._consumer_client: aioredis.Redis | None = None
        self._task: asyncio.Task | None = None
        self._dispatch_fn: DispatchFn | None = None
        self._consecutive_ack_failures: int = 0
        self._consecutive_dispatch_failures: int = 0

    @property
    def consumer_id(self) -> str:
        return self._consumer_id

    @property
    def group_name(self) -> str:
        return self._group_name

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, dispatch_fn: DispatchFn) -> None:
        """Connect to Redis, create consumer groups, start the consumer loop."""
        self._dispatch_fn = dispatch_fn
        self._publish_client = aioredis.from_url(
            self._redis_url, decode_responses=True
        )
        self._consumer_client = aioredis.from_url(
            self._redis_url, decode_responses=True
        )

        # Shared monitoring group — created once, id=$ so it tracks new msgs.
        await self._create_group(self._publish_client, GROUP_NAME)
        # Per-process group — broadcast: this process receives all events.
        await self._create_group(self._publish_client, self._group_name)

        self._task = asyncio.create_task(self._consumer_loop(), name="streams_consumer")
        logger.info(
            "streams_bridge_started",
            extra={
                "consumer_id": self._consumer_id,
                "group": self._group_name,
                "stream": STREAM_KEY,
            },
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        for client in (self._publish_client, self._consumer_client):
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    logger.debug("streams_client_close_error", exc_info=True)
        self._publish_client = None
        self._consumer_client = None
        logger.info("streams_bridge_stopped")

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(
        self,
        channel: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Write event to Redis Stream. Returns the assigned per-channel seq."""
        if self._publish_client is None:
            raise RuntimeError("RedisStreamsBridge not started")

        # Atomically assign the next sequence number for this channel.
        seq: int = await self._publish_client.hincrby(SEQ_HASH, channel, 1)

        minid = f"{int(time.time() * 1000) - STREAM_RETENTION_MS}-0"
        await self._publish_client.xadd(
            STREAM_KEY,
            {
                "channel": channel,
                "type": event_type,
                "payload": json.dumps(payload),
                "boot_epoch": self._boot_epoch,
                "seq": str(seq),
            },
            minid=minid,
            approximate=True,
        )
        return seq

    async def fetch_backlog(self, channel: str, since_seq: int) -> list[dict[str, Any]]:
        """Scan the stream and return entries for channel with seq > since_seq.

        Only returns entries written by this process's boot epoch so clients
        that reconnect after a server restart get an empty backfill (the epoch
        mismatch is signalled separately by the caller).
        """
        if self._publish_client is None:
            return []
        start_id = f"{max(0, int(time.time() * 1000) - STREAM_RETENTION_MS)}-0"
        entries: list[tuple[str, dict[str, str]]] = await self._publish_client.xrange(
            STREAM_KEY, start_id, "+", STREAM_MAXLEN
        )
        result: list[dict[str, Any]] = []
        for _entry_id, fields in entries:
            if fields.get("channel") != channel:
                continue
            if fields.get("boot_epoch") != self._boot_epoch:
                continue
            try:
                seq = int(fields["seq"])
            except (KeyError, ValueError):
                continue
            if seq > since_seq:
                try:
                    payload = json.loads(fields.get("payload", "{}"))
                except json.JSONDecodeError:
                    payload = {}
                result.append({
                    "channel": channel,
                    "type": fields["type"],
                    "payload": payload,
                    "seq": seq,
                })
        return result

    async def get_seq(self, channel: str) -> int:
        """Return the current sequence number for a channel (0 if none)."""
        if self._publish_client is None:
            return 0
        val = await self._publish_client.hget(SEQ_HASH, channel)
        return int(val) if val else 0

    # ------------------------------------------------------------------
    # Consumer loop
    # ------------------------------------------------------------------

    async def _consumer_loop(self) -> None:
        """Read from the per-process consumer group and call dispatch_fn."""
        backoff = self._INITIAL_BACKOFF
        while True:
            try:
                results = await self._consumer_client.xreadgroup(
                    self._group_name,
                    self._consumer_id,
                    {STREAM_KEY: ">"},
                    count=self._READ_COUNT,
                    block=self._BLOCK_MS,
                )
                backoff = self._INITIAL_BACKOFF

                if not results:
                    continue

                for _stream, entries in results:
                    for entry_id, fields in entries:
                        await self._handle_entry(entry_id, fields)

            except asyncio.CancelledError:
                return
            except aioredis.ResponseError as exc:
                logger.warning(
                    "streams_consumer_redis_error",
                    extra={"error": str(exc), "backoff_s": backoff},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._MAX_BACKOFF)
            except Exception:
                logger.exception(
                    "streams_consumer_unexpected_error",
                    extra={"backoff_s": backoff},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._MAX_BACKOFF)

    async def _handle_entry(self, entry_id: str, fields: dict[str, str]) -> None:
        try:
            channel = fields["channel"]
            event_type = fields["type"]
            payload = json.loads(fields["payload"])
            seq = int(fields["seq"])
        except (KeyError, json.JSONDecodeError, ValueError):
            logger.warning(
                "streams_bad_entry",
                extra={"entry_id": entry_id, "fields": sorted(fields.keys())},
            )
            await self._ack(entry_id)
            return

        if self._dispatch_fn is not None:
            try:
                await self._dispatch_fn(channel, event_type, seq, payload)
                self._consecutive_dispatch_failures = 0
            except Exception:
                self._consecutive_dispatch_failures += 1
                # Always log; escalate if dispatch failure is persistent. We
                # still ack: a poisoned entry would otherwise loop forever
                # and block fresh events. See docs/audits/error-handling-report.md §B2.
                if (
                    self._consecutive_dispatch_failures
                    >= self._ACK_FAILURE_ESCALATE_AT
                ):
                    logger.error(
                        "streams_dispatch_error_persistent",
                        extra={
                            "channel": channel,
                            "entry_id": entry_id,
                            "consecutive_failures": self._consecutive_dispatch_failures,
                        },
                        exc_info=True,
                    )
                else:
                    logger.exception(
                        "streams_dispatch_error",
                        extra={"channel": channel, "entry_id": entry_id},
                    )

        await self._ack(entry_id)

    async def _ack(self, entry_id: str) -> None:
        try:
            await self._consumer_client.xack(STREAM_KEY, self._group_name, entry_id)
            self._consecutive_ack_failures = 0
        except Exception:
            self._consecutive_ack_failures += 1
            # Ack failures cause Redis Streams to re-deliver to this consumer
            # on its next read, which means duplicate dispatch. Single failures
            # are usually transient (Redis connection blip); persistent
            # failures need ops attention because backlog grows unbounded.
            # See docs/audits/error-handling-report.md §B3.
            if self._consecutive_ack_failures >= self._ACK_FAILURE_ESCALATE_AT:
                logger.error(
                    "streams_ack_error_persistent",
                    extra={
                        "entry_id": entry_id,
                        "consecutive_failures": self._consecutive_ack_failures,
                    },
                    exc_info=True,
                )
                # Reset so we don't keep emitting the same alert until restart.
                self._consecutive_ack_failures = 0
            else:
                logger.warning(
                    "streams_ack_error",
                    extra={"entry_id": entry_id},
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _create_group(client: aioredis.Redis, group_name: str) -> None:
        """Create consumer group on STREAM_KEY. No-op if already exists."""
        try:
            await client.xgroup_create(STREAM_KEY, group_name, id="$", mkstream=True)
            logger.info("streams_group_created", extra={"group": group_name})
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
