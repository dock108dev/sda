"""In-memory simulation result cache with TTL policies.

Prevents repeated expensive simulations by caching results keyed on
simulation parameters. Pregame simulations are cached indefinitely
(until eviction), while live simulations expire after a short TTL.

Usage::

    cache = SimulationCache()
    key = cache.generate_cache_key(params)
    cached = cache.get(key)
    if cached is None:
        result = run_expensive_simulation(...)
        cache.set(key, result, mode="pregame")
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# TTL in seconds by simulation mode.
_TTL_POLICY: dict[str, float | None] = {
    "pregame": None,  # indefinite
    "live": 30.0,
}

# Maximum cache entries before LRU eviction.
_MAX_ENTRIES = 500


class SimulationCache:
    """Thread-safe in-memory cache for simulation results."""

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._store: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def generate_cache_key(self, params: dict[str, Any]) -> str:
        """Generate a deterministic cache key from simulation parameters.

        Args:
            params: Dict of simulation parameters (sport, teams, iterations, etc).

        Returns:
            Hex digest string suitable as a cache key.
        """
        serialized = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a cached result if it exists and hasn't expired.

        Args:
            key: Cache key from ``generate_cache_key``.

        Returns:
            Cached result dict or ``None`` if miss/expired.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            if entry.ttl is not None and (time.monotonic() - entry.created_at) > entry.ttl:
                del self._store[key]
                return None

            entry.last_accessed = time.monotonic()
            return entry.value

    def set(
        self,
        key: str,
        value: dict[str, Any],
        mode: str = "pregame",
    ) -> None:
        """Store a simulation result in the cache.

        Args:
            key: Cache key.
            value: Simulation result dict to cache.
            mode: ``"pregame"`` (indefinite) or ``"live"`` (30s TTL).
        """
        ttl = _TTL_POLICY.get(mode)

        with self._lock:
            if len(self._store) >= self._max_entries and key not in self._store:
                self._evict_one()

            self._store[key] = _CacheEntry(
                value=value,
                ttl=ttl,
                created_at=time.monotonic(),
                last_accessed=time.monotonic(),
            )

    def invalidate(self, key: str) -> bool:
        """Remove a specific entry from the cache.

        Returns:
            ``True`` if the entry existed and was removed.
        """
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        """Current number of entries in the cache."""
        with self._lock:
            return len(self._store)

    def _evict_one(self) -> None:
        """Evict the least recently accessed entry. Caller must hold ``_lock``."""
        if not self._store:
            return
        oldest_key = min(
            self._store, key=lambda k: self._store[k].last_accessed,
        )
        del self._store[oldest_key]


class _CacheEntry:
    """Internal cache entry with metadata."""

    __slots__ = ("value", "ttl", "created_at", "last_accessed")

    def __init__(
        self,
        value: dict[str, Any],
        ttl: float | None,
        created_at: float,
        last_accessed: float,
    ) -> None:
        self.value = value
        self.ttl = ttl
        self.created_at = created_at
        self.last_accessed = last_accessed
