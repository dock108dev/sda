"""Central registry for in-process circuit breaker state.

Maintains open/closed state, trip count, and last trip reason for every
named breaker registered in this process.  Thread-safe for synchronous
callers (live_odds_redis, fairbet_runtime).

Trip events are queued in a thread-safe buffer and drained to the DB by
the background flush task started in the FastAPI lifespan.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class BreakerState:
    name: str
    is_open: bool = False
    trip_count: int = 0
    last_trip_reason: str | None = None
    last_trip_at: datetime | None = None
    last_reset_at: datetime | None = None


@dataclass
class _PendingTripEvent:
    breaker_name: str
    reason: str
    tripped_at: datetime


class CircuitBreakerRegistry:
    """Singleton registry — use the module-level ``registry`` instance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._breakers: dict[str, BreakerState] = {}
        # Thread-safe queue drained by the async background flusher.
        self.pending_events: queue.SimpleQueue[_PendingTripEvent] = queue.SimpleQueue()

    def register(self, name: str) -> None:
        """Ensure a breaker entry exists; idempotent."""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = BreakerState(name=name)

    def record_trip(self, name: str, reason: str) -> None:
        """Record a trip event; called from sync circuit breaker code."""
        now = datetime.now(UTC)
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = BreakerState(name=name)
            state = self._breakers[name]
            state.is_open = True
            state.trip_count += 1
            state.last_trip_reason = reason
            state.last_trip_at = now
        self.pending_events.put_nowait(_PendingTripEvent(name, reason, now))

    def record_reset(self, name: str) -> None:
        """Record a reset; called when the underlying call succeeds again."""
        now = datetime.now(UTC)
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = BreakerState(name=name)
            state = self._breakers[name]
            state.is_open = False
            state.last_reset_at = now

    def get_all(self) -> list[BreakerState]:
        with self._lock:
            return list(self._breakers.values())

    def get(self, name: str) -> BreakerState | None:
        with self._lock:
            return self._breakers.get(name)

    def drain_pending(self) -> list[_PendingTripEvent]:
        """Drain all queued trip events (called by the async DB flusher)."""
        events: list[_PendingTripEvent] = []
        while True:
            try:
                events.append(self.pending_events.get_nowait())
            except queue.Empty:
                break
        return events


# Module-level singleton used across the codebase.
registry = CircuitBreakerRegistry()
