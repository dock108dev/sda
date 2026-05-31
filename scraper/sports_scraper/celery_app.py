"""Celery app configuration for sports scraper."""

from __future__ import annotations

import celery as _celery_mod
import redis as _redis
from celery import Celery, signals
from celery.schedules import crontab

from .config import settings
from .db import db_models, get_session
from .logging import logger
from .telemetry import init_telemetry
from .utils.datetime_utils import now_utc

# Must be called before Celery app creation so CeleryInstrumentor hooks in.
# No-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
init_telemetry(environment=settings.environment)

HOLD_KEY = "sports:tasks_held"


def _is_held() -> bool:
    """Check whether the admin has held all scheduled task dispatch.

    Fails closed for scheduled tasks: if Redis is unreachable, treat the
    scheduler as held so maintenance guardrails cannot be bypassed silently.
    """
    try:
        r = _redis.from_url(settings.redis_url, decode_responses=True)
        return r.get(HOLD_KEY) == "1"
    except Exception:
        logger.error("hold_check_redis_unavailable_failing_closed", exc_info=True)
        return True


# Canonical queue names — import these instead of using string literals
DEFAULT_QUEUE = "sports-scraper"

celery_config = {
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "timezone": "UTC",
    "enable_utc": True,
    "task_track_started": True,
    "worker_prefetch_multiplier": 1,
    "task_time_limit": 43200,  # 12 hours hard limit
    "task_soft_time_limit": 42600,  # 11h 50m soft limit
    "task_default_queue": DEFAULT_QUEUE,
    "broker_transport_options": {
        "visibility_timeout": 86400,  # 24h — prevents re-delivery of long tasks
    },
}


def _mark_job_run_skipped(celery_task_id: str | None) -> None:
    """Mark any SportsJobRun for this task as skipped so it doesn't stay queued."""
    if not celery_task_id:
        return
    try:
        from .db import db_models, get_session
        from .utils.datetime_utils import now_utc

        with get_session() as session:
            run = (
                session.query(db_models.SportsJobRun)
                .filter(
                    db_models.SportsJobRun.celery_task_id == celery_task_id,
                    db_models.SportsJobRun.status == "queued",
                )
                .first()
            )
            if run:
                run.status = "skipped"
                run.finished_at = now_utc()
                session.commit()
    except Exception:
        logger.warning("held_task_job_run_cleanup_failed", exc_info=True)


class _HoldAwareTask(_celery_mod.Task):
    """Task base class that skips execution when the admin hold is active.

    Beat-scheduled tasks are blocked. Manual triggers (with
    ``headers={"manual_trigger": True}``) bypass the hold.
    """

    def __call__(self, *args, **kwargs):
        if _is_held():
            headers = getattr(self.request, "headers", None) or {}
            if headers.get("manual_trigger") not in (True, "True", "true", 1, "1"):
                logger.info("task_held_skipping", task=self.name, task_id=self.request.id)
                # Clean up any SportsJobRun that was created for this task
                # so it doesn't sit in "queued" forever.
                _mark_job_run_skipped(self.request.id)
                return {"skipped": True, "reason": "held"}
        return super().__call__(*args, **kwargs)


app = Celery(
    "sports-data-scraper",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["sports_scraper.jobs.polling_tasks", "sports_scraper.jobs.scrape_tasks"],
)
# Set the default Task class for ALL tasks including @shared_task.
# task_cls in the constructor only applies to @app.task, not @shared_task.
app.Task = _HoldAwareTask
app.conf.update(**celery_config)
app.conf.task_acks_late = True
app.conf.task_routes = {
    "poll_live_pbp": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "poll_game_calendars": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
}
_beat_schedule = {
    "calendar-game-stubs-every-15m": {
        "task": "poll_game_calendars",
        "schedule": crontab(minute="*/15"),
        "options": {
            "queue": DEFAULT_QUEUE,
            "routing_key": DEFAULT_QUEUE,
            "expires": 840,
        },
    },
    "catchup-pbp-stats-every-5m": {
        "task": "poll_live_pbp",
        "schedule": crontab(minute="*/5"),
        "options": {
            "queue": DEFAULT_QUEUE,
            "routing_key": DEFAULT_QUEUE,
            "expires": 270,
        },
    },
}

app.conf.beat_schedule = _beat_schedule

logger.info(
    "beat_schedule_loaded",
    environment=settings.environment,
    task_count=len(_beat_schedule),
)


