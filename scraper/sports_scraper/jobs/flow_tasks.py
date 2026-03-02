"""Celery tasks for game flow generation."""

from __future__ import annotations

from celery import shared_task

from ..api_client import get_api_headers
from ..logging import logger


def _run_flow_generation(
    league: str,
    max_games: int | None = None,
) -> dict:
    """
    Common implementation for scheduled flow generation tasks.

    Args:
        league: League code (NBA, NHL, NCAAB, MLB)
        max_games: Maximum number of games to process (None = no limit)

    Returns:
        dict with job result
    """
    import time
    from datetime import timedelta

    import httpx

    from ..config import settings
    from ..utils.datetime_utils import today_et

    # Calculate 72-hour window: 2 days ago through today (ET sports calendar)
    today = today_et()
    start_date = today - timedelta(days=2)
    end_date = today

    logger.info(
        f"scheduled_{league.lower()}_flow_gen_start",
        start_date=str(start_date),
        end_date=str(end_date),
        max_games=max_games,
    )

    api_base = settings.api_internal_url

    try:
        # Start the bulk generation job
        request_body = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "leagues": [league],
            "force": False,  # Don't regenerate existing flows
        }
        if max_games is not None:
            request_body["max_games"] = max_games

        with httpx.Client(timeout=60.0, headers=get_api_headers()) as client:
            response = client.post(
                f"{api_base}/api/admin/sports/pipeline/bulk-generate-async",
                json=request_body,
            )
            response.raise_for_status()
            job_data = response.json()

        job_id = job_data["job_id"]
        logger.info(f"scheduled_{league.lower()}_flow_gen_job_started", job_id=job_id)

        # Poll for completion (max 30 minutes, check every 30 seconds)
        max_polls = 60
        poll_interval = 30

        for _poll_num in range(max_polls):
            time.sleep(poll_interval)

            with httpx.Client(timeout=30.0, headers=get_api_headers()) as client:
                status_response = client.get(
                    f"{api_base}/api/admin/sports/pipeline/bulk-generate-status/{job_id}"
                )
                status_response.raise_for_status()
                status = status_response.json()

            state = status.get("state", "UNKNOWN")

            if state == "PROGRESS":
                logger.info(
                    f"scheduled_{league.lower()}_flow_gen_progress",
                    job_id=job_id,
                    current=status.get("current"),
                    total=status.get("total"),
                    successful=status.get("successful"),
                    failed=status.get("failed"),
                    skipped=status.get("skipped"),
                )
            elif state == "SUCCESS":
                result = status.get("result", {})
                logger.info(
                    f"scheduled_{league.lower()}_flow_gen_complete",
                    job_id=job_id,
                    total_games=result.get("total_games", 0),
                    successful=result.get("successful", 0),
                    failed=result.get("failed", 0),
                    skipped=result.get("skipped", 0),
                    generated=result.get("generated", 0),
                )
                return {
                    "job_id": job_id,
                    "state": "SUCCESS",
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "leagues": [league],
                    **result,
                }
            elif state == "FAILURE":
                logger.error(
                    f"scheduled_{league.lower()}_flow_gen_failed",
                    job_id=job_id,
                    status=status.get("status"),
                )
                return {
                    "job_id": job_id,
                    "state": "FAILURE",
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "leagues": [league],
                    "error": status.get("status"),
                }

        # Timed out waiting for completion
        logger.warning(
            f"scheduled_{league.lower()}_flow_gen_timeout",
            job_id=job_id,
            max_wait_minutes=max_polls * poll_interval / 60,
        )
        return {
            "job_id": job_id,
            "state": "TIMEOUT",
            "start_date": str(start_date),
            "end_date": str(end_date),
            "leagues": [league],
            "error": "Timed out waiting for job completion",
        }

    except httpx.HTTPStatusError as exc:
        logger.error(
            f"scheduled_{league.lower()}_flow_gen_http_error",
            status_code=exc.response.status_code,
            error=exc.response.text,
        )
        return {
            "state": "ERROR",
            "start_date": str(start_date),
            "end_date": str(end_date),
            "leagues": [league],
            "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
        }
    except Exception as exc:
        logger.exception(
            f"scheduled_{league.lower()}_flow_gen_error",
            error=str(exc),
        )
        raise  # Let Celery retry


