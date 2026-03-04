"""Celery app configuration for sports scraper."""

from __future__ import annotations

from celery import Celery, signals
from celery.schedules import crontab

from .config import settings
from .db import db_models, get_session
from .logging import logger
from .utils.datetime_utils import now_utc

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

app = Celery(
    "sports-data-scraper",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["sports_scraper.jobs.tasks"],
)
app.conf.update(**celery_config)
app.conf.task_routes = {
    "run_scrape_job": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # Bulk social tasks route to lower-priority queue so live tasks aren't starved
    "collect_social_for_league": {"queue": SOCIAL_BULK_QUEUE, "routing_key": SOCIAL_BULK_QUEUE},
    "collect_team_social": {"queue": SOCIAL_BULK_QUEUE, "routing_key": SOCIAL_BULK_QUEUE},
    "map_social_to_games": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    # Social error callback runs on main scraper queue (DB writes only)
    "handle_social_task_failure": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # Game-state-machine polling tasks
    "update_game_states": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "poll_live_pbp": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "sync_mainline_odds": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "sync_prop_odds": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "trigger_flow_for_game": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    "run_daily_sweep": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    # Final-whistle social scrape runs on social-scraper queue (concurrency=1)
    "run_final_whistle_social": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    # Game social collection every 30 min (odds-gated + staleness targeting)
    "collect_game_social": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    # MLB advanced stats (Statcast-derived, post-game)
    "ingest_mlb_advanced_stats": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
}
# Daily pipeline schedule (all times US Eastern / UTC during EST):
#
#   3:30 AM EST (08:30 UTC) — Sports ingestion (NBA → NHL → NCAAB → MLB sequentially)
#   4:00 AM EST (09:00 UTC) — Daily sweep (truth repair, backfill missing data)
#   4:30 AM EST (09:30 UTC) — NBA flow generation
#   5:00 AM EST (10:00 UTC) — NHL flow generation
#   5:30 AM EST (10:30 UTC) — NCAAB flow generation
#   6:00 AM EST (11:00 UTC) — MLB flow generation
#
# Each job is spaced 30 minutes apart. During EDT (March-November) all times
# shift 1 hour later (e.g., ingestion at 4:30 AM EDT).
#
# High-frequency polling (every 60s, staggered 15s apart via countdown):
#   :00  update_game_states  — disabled 3–11 AM EST (08–16 UTC)
#   :15  poll_live_pbp       — disabled 3–11 AM EST (08–16 UTC)
#   :30  sync_mainline_odds  — no quiet window
#   :45  sync_prop_odds      — no quiet window

# High-frequency polling — all fire every 60s, staggered by countdown offsets.
# Stats/PBP disabled 3–11 AM EST (hour 08–16 UTC excluded from crontab).
_polling_schedule = {
    "game-state-updater-every-60s": {
        "task": "update_game_states",
        "schedule": crontab(minute="*/1", hour="0-7,16-23"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 0},
    },
    "live-pbp-poll-every-60s": {
        "task": "poll_live_pbp",
        "schedule": crontab(minute="*/1", hour="0-7,16-23"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 15},
    },
    "mainline-odds-sync-every-60s": {
        "task": "sync_mainline_odds",
        "schedule": crontab(minute="*/1"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 30},
    },
    "prop-odds-sync-every-60s": {
        "task": "sync_prop_odds",
        "schedule": crontab(minute="*/1"),
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE, "countdown": 45},
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
    "daily-nba-flow-generation-430am-eastern": {
        "task": "run_scheduled_nba_flow_generation",
        "schedule": crontab(minute=30, hour=9),  # 4:30 AM EST = 09:30 UTC (+30 min after sweep)
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "daily-nhl-flow-generation-5am-eastern": {
        "task": "run_scheduled_nhl_flow_generation",
        "schedule": crontab(minute=0, hour=10),  # 5:00 AM EST = 10:00 UTC (+30 min after NBA flow)
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "daily-ncaab-flow-generation-530am-eastern": {
        "task": "run_scheduled_ncaab_flow_generation",
        "schedule": crontab(minute=30, hour=10),  # 5:30 AM EST = 10:30 UTC (+30 min after NHL flow)
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    "daily-mlb-flow-generation-6am-eastern": {
        "task": "run_scheduled_mlb_flow_generation",
        "schedule": crontab(
            minute=0, hour=11
        ),  # 6:00 AM EST = 11:00 UTC (+30 min after NCAAB flow)
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
    # === Daily sweep (status repair, social scrape #2, embedded tweets, archive) ===
    # Lightweight housekeeping — no full pipeline re-runs or flow generation
    "daily-sweep-4am-eastern": {
        "task": "run_daily_sweep",
        "schedule": crontab(minute=0, hour=9),  # 4:00 AM EST = 09:00 UTC (+30 min after ingestion)
        "options": {"queue": DEFAULT_QUEUE, "routing_key": DEFAULT_QUEUE},
    },
}

# Social polling — game social collection every 30 min, mapping staggered at :15/:45
_live_polling_schedule = {
    "game-social-every-30-min": {
        "task": "collect_game_social",
        "schedule": crontab(minute="0,30"),
        "options": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
    },
    "map-social-to-games-every-30-min": {
        "task": "map_social_to_games",
        "schedule": crontab(minute="15,45"),
        "options": {"queue": SOCIAL_QUEUE, "routing_key": SOCIAL_QUEUE},
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


@signals.worker_ready.connect
def on_worker_ready(sender=None, **kwargs):
    """Called when Celery worker is ready. Mark any stale runs as interrupted."""
    # sender is the worker Consumer object with .hostname attribute
    worker_name = getattr(sender, "hostname", None) or str(sender) if sender else "unknown"
    logger.info("celery_worker_ready", worker=worker_name)
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
