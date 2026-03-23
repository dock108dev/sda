"""Helpers for recording phase-level job runs."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from contextlib import contextmanager
from typing import Any

from app.utils.datetime_utils import now_utc as _now_utc
from sqlalchemy import asc

from ..db import db_models, get_session
from ..logging import logger


def start_job_run(
    phase: str,
    leagues: Iterable[str],
    celery_task_id: str | None = None,
) -> int:
    """Create a job run record and return its ID."""
    leagues_list = [league.upper() for league in leagues]
    with get_session() as session:
        run = db_models.SportsJobRun(
            phase=phase,
            leagues=leagues_list,
            status="running",
            started_at=_now_utc(),
            celery_task_id=celery_task_id,
        )
        session.add(run)
        session.flush()
        run_id = int(run.id)
        logger.info("job_run_started", run_id=run_id, phase=phase, leagues=leagues_list)
        return run_id


def complete_job_run(
    run_id: int,
    status: str,
    error_summary: str | None = None,
    summary_data: dict[str, Any] | None = None,
) -> None:
    """Finalize a job run record with status + duration."""
    with get_session() as session:
        run = session.get(db_models.SportsJobRun, run_id)
        if not run:
            logger.error("job_run_missing", run_id=run_id)
            return
        if run.status == "canceled":
            # Cancellation is terminal. Do not let normal task finalization
            # overwrite a user-initiated cancel with success/error.
            logger.info(
                "job_run_completion_skipped_canceled",
                run_id=run_id,
                attempted_status=status,
            )
            return
        finished_at = _now_utc()
        run.status = status
        run.finished_at = finished_at
        run.duration_seconds = (finished_at - run.started_at).total_seconds()
        run.error_summary = error_summary
        if summary_data is not None:
            run.summary_data = summary_data
        session.flush()
        logger.info("job_run_completed", run_id=run_id, phase=run.phase, status=status)


def queue_job_run(
    phase: str,
    leagues: Iterable[str],
    celery_task_id: str,
) -> int:
    """Create a job run record with status='queued' and return its ID.

    Used at dispatch time so the run is visible in the UI before the
    worker picks it up.  ``started_at`` is set to now as a placeholder
    (the column is NOT NULL); ``activate_queued_job_run`` overwrites it
    with the real start time.
    """
    leagues_list = [league.upper() for league in leagues]
    with get_session() as session:
        run = db_models.SportsJobRun(
            phase=phase,
            leagues=leagues_list,
            status="queued",
            started_at=_now_utc(),  # placeholder — overwritten on activation
            celery_task_id=celery_task_id,
        )
        session.add(run)
        session.flush()
        run_id = int(run.id)
        logger.info(
            "job_run_queued",
            run_id=run_id,
            phase=phase,
            leagues=leagues_list,
            celery_task_id=celery_task_id,
        )
        return run_id


def activate_queued_job_run(job_run_id: int) -> int:
    """Transition a queued job run to 'running' and set the real start time.

    * If the record is ``"queued"``: transition to ``"running"``.
    * If already ``"running"`` (Celery retry): no-op, return same ID.
    * If missing or unexpected status (e.g. canceled before pickup):
      fall back to ``start_job_run()`` so the task is still tracked.
    """
    with get_session() as session:
        run = session.get(db_models.SportsJobRun, job_run_id)
        if not run:
            logger.warning(
                "activate_queued_missing",
                job_run_id=job_run_id,
                fallback="start_job_run",
            )
            return start_job_run("social", [])

        if run.status == "running":
            # Celery retry — already activated
            return int(run.id)

        if run.status != "queued":
            # If canceled before pickup, abort this task invocation.
            if run.status == "canceled":
                logger.info(
                    "activate_queued_canceled",
                    job_run_id=job_run_id,
                    phase=run.phase,
                )
                raise RuntimeError(f"Job run {job_run_id} was canceled before pickup")

            # Otherwise changed before worker pickup (unexpected)
            logger.warning(
                "activate_queued_unexpected_status",
                job_run_id=job_run_id,
                status=run.status,
                fallback="start_job_run",
            )
            return start_job_run(run.phase, list(run.leagues or []))

        run.status = "running"
        run.started_at = _now_utc()
        session.flush()
        logger.info("job_run_activated", run_id=job_run_id)
        return int(run.id)


def enforce_social_queue_limit(max_size: int = 10) -> list[int]:
    """Evict oldest queued social tasks when the queue is at or above *max_size*.

    For each evicted record the corresponding Celery task is revoked and
    the DB status is set to ``"canceled"``.

    Returns the list of evicted run IDs (empty if no eviction needed).
    """
    from ..celery_app import app as celery_app

    evicted_ids: list[int] = []
    with get_session() as session:
        queued = (
            session.query(db_models.SportsJobRun)
            .filter(
                db_models.SportsJobRun.phase == "social",
                db_models.SportsJobRun.status == "queued",
            )
            .order_by(asc(db_models.SportsJobRun.created_at))
            .all()
        )

        if len(queued) < max_size:
            return evicted_ids

        # Evict oldest entries so we end up with (max_size - 1) queued,
        # leaving room for the new dispatch.
        to_evict = len(queued) - max_size + 1
        for run in queued[:to_evict]:
            if run.celery_task_id:
                try:
                    celery_app.control.revoke(run.celery_task_id)
                except Exception as exc:
                    logger.warning(
                        "evict_revoke_failed",
                        run_id=run.id,
                        celery_task_id=run.celery_task_id,
                        error=str(exc),
                    )
            run.status = "canceled"
            run.finished_at = _now_utc()
            run.duration_seconds = 0.0
            run.error_summary = "Evicted: social queue exceeded max limit"
            evicted_ids.append(int(run.id))

        session.flush()
        if evicted_ids:
            logger.info(
                "social_queue_evicted",
                evicted=evicted_ids,
                max_size=max_size,
            )
    return evicted_ids


class JobRunTracker:
    """Mutable tracker for accumulating summary data during a job run."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self.summary_data: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Set a summary data key."""
        self.summary_data[key] = value

    def increment(self, key: str, amount: int = 1) -> None:
        """Increment a numeric summary data key."""
        self.summary_data[key] = self.summary_data.get(key, 0) + amount


