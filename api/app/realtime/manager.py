"""Channel registry, sequence tracking, and local fan-out.

Publishing flow (with Redis Streams bridge wired in):
  publish() → RedisStreamsBridge.publish() (XADD + HINCRBY)
  → consumer loop reads entry → _dispatch_local() → WS/SSE connections

Without bridge (unit tests / no Redis):
  publish() → _dispatch_local() directly (in-memory seq counter fallback).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, Protocol

from .models import MAX_CHANNELS_PER_CONNECTION, RealtimeEvent, is_valid_channel

if TYPE_CHECKING:
    from .streams import RedisStreamsBridge

logger = logging.getLogger(__name__)

REALTIME_DEBUG = os.getenv("REALTIME_DEBUG", "").lower() in ("1", "true", "yes")

SSE_QUEUE_MAX = 200
WS_SEND_TIMEOUT_S = 2.0


class Connection(Protocol):
    """Abstract connection that can receive JSON events."""

    async def send_event(self, data: str) -> None: ...

    @property
    def id(self) -> str: ...


class WSConnection:
    """Wraps a Starlette WebSocket for the manager."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._id = f"ws-{id(ws)}"

    @property
    def id(self) -> str:
        return self._id

    async def send_event(self, data: str) -> None:
        await asyncio.wait_for(self._ws.send_text(data), timeout=WS_SEND_TIMEOUT_S)


