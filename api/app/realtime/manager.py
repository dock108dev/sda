"""In-memory channel registry, sequence tracking, and fan-out.

Single-instance design. Upgradeable to Redis pub/sub later by replacing
the publish() method with a Redis PUBLISH + subscriber relay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Coroutine, Protocol

from .models import MAX_CHANNELS_PER_CONNECTION, RealtimeEvent, is_valid_channel

logger = logging.getLogger(__name__)

REALTIME_DEBUG = os.getenv("REALTIME_DEBUG", "").lower() in ("1", "true", "yes")

# Per-SSE-connection queue depth before disconnect
SSE_QUEUE_MAX = 200

# WS send timeout — drop connection if send takes longer
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


# Type for the on_first_subscriber callback
OnFirstSubscriberCallback = Callable[[str], Coroutine[Any, Any, None]]


class RealtimeManager:
    """In-memory pub/sub manager.

    Thread-safe via asyncio (single event loop).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[Connection]] = {}
        self._seq: dict[str, int] = {}
        self._conn_channels: dict[str, set[str]] = {}  # conn.id -> channels
        self._boot_epoch: int = int(time.time())
        self._on_first_subscriber: OnFirstSubscriberCallback | None = None

        # Metrics
        self._publish_count: int = 0
        self._error_count: int = 0

    @property
    def boot_epoch(self) -> int:
        return self._boot_epoch

    def set_on_first_subscriber(self, callback: OnFirstSubscriberCallback) -> None:
        """Register callback invoked when a channel goes from 0 -> 1 subscribers."""
        self._on_first_subscriber = callback

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, conn: Connection, channel: str) -> bool:
        """Subscribe connection to a channel. Returns False on validation error."""
        if not is_valid_channel(channel):
            logger.warning("realtime_invalid_channel", extra={"channel": channel})
            return False

        # Enforce per-connection channel limit
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

        # Initialise seq counter for new channels
        if channel not in self._seq:
            self._seq[channel] = 0

        # Fire catch-up callback when channel goes from 0 -> 1 subscribers
        if was_empty and self._on_first_subscriber is not None:
            asyncio.ensure_future(self._safe_first_subscriber_callback(channel))

        if REALTIME_DEBUG:
            logger.debug(
                "realtime_subscribe",
                extra={"conn": conn.id, "channel": channel, "subs": len(subs)},
            )

        return True

    async def _safe_first_subscriber_callback(self, channel: str) -> None:
        """Safely invoke the first-subscriber callback."""
        try:
            if self._on_first_subscriber:
                await self._on_first_subscriber(channel)
        except Exception:
            logger.exception("realtime_first_subscriber_error", extra={"channel": channel})

    def unsubscribe(self, conn: Connection, channel: str) -> None:
        """Remove connection from a channel."""
        subs = self._subscribers.get(channel)
        if subs:
            subs.discard(conn)
            if not subs:
                del self._subscribers[channel]

        conn_channels = self._conn_channels.get(conn.id)
        if conn_channels:
            conn_channels.discard(channel)

    def disconnect(self, conn: Connection) -> None:
        """Remove connection from all channels."""
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
        """Publish an event to all subscribers of a channel.

        Returns the sequence number assigned to this event.
        Non-blocking: slow/broken subscribers are dropped.
        """
        seq = self._seq.get(channel, 0) + 1
        self._seq[channel] = seq
        self._publish_count += 1

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
            return seq

        dead: list[Connection] = []
        for conn in subs:
            try:
                await conn.send_event(data)
            except OverflowError:
                # SSE queue full -> disconnect
                logger.info("realtime_sse_overflow", extra={"conn": conn.id, "channel": channel})
                dead.append(conn)
            except asyncio.TimeoutError:
                # WS send timed out -> disconnect
                logger.info("realtime_ws_timeout", extra={"conn": conn.id, "channel": channel})
                dead.append(conn)
                self._error_count += 1
            except Exception:
                # WS send failed -> disconnect
                logger.debug("realtime_send_failed", extra={"conn": conn.id, "channel": channel})
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

        return seq

    # ------------------------------------------------------------------
    # Status / metrics
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return connection counts and channel info."""
        all_conns: set[str] = set()
        channel_counts: dict[str, int] = {}
        for ch, subs in self._subscribers.items():
            channel_counts[ch] = len(subs)
            for s in subs:
                all_conns.add(s.id)

        return {
            "boot_epoch": self._boot_epoch,
            "total_connections": len(all_conns),
            "total_channels": len(self._subscribers),
            "channels": channel_counts,
            "publish_count": self._publish_count,
            "error_count": self._error_count,
        }

    def has_subscribers(self, channel: str) -> bool:
        """Check if a channel has any active subscribers."""
        return bool(self._subscribers.get(channel))

    def active_channels(self) -> set[str]:
        """Return set of channels with at least one subscriber."""
        return {ch for ch, subs in self._subscribers.items() if subs}


# Singleton instance — import this in other modules
realtime_manager = RealtimeManager()
