"""Operational metrics for worker fallbacks and degraded paths."""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

_initialized = False
_instruments: dict[str, object] = {}


class _NoopCounter:
    def add(self, *args, **kwargs) -> None:  # noqa: ANN002
        pass


_NOOP = _NoopCounter()


def _counter(name: str, description: str) -> object:
    global _initialized, _instruments
    if not _initialized:
        _initialized = True
        try:
            from opentelemetry import metrics

            meter = metrics.get_meter("sports_scraper.operational", version="1.0")
            _instruments = {
                "polling_lock_skipped": meter.create_counter(
                    name="scraper.polling.lock_skipped",
                    description="Polling task executions skipped because a Redis lock was unavailable",
                ),
                "polling_degraded": meter.create_counter(
                    name="scraper.polling.degraded",
                    description="Polling task executions completed with suppressed errors",
                ),
                "polling_missing_external_id": meter.create_counter(
                    name="scraper.polling.missing_external_id",
                    description="Polling attempts skipped because a game was missing provider identifiers",
                ),
                "polling_boxscore_soft_failure": meter.create_counter(
                    name="scraper.polling.boxscore_soft_failure",
                    description="Boxscore polling failures converted to soft per-game failures",
                ),
                "job_partial_success": meter.create_counter(
                    name="scraper.job.partial_success",
                    description="Worker jobs completed in a degraded or partial-success state",
                ),
                "flow_generation_transient_error": meter.create_counter(
                    name="scraper.flow_generation.transient_error",
                    description="Scheduled flow-generation transient upstream failures handed to Celery retry",
                ),
                "lock_force_release": meter.create_counter(
                    name="scraper.lock.force_release",
                    description="Manual or startup force-release operations against Redis lock keys",
                ),
            }
        except ImportError:
            _logger.debug("opentelemetry not available; operational metrics are no-ops")
    return _instruments.get(name, _NOOP)


def record_polling_lock_skipped(*, task: str, reason: str) -> None:
    _counter("polling_lock_skipped", "").add(1, attributes={"task": task, "reason": reason})


def record_polling_degraded(*, task: str, suppressed_errors: int) -> None:
    _counter("polling_degraded", "").add(
        1,
        attributes={"task": task, "suppressed_errors": str(suppressed_errors)},
    )


def record_missing_external_id(*, league: str, field: str, phase: str) -> None:
    _counter("polling_missing_external_id", "").add(
        1,
        attributes={"league": league, "field": field, "phase": phase},
    )


def record_boxscore_soft_failure(*, league: str, error_type: str) -> None:
    _counter("polling_boxscore_soft_failure", "").add(
        1,
        attributes={"league": league, "error_type": error_type},
    )


def record_job_partial_success(*, phase: str, status: str) -> None:
    _counter("job_partial_success", "").add(1, attributes={"phase": phase, "status": status})


def record_flow_generation_transient_error(*, league: str, status_code: str) -> None:
    _counter("flow_generation_transient_error", "").add(
        1,
        attributes={"league": league, "status_code": status_code},
    )


def record_lock_force_release(*, operation: str, deleted: bool) -> None:
    _counter("lock_force_release", "").add(
        1,
        attributes={"operation": operation, "deleted": str(deleted).lower()},
    )
