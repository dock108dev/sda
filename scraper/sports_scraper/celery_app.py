"""Celery app configuration for sports scraper."""

from __future__ import annotations

import celery as _celery_mod
import redis as _redis
from celery import Celery, signals
from celery.schedules import crontab

from .config import settings
from .db import db_models, get_session
from .logging import logger
from .odds.metrics import init_odds_metrics
from .telemetry import init_telemetry
from .utils.datetime_utils import now_utc

# Must be called before Celery app creation so CeleryInstrumentor hooks in.
# No-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
init_telemetry(environment=settings.environment)
init_odds_metrics()

HOLD_KEY = "sports:tasks_held"


def _is_held() -> bool:
    """Check whether the admin has held all scheduled task dispatch.

    Fails open: if Redis is unreachable, allow tasks to proceed so
    ingestion is not silently blocked by transient infrastructure issues.
    """
    try:
        r = _redis.from_url(settings.redis_url, decode_responses=True)
        return r.get(HOLD_KEY) == "1"
    except Exception:
        logger.warning("hold_check_redis_unavailable — failing open (tasks proceed)", exc_info=True)
        return False

# Canonical queue names — import these instead of using string literals
DEFAULT_QUEUE = "sports-scraper"
SOCIAL_QUEUE = "social-scraper"
SOCIAL_BULK_QUEUE = "social-bulk"

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
    include=[
        "sports_scraper.jobs.tasks",
        "sports_scraper.jobs.session_health_task",
        "sports_scraper.jobs.grader_task",
    ],
)
# Set the default Task class for ALL tasks including @shared_task.
# task_cls in the constructor only applies to @app.task, not @shared_task.
app.Task = _HoldAwareTask
app.conf.update(**celery_config)
app.conf.task_acks_late = True
app.conf.task_routes = {
    "run_scrape_job": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # All X scraping on one queue — single Playwright session, no parallel X hits
    "collect_social_for_league": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    "collect_team_social": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    "map_social_to_games": {"queue": SOCIAL_BULK_QUEUE, "routing_key": SOCIAL_BULK_QUEUE},
    # Social error callback runs on main scraper queue (DB writes only)
    "handle_social_task_failure": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # Game-state-machine polling tasks
    "update_game_states": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "poll_live_pbp": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "sync_mainline_odds": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "sync_prop_odds": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "trigger_flow_for_game": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "sweep_missing_flows": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "run_daily_sweep": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # Game social collection every 30 min (odds-gated + staleness targeting)
    "collect_game_social": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    # Session health probe — runs on social-scraper to share the same IP/session
    "check_playwright_session_health": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    # MLB advanced stats (Statcast-derived, post-game)
    "ingest_mlb_advanced_stats": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # Live orchestrator + live odds polling
    "live_orchestrator_tick": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "poll_live_odds_mainline": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "poll_live_odds_props": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # Narrative quality grader (dispatched by API finalize_moments stage)
    "grade_flow_task": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
}
# Daily pipeline schedule (all times US Eastern / UTC during EST):
#
#   3:30 AM EST (08:30 UTC) — Sports ingestion (NBA → NHL → NCAAB → MLB sequentially)
#   4:00 AM EST (09:00 UTC) — Daily sweep (truth repair, backfill missing data)
#   7:00 AM EST (12:00 UTC) — Flow missing sweep (safety-net for hook misfire)
#
# Flow generation is event-driven: the ORM hook in api/app/db/hooks.py dispatches
# trigger_flow_for_game on every LIVE→FINAL transition. sweep_missing_flows is the
# daily fallback for any games the hook missed. The NX lock prevents double-dispatch.
#
# During EDT (March-November) all times shift 1 hour later.
#
# High-frequency polling (every 60s, staggered 15s apart via countdown):
#   :00  update_game_states  — disabled 3–11 AM EST (08–16 UTC)
#   :15  poll_live_pbp       — disabled 3–11 AM EST (08–16 UTC)
#   :30  sync_mainline_odds  — no quiet window
#   :45  sync_prop_odds      — no quiet window

# High-frequency polling — all fire every 60s, staggered by countdown offsets.
# Stats/PBP disabled 3–11 AM EST (hour 08–16 UTC excluded from crontab).
# High-frequency polling tasks use `expires` so stale tasks are dropped from the
# queue rather than piling up behind backfill/ingestion jobs. If a task hasn't
# been picked up within its interval, a fresh one will be dispatched by beat.
_polling_schedule = {
    "game-state-updater-every-60s": {
        "task": "update_game_states",
        "schedule": crontab(minute="*/1", hour="0-7,16-23"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 0, "expires": 55},
    },
    "live-pbp-poll-every-60s": {
        "task": "poll_live_pbp",
        "schedule": crontab(minute="*/1", hour="0-7,16-23"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 15, "expires": 55},
    },
    "mainline-odds-sync-every-3m": {
        "task": "sync_mainline_odds",
        "schedule": crontab(minute="*/3"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 30, "expires": 170},
    },
    "prop-odds-sync-every-15m": {
        "task": "sync_prop_odds",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 45, "expires": 870},
    },
    # Live orchestrator: runs every 5 seconds to dynamically dispatch
    # per-game polling at sport-appropriate cadences (PBP, stats, odds).
    # Only dispatches work when live games exist.
    "live-orchestrator-every-5s": {
        "task": "live_orchestrator_tick",
        "schedule": 5.0,  # Every 5 seconds (numeric = seconds interval)
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "expires": 4},
    },
    # Calendar poll: creates game stubs from league schedule APIs every 15 min.
    # Catches postseason matchups, schedule changes, and late-added games
    # that appear after the daily 3:30 AM ingestion.
    "calendar-poll-every-15m": {
        "task": "poll_game_calendars",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "expires": 840},
    },
}