@shared_task(
    name="run_scheduled_nba_flow_generation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_scheduled_nba_flow_generation() -> dict:
    """
    Scheduled task to generate flows for NBA games in the last 72 hours.

    Runs 15 minutes after timeline generation completes (7:15 AM EST).
    Only generates flows for games that don't already have them (force=False).
    """
    return _run_flow_generation("NBA")


@shared_task(
    name="run_scheduled_nhl_flow_generation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_scheduled_nhl_flow_generation() -> dict:
    """
    Scheduled task to generate flows for NHL games in the last 72 hours.

    Runs 15 minutes after NBA flow generation (7:30 AM EST).
    Only generates flows for games that don't already have them (force=False).
    """
    return _run_flow_generation("NHL")


@shared_task(
    name="run_scheduled_ncaab_flow_generation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_scheduled_ncaab_flow_generation() -> dict:
    """
    Scheduled task to generate flows for NCAAB games in the last 72 hours.

    Runs 15 minutes after NHL flow generation (7:45 AM EST).
    Only generates flows for games that don't already have them (force=False).
    """
    return _run_flow_generation("NCAAB")


@shared_task(
    name="run_scheduled_mlb_flow_generation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_scheduled_mlb_flow_generation() -> dict:
    """
    Scheduled task to generate flows for MLB games in the last 72 hours.

    Runs 30 minutes after NCAAB flow generation (6:00 AM EST = 11:00 UTC).
    Only generates flows for games that don't already have them (force=False).
    """
    return _run_flow_generation("MLB")


@shared_task(
    name="run_scheduled_flow_generation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_scheduled_flow_generation() -> dict:
    """
    Scheduled task to generate game flows for all leagues in the last 3 days.

    This runs after timeline generation completes and generates flows for all
    games with PBP data that haven't had flows generated yet.

    Uses a 3-day window: today, yesterday, and 2 days ago.
    For example, if run on 1/23, generates flows for 1/21, 1/22, and 1/23.
    """
    import time
    from datetime import timedelta

    import httpx

    from ..config import settings
    from ..config_sports import get_scheduled_leagues
    from ..utils.datetime_utils import today_et

    # Calculate 3-day window: 2 days ago through today (ET sports calendar)
    today = today_et()
    start_date = today - timedelta(days=2)
    end_date = today

    leagues = list(get_scheduled_leagues())

    logger.info(
        "scheduled_flow_gen_start",
        start_date=str(start_date),
        end_date=str(end_date),
        leagues=leagues,
    )

    api_base = settings.api_internal_url

    try:
        # Start the bulk generation job
        with httpx.Client(timeout=60.0, headers=get_api_headers()) as client:
            response = client.post(
                f"{api_base}/api/admin/sports/games/bulk-generate-async",
                json={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "leagues": leagues,
                    "force": False,  # Don't regenerate existing flows
                },
            )
            response.raise_for_status()
            job_data = response.json()

        job_id = job_data["job_id"]
        logger.info("scheduled_flow_gen_job_started", job_id=job_id)

        # Poll for completion (max 30 minutes, check every 30 seconds)
        max_polls = 60
        poll_interval = 30

        for _poll_num in range(max_polls):
            time.sleep(poll_interval)

            with httpx.Client(timeout=30.0, headers=get_api_headers()) as client:
                status_response = client.get(
                    f"{api_base}/api/admin/sports/games/bulk-generate-status/{job_id}"
                )
                status_response.raise_for_status()
                status = status_response.json()

            state = status.get("state", "UNKNOWN")

            if state == "PROGRESS":
                logger.info(
                    "scheduled_flow_gen_progress",
                    job_id=job_id,
                    current=status.get("current"),
                    total=status.get("total"),
                    successful=status.get("successful"),
                    failed=status.get("failed"),
                    skipped=status.get("skipped"),
                )
            elif state == "SUCCESS":
                result = status.get("result", {})
                logger.info(
                    "scheduled_flow_gen_complete",
                    job_id=job_id,
                    total_games=result.get("total_games", 0),
                    successful=result.get("successful", 0),
                    failed=result.get("failed", 0),
                    skipped=result.get("skipped", 0),
                    generated=result.get("generated", 0),
                )
                return {
                    "job_id": job_id,
                    "state": "SUCCESS",
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "leagues": leagues,
                    **result,
                }
            elif state == "FAILURE":
                logger.error(
                    "scheduled_flow_gen_failed",
                    job_id=job_id,
                    status=status.get("status"),
                )
                return {
                    "job_id": job_id,
                    "state": "FAILURE",
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "leagues": leagues,
                    "error": status.get("status"),
                }

        # Timed out waiting for completion
        logger.warning(
            "scheduled_flow_gen_timeout",
            job_id=job_id,
            max_wait_minutes=max_polls * poll_interval / 60,
        )
        return {
            "job_id": job_id,
            "state": "TIMEOUT",
            "start_date": str(start_date),
            "end_date": str(end_date),
            "leagues": leagues,
            "error": "Timed out waiting for job completion",
        }

    except httpx.HTTPStatusError as exc:
        logger.error(
            "scheduled_flow_gen_http_error",
            status_code=exc.response.status_code,
            error=exc.response.text,
        )
        return {
            "state": "ERROR",
            "start_date": str(start_date),
            "end_date": str(end_date),
            "leagues": leagues,
            "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
        }
    except Exception as exc:
        logger.exception(
            "scheduled_flow_gen_error",
            error=str(exc),
        )
        raise  # Let Celery retry