class SSEConnection:
    """Queue-based connection for SSE streaming."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SSE_QUEUE_MAX)
        self._id = f"sse-{id(self)}"

    @property
    def id(self) -> str:
        return self._id

    @property
    def queue(self) -> asyncio.Queue[str]:
        return self._queue

    async def send_event(self, data: str) -> None:
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            raise OverflowError("SSE queue full")


OnFirstSubscriberCallback = Callable[[str], Coroutine[Any, Any, None]]


class RealtimeManager:
    """Channel registry and local fan-out for one API process.

    When a ``RedisStreamsBridge`` is wired in via ``set_streams_bridge()``,
    ``publish()`` writes to the Redis Stream and the bridge's consumer loop
    calls ``_dispatch_local()`` to reach local connections.  Without a bridge
    the call goes directly to ``_dispatch_local()`` (used in unit tests).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[Connection]] = {}
        # Fallback seq counter — used only when no bridge is wired (tests).
        self._seq: dict[str, int] = {}
        self._conn_channels: dict[str, set[str]] = {}  # conn.id -> channels
        self._boot_epoch: str = str(uuid.uuid4())
        self._on_first_subscriber: OnFirstSubscriberCallback | None = None
        self._bridge: RedisStreamsBridge | None = None

        self._publish_count: int = 0
        self._error_count: int = 0

    @property
    def boot_epoch(self) -> str:
        return self._boot_epoch

    def set_streams_bridge(self, bridge: RedisStreamsBridge) -> None:
        """Wire in the Redis Streams bridge for multi-process fanout."""
        self._bridge = bridge

    def set_on_first_subscriber(self, callback: OnFirstSubscriberCallback) -> None:
        """Register callback invoked when a channel goes from 0 → 1 subscribers."""
        self._on_first_subscriber = callback

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, conn: Connection, channel: str) -> bool:
        """Subscribe connection to a channel. Returns False on validation error."""
        if not is_valid_channel(channel):
            logger.warning("realtime_invalid_channel", extra={"channel": channel})
            return False

        conn_channels = self._conn_channels.setdefault(conn.id, set())
        if len(conn_channels) >= MAX_CHANNELS_PER_CONNECTION and channel not in conn_channels:
            logger.warning(
                "realtime_channel_limit",
                extra={"conn": conn.id, "limit": MAX_CHANNELS_PER_CONNECTION},
            )
            return False

        subs = self._subscribers.setdefault(channel, set())
        was_empty = len(subs) == 0
        subs.add(conn)
        conn_channels.add(channel)

        if channel not in self._seq:
            self._seq[channel] = 0

        if was_empty and self._on_first_subscriber is not None:
            asyncio.ensure_future(self._safe_first_subscriber_callback(channel))

        if REALTIME_DEBUG:
            logger.debug(
                "realtime_subscribe",
                extra={"conn": conn.id, "channel": channel, "subs": len(subs)},
            )

        return True

    async def _safe_first_subscriber_callback(self, channel: str) -> None:
        try:
            if self._on_first_subscriber:
                await self._on_first_subscriber(channel)
        except Exception:
            logger.exception("realtime_first_subscriber_error", extra={"channel": channel})

    def unsubscribe(self, conn: Connection, channel: str) -> None:
        subs = self._subscribers.get(channel)
        if subs:
            subs.discard(conn)
            if not subs:
                del self._subscribers[channel]

        conn_channels = self._conn_channels.get(conn.id)
        if conn_channels:
            conn_channels.discard(channel)

    def disconnect(self, conn: Connection) -> None:
        channels = self._conn_channels.pop(conn.id, set())
        for ch in channels:
            subs = self._subscribers.get(ch)
            if subs:
                subs.discard(conn)
                if not subs:
                    del self._subscribers[ch]

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(
        self,
        channel: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Publish an event to the channel.

        With bridge: writes to Redis Stream; the consumer loop delivers to
        local subscribers asynchronously.
        Without bridge: dispatches in-process immediately (unit-test path).

        Returns the sequence number assigned to this event.
        """
        self._publish_count += 1

        if self._bridge is not None:
            return await self._bridge.publish(channel, event_type, payload)

        # In-process fallback (no Redis, used in unit tests).
        seq = self._seq.get(channel, 0) + 1
        self._seq[channel] = seq
        await self._dispatch_local(channel, event_type, seq, payload)
        return seq

    async def _dispatch_local(
        self,
        channel: str,
        event_type: str,
        seq: int,
        payload: dict[str, Any],
    ) -> None:
        """Fan out a pre-sequenced event to all local WS/SSE connections.

        Called either from the fallback publish path (no bridge) or from the
        bridge's consumer loop after reading from Redis Streams.  The boot
        epoch is always this process's own value so clients detect restarts.
        """
        event = RealtimeEvent(
            type=event_type,
            channel=channel,
            seq=seq,
            payload=payload,
            boot_epoch=self._boot_epoch,
        )
        data = json.dumps(event.to_dict())

        subs = self._subscribers.get(channel)
        if not subs:
            return

        dead: list[Connection] = []
        for conn in list(subs):
            try:
                await conn.send_event(data)
            except OverflowError:
                logger.info(
                    "realtime_sse_overflow",
                    extra={"conn": conn.id, "channel": channel},
                )
                dead.append(conn)
            except TimeoutError:
                logger.info(
                    "realtime_ws_timeout",
                    extra={"conn": conn.id, "channel": channel},
                )
                dead.append(conn)
                self._error_count += 1
            except Exception:
                logger.warning(
                    "realtime_send_failed",
                    extra={"conn": conn.id, "channel": channel},
                    exc_info=True,
                )
                dead.append(conn)
                self._error_count += 1

        for conn in dead:
            self.disconnect(conn)

        if REALTIME_DEBUG:
            logger.debug(
                "realtime_publish",
                extra={
                    "channel": channel,
                    "type": event_type,
                    "seq": seq,
                    "recipients": len(subs) - len(dead),
                    "dropped": len(dead),
                },
            )

    # ------------------------------------------------------------------
    # Status / metrics
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        all_conns: set[str] = set()
        channel_counts: dict[str, int] = {}
        for ch, subs in self._subscribers.items():
            channel_counts[ch] = len(subs)
            for s in subs:
                all_conns.add(s.id)

        result: dict[str, Any] = {
            "boot_epoch": self._boot_epoch,
            "total_connections": len(all_conns),
            "total_channels": len(self._subscribers),
            "channels": channel_counts,
            "publish_count": self._publish_count,
            "error_count": self._error_count,
        }

        if self._bridge is not None:
            result["streams_consumer_id"] = self._bridge.consumer_id
            result["streams_group"] = self._bridge.group_name

        return result

    async def fetch_backlog(self, channel: str, since_seq: int) -> list[dict[str, Any]]:
        """Return stream entries for channel with seq > since_seq via the bridge.

        Returns empty list if no bridge is wired (unit-test / no-Redis path).
        """
        if self._bridge is not None:
            return await self._bridge.fetch_backlog(channel, since_seq)
        return []

    def has_subscribers(self, channel: str) -> bool:
        return bool(self._subscribers.get(channel))

    def active_channels(self) -> set[str]:
        return {ch for ch, subs in self._subscribers.items() if subs}


# Singleton instance — import this in other modules
realtime_manager = RealtimeManager()