# Scheduled tasks — active in all environments.
# Local deploys mirror production for testing purposes.
_scheduled_tasks = {
    "daily-sports-ingestion-330am-eastern": {
        "task": "run_scheduled_ingestion",
        "schedule": crontab(minute=30, hour=8),  # 3:30 AM EST = 08:30 UTC
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    # === Golf (DataGolf API) ===
    "golf-schedule-daily-7am-eastern": {
        "task": "golf_sync_schedule",
        "schedule": crontab(minute=0, hour=12),  # 7:00 AM EST = 12:00 UTC
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "golf-players-weekly-monday": {
        "task": "golf_sync_players",
        "schedule": crontab(minute=0, hour=12, day_of_week="monday"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "golf-field-every-6h": {
        "task": "golf_sync_field",
        "schedule": crontab(minute=0, hour="6,12,18,0"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "golf-odds-every-30m": {
        "task": "golf_sync_odds",
        "schedule": crontab(minute="0,30"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "expires": 1500},
    },
    "golf-leaderboard-every-5m": {
        "task": "golf_sync_leaderboard",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "expires": 270},
    },
    "golf-dfs-every-6h": {
        "task": "golf_sync_dfs",
        "schedule": crontab(minute=30, hour="6,12,18,0"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "golf-stats-weekly-tuesday": {
        "task": "golf_sync_stats",
        "schedule": crontab(minute=0, hour=12, day_of_week="tuesday"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "golf-score-pools-every-5m": {
        "task": "golf_score_pools",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "expires": 270},
    },
    # === Daily sweep (status repair, social scrape #2, embedded tweets, archive) ===
    # Lightweight housekeeping — no full pipeline re-runs or flow generation
    "daily-sweep-4am-eastern": {
        "task": "run_daily_sweep",
        "schedule": crontab(minute=0, hour=9),  # 4:00 AM EST = 09:00 UTC (+30 min after ingestion)
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    # === Flow missing sweep (safety-net for LIVE→FINAL hook misfire) ===
    # Runs after ingestion + sweep have settled. Finds FINAL games with no artifact
    # and re-enqueues trigger_flow_for_game; NX lock prevents double-dispatch.
    "flow-missing-sweep-7am-eastern": {
        "task": "sweep_missing_flows",
        "schedule": crontab(minute=0, hour=12),  # 7:00 AM EST = 12:00 UTC
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    # === Analytics: outcome recording + batch sims (noon–3 AM ET = 17–08 UTC) ===
    # Runs every 30 min during active sports hours. Dispatches to the API
    # worker's "celery" queue (same Redis broker, different Celery app).
    "record-outcomes-every-30m": {
        "task": "record_completed_outcomes",
        "schedule": crontab(minute="0,30", hour="0-8,17-23"),
        "options": {"queue": "celery", "routing_key": "celery", "expires": 1500},
    },
    # === MLB forecast refresh (hourly) ===
    # Pre-computes predictions for all MLB games in the next 24 hours.
    # Results stored in mlb_daily_forecasts work table for downstream apps.
    "mlb-forecast-refresh-hourly": {
        "task": "refresh_mlb_forecasts",
        "schedule": crontab(minute=5),  # :05 past each hour (avoids :00 pile-up)
        "options": {"queue": "celery", "routing_key": "celery", "expires": 3300},
    },
    # === Pipeline coverage report (daily 06:00 UTC) ===
    # Writes a PipelineCoverageReport row summarising FINAL games vs flows for
    # yesterday, broken down by sport.  Re-running overwrites the same-day row.
    # Runs after ingestion (03:30 UTC) and flow sweep (07:00 EST / 12:00 UTC)
    # have had time to settle, but early enough for the admin morning review.
    "pipeline-coverage-report-daily-6am-utc": {
        "task": "generate_pipeline_coverage_report",
        "schedule": crontab(minute=0, hour=6),  # 06:00 UTC
        "options": {"queue": "celery", "routing_key": "celery", "expires": 3300},
    },
}

# Social polling — game social collection every 30 min, mapping staggered at :15/:45
_live_polling_schedule = {
    "game-social-every-60-min": {
        "task": "collect_game_social",
        "schedule": crontab(minute="0"),
        "options": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE, "expires": 3300},
    },
    "map-social-to-games-every-30-min": {
        "task": "map_social_to_games",
        "schedule": crontab(minute="15,45"),
        "options": {"queue": SOCIAL_BULK_QUEUE, "routing_key": SOCIAL_BULK_QUEUE, "expires": 1500},
    },
    # Playwright session health probe — every 30 min, staggered at :10/:40 so
    # it doesn't compete with game-social at :00/:30.  Expires at 28 min so a
    # slow queue never runs a stale probe from the previous cycle.
    "playwright-session-health-every-30m": {
        "task": "check_playwright_session_health",
        "schedule": crontab(minute="10,40"),
        "options": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE, "expires": 1680},
    },
}

# All environments run the full schedule — local mirrors production.
_beat_schedule = {
    **_polling_schedule,
    **_scheduled_tasks,
    **_live_polling_schedule,
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

    # Run an immediate health probe on startup so circuit breaker state is
    # populated before the first beat-scheduled probe fires at :10/:40.
    # Dispatch async so it doesn't block worker initialisation.
    try:
        app.send_task("check_playwright_session_health", queue=SOCIAL_QUEUE)
        logger.info("playwright_session_health_startup_probe_dispatched")
    except Exception:
        logger.warning("playwright_session_health_startup_probe_dispatch_failed", exc_info=True)


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
