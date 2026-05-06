"""OTel metric for Postgres connection health.

Exposes ``pg.idle_in_txn.max_age_seconds`` as an observable gauge — the
oldest ``idle in transaction`` session per role. The metric callback
reads from a process-local cache that the ``export_pg_idle_txn_metrics``
Celery beat task refreshes once a minute (matching the OTel reader
interval).

The pattern is deliberately split:

- Beat task → ``update_max_idle_in_txn_age(role, age_s)``
- OTel reader → callback → reads from the cache → emits Observations

This keeps the OTel callback fast and DB-free, so the metrics export
loop can never itself stall on a database round-trip.

When opentelemetry-sdk is not installed or no endpoint is configured,
``init()`` is a no-op and ``update_max_idle_in_txn_age`` simply caches
values that are never observed.
"""

from __future__ import annotations

import logging
import threading
from collections import namedtuple

_logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict[str, int] = {}
_initialized = False

# Local stand-in used when opentelemetry is not importable (e.g. local
# tests without the otel-sdk extra). Same field names as
# ``opentelemetry.metrics.Observation`` so call-site code is identical.
_LocalObservation = namedtuple("_LocalObservation", ["value", "attributes"])


def update_max_idle_in_txn_age(role: str, age_seconds: int) -> None:
    """Cache the latest oldest-idle-in-txn age for ``role``.

    Called from the beat-driven exporter task. Concurrency-safe via
    a process-local lock.
    """
    with _lock:
        _state[role] = max(0, int(age_seconds))


def reset_state() -> None:
    """Test-only: clear cached state so a test can assert on a fresh slate."""
    with _lock:
        _state.clear()


def _callback(_options):  # type: ignore[no-untyped-def]
    """OTel observable-gauge callback. Yields one Observation per role.

    No DB access here — only reads the snapshot the beat task left
    behind. ``_options`` is an ``opentelemetry.metrics.CallbackOptions``
    we don't currently consult.

    Falls back to a local namedtuple when the otel package is missing
    (e.g. in local unit tests) so callers can still introspect the
    cached state without the runtime dependency.
    """
    try:
        from opentelemetry.metrics import Observation  # type: ignore[import-not-found]
    except ImportError:
        Observation = _LocalObservation  # type: ignore[assignment, misc]

    with _lock:
        snapshot = dict(_state)

    observations: list = []
    for role, age in snapshot.items():
        observations.append(Observation(age, attributes={"usename": role}))
    return observations


def init() -> None:
    """Register the observable gauge with the global MeterProvider.

    Idempotent: subsequent calls are no-ops. Safe to call from worker
    process startup (``celery_app`` import) and from the beat task
    itself (which is what guarantees registration even when no metric
    has been emitted yet).
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    try:
        from opentelemetry import metrics
    except ImportError:
        _logger.debug("opentelemetry not available — pg_health metrics are no-ops")
        return

    meter = metrics.get_meter("pg_health", version="1.0")
    meter.create_observable_gauge(
        name="pg.idle_in_txn.max_age_seconds",
        description=(
            "Max age in seconds of any 'idle in transaction' Postgres session, "
            "by role. Alert when sustained >30s — see Phase 1 of the long-txn fix."
        ),
        unit="s",
        callbacks=[_callback],
    )


def collect_observations_for_test() -> list:
    """Test-only: return what the OTel callback would emit right now."""
    return list(_callback(None))


# Public surface
__all__ = [
    "collect_observations_for_test",
    "init",
    "reset_state",
    "update_max_idle_in_txn_age",
]