def _get_current_celery_task_id() -> str | None:
    """Return the current Celery task ID if running inside a Celery worker."""
    try:
        from celery import current_task

        if current_task and current_task.request and current_task.request.id:
            return str(current_task.request.id)
    except Exception:
        pass
    return None


@contextmanager
def track_job_run(
    phase: str,
    leagues: Iterable[str] = (),
    job_run_id: int | None = None,
) -> Generator[JobRunTracker, None, None]:
    """Context manager that creates a job run on enter and finalizes on exit.

    If *job_run_id* is provided (pre-queued dispatch), the existing record
    is activated instead of creating a new one.

    Usage:
        with track_job_run("poll_live_pbp", ["NBA", "NHL", "MLB", "NFL", "NCAAB"]) as tracker:
            # ... do work ...
            tracker.set("games_polled", 5)
            tracker.set("api_calls", 12)

    On normal exit: status="success", summary_data from tracker.
    On exception: status="error", error_summary from exception.
    """
    if job_run_id is not None:
        run_id = activate_queued_job_run(job_run_id)
    else:
        celery_task_id = _get_current_celery_task_id()
        run_id = start_job_run(phase, leagues, celery_task_id=celery_task_id)
    tracker = JobRunTracker(run_id)

    try:
        yield tracker
    except Exception as exc:
        complete_job_run(
            run_id,
            status="error",
            error_summary=str(exc)[:500],
            summary_data=tracker.summary_data or None,
        )
        raise
    else:
        complete_job_run(
            run_id,
            status="success",
            summary_data=tracker.summary_data or None,
        )