def mark_stale_runs_interrupted():
    """
    Mark any runs that are stuck in 'running' status as 'interrupted'.

    Called on worker startup. If the worker just booted, any 'running' job is
    orphaned — the previous worker process that owned it is gone. No time
    threshold is needed; every running record is stale by definition.

    Covers both SportsScrapeRun (ingestion runs) and SportsJobRun (task runs).
    """
    try:
        with get_session() as session:
            # --- SportsScrapeRun (ingestion runs) ---
            stale_runs = (
                session.query(db_models.SportsScrapeRun)
                .filter(
                    db_models.SportsScrapeRun.status.in_(["running", "pending"]),
                )
                .all()
            )

            if stale_runs:
                for run in stale_runs:
                    run.status = "interrupted"
                    run.finished_at = now_utc()
                    run.error_details = "Run was interrupted (worker restart or container killed)"
                    logger.warning(
                        "marking_stale_run_interrupted",
                        run_id=run.id,
                        started_at=str(run.started_at),
                    )

                session.commit()
                logger.info("stale_runs_marked_interrupted", count=len(stale_runs))

            # --- SportsJobRun (task runs) ---
            stale_job_runs = (
                session.query(db_models.SportsJobRun)
                .filter(
                    db_models.SportsJobRun.status.in_(["running", "queued"]),
                )
                .all()
            )

            if stale_job_runs:
                for jr in stale_job_runs:
                    jr.status = "interrupted"
                    jr.finished_at = now_utc()
                    jr.duration_seconds = (
                        (now_utc() - jr.started_at).total_seconds() if jr.started_at else None
                    )
                    jr.error_summary = "Task was interrupted (worker restart or container killed)"
                    logger.warning(
                        "marking_stale_job_run_interrupted",
                        run_id=jr.id,
                        phase=jr.phase,
                        started_at=str(jr.started_at),
                    )

                session.commit()
                logger.info("stale_job_runs_marked_interrupted", count=len(stale_job_runs))

            if not stale_runs and not stale_job_runs:
                logger.debug("no_stale_runs_found")
    except Exception as exc:
        logger.exception("failed_to_mark_stale_runs", error=str(exc))


# Hold enforcement is handled by _HoldAwareTask.__call__() (line 54).
# A previous task_prerun signal handler also raised Ignore() as a backup,
# but Celery logs signal-raised exceptions as ERROR level, creating noisy
# "Signal handler raised: Ignore()" messages every few seconds when hold
# is active.  The base class approach is sufficient and silent.


@signals.worker_ready.connect
def on_worker_ready(sender=None, **kwargs):
    """Called when Celery worker is ready. Clear stale locks and mark stale runs."""
    # sender is the worker Consumer object with .hostname attribute
    worker_name = getattr(sender, "hostname", None) or str(sender) if sender else "unknown"
    logger.info("celery_worker_ready", worker=worker_name)

    from .utils.redis_lock import clear_all_locks

    clear_all_locks()
    mark_stale_runs_interrupted()


@signals.worker_shutting_down.connect
def on_worker_shutting_down(sender=None, **kwargs):
    """Called when Celery worker is shutting down. Mark currently running tasks as interrupted."""
    # sender for this signal is a string (the worker hostname), not an object
    worker_name = str(sender) if sender else "unknown"
    logger.info("celery_worker_shutting_down", worker=worker_name)
    try:
        with get_session() as session:
            # --- SportsScrapeRun ---
            running_runs = (
                session.query(db_models.SportsScrapeRun)
                .filter(
                    db_models.SportsScrapeRun.status == "running",
                )
                .all()
            )

            for run in running_runs:
                run.status = "interrupted"
                run.finished_at = now_utc()
                run.error_details = "Run was interrupted (worker shutdown)"
                logger.warning(
                    "marking_run_interrupted_on_shutdown",
                    run_id=run.id,
                    started_at=str(run.started_at),
                )

            # --- SportsJobRun ---
            running_jobs = (
                session.query(db_models.SportsJobRun)
                .filter(
                    db_models.SportsJobRun.status.in_(["running", "queued"]),
                )
                .all()
            )

            for jr in running_jobs:
                jr.status = "interrupted"
                jr.finished_at = now_utc()
                jr.duration_seconds = (
                    (now_utc() - jr.started_at).total_seconds() if jr.started_at else None
                )
                jr.error_summary = "Task was interrupted (worker shutdown)"
                logger.warning(
                    "marking_job_run_interrupted_on_shutdown",
                    run_id=jr.id,
                    phase=jr.phase,
                    started_at=str(jr.started_at),
                )

            if running_runs or running_jobs:
                session.commit()
                logger.info(
                    "runs_marked_interrupted_on_shutdown",
                    scrape_runs=len(running_runs),
                    job_runs=len(running_jobs),
                )
    except Exception as exc:
        logger.exception("failed_to_mark_runs_on_shutdown", error=str(exc))
