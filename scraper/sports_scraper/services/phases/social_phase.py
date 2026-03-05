"""Social dispatch phase — sends collection tasks to dedicated worker."""

from __future__ import annotations

from datetime import datetime, timedelta

from ...celery_app import SOCIAL_BULK_QUEUE
from ...logging import logger
from ...utils.datetime_utils import cap_social_date_range


def dispatch_social(
    run_id: int,
    config,
    summary: dict,
    start: datetime,
    end: datetime,
    supported_social_leagues: tuple,
    *,
    get_session,
    social_task_exists_fn,
    queue_job_run,
    enforce_social_queue_limit,
) -> None:
    """Phase: dispatch social scraping to dedicated worker.

    Creates a 'queued' DB record *before* dispatching so the task is
    immediately visible (and cancellable) in the RunsDrawer.  Oldest
    queued social tasks are evicted when the queue exceeds 10.

    Dispatches one task per league covering the full date range.
    """
    import uuid

    if config.league_code not in supported_social_leagues:
        logger.info(
            "x_social_not_implemented",
            run_id=run_id,
            league=config.league_code,
            message="X/social scraping is not yet implemented for this league; skipping.",
        )
    else:
        from ...jobs.social_tasks import collect_team_social, handle_social_task_failure

        # Enforce FIFO queue cap before adding a new task
        enforce_social_queue_limit(10)

        social_start, social_end = cap_social_date_range(start, end)

        if social_start > social_end:
            logger.info(
                "social_dispatch_skipped_empty_range",
                run_id=run_id,
                league=config.league_code,
                social_start=str(social_start),
                end=str(social_end),
                reason="Capped social_start exceeds end date",
            )
            return

        # Skip dispatch if a task is already queued/running for this league
        if social_task_exists_fn(config.league_code):
            logger.info(
                "social_dispatch_skipped_duplicate",
                run_id=run_id,
                league=config.league_code,
                reason="A social task is already queued or running for this league",
            )
            summary["social_posts"] = "skipped (already queued)"
            return

        # Dispatch a single task covering the full date range per league.
        task_id = str(uuid.uuid4())
        job_run_id = queue_job_run("social", [config.league_code], celery_task_id=task_id)

        logger.info(
            "social_dispatched_to_worker",
            run_id=run_id,
            league=config.league_code,
            start_date=str(social_start),
            end_date=str(social_end),
            job_run_id=job_run_id,
            celery_task_id=task_id,
        )
        collect_team_social.apply_async(
            args=[config.league_code, str(social_start), str(social_end)],
            kwargs={"scrape_run_id": run_id, "job_run_id": job_run_id},
            queue=SOCIAL_BULK_QUEUE,
            task_id=task_id,
            link_error=handle_social_task_failure.s(run_id),
        )

        summary["social_posts"] = "dispatched to worker"
