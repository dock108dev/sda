"""Celery task: periodic Playwright session health probe.

Runs every 30 minutes on the social-scraper queue. Completes in under 10
seconds. On session expiry, trips a Redis circuit breaker that the admin
dashboard polls and scraping tasks can optionally check.

Probe failure does NOT raise — it only records state and returns. This keeps
the probe non-blocking: scraping tasks continue to run and handle their own
auth errors independently.
"""

from __future__ import annotations

import redis as _redis_mod
from celery import shared_task

from ..celery_app import SOCIAL_QUEUE
from ..config import settings
from ..logging import logger
from ..social.session_health import (
    CIRCUIT_BREAKER_THRESHOLD,
    get_cached_health,
    get_consecutive_failures,
    probe_session_health,
    record_health,
)

# Task expires after 28 min — if the beat fires and no worker picks it up
# before the next beat cycle, the stale task is dropped automatically.
_TASK_EXPIRES_SECONDS = 28 * 60


@shared_task(
    name="check_playwright_session_health",
    queue=SOCIAL_QUEUE,
    expires=_TASK_EXPIRES_SECONDS,
    time_limit=30,
    soft_time_limit=25,
    ignore_result=False,
)
def check_playwright_session_health() -> dict:
    """Probe X/Twitter session validity and record result to Redis.

    Returns a dict with the health snapshot so the Celery result backend
    stores it for debugging. The canonical health state lives in Redis.
    """
    logger.info("playwright_session_health_probe_start")

    result = probe_session_health()

    newly_tripped = False
    try:
        r = _redis_mod.from_url(settings.redis_url, decode_responses=True)
        newly_tripped = record_health(r, result)
        consecutive = get_consecutive_failures(r)
    except Exception:
        logger.warning(
            "playwright_session_health_redis_write_failed",
            exc_info=True,
        )
        consecutive = 0

    if result.is_valid:
        logger.info(
            "playwright_session_health_ok",
            checked_at=result.checked_at,
        )
    else:
        logger.error(
            "playwright_session_health_failed",
            reason=result.failure_reason,
            checked_at=result.checked_at,
            auth_token_present=result.auth_token_present,
            ct0_present=result.ct0_present,
            consecutive_failures=consecutive,
        )

    if newly_tripped:
        logger.error(
            "playwright_circuit_breaker_tripped",
            reason=result.failure_reason,
            consecutive_failures=CIRCUIT_BREAKER_THRESHOLD,
            action="social_scraping_suspended",
            alert=True,
        )

    return {
        "is_valid": result.is_valid,
        "checked_at": result.checked_at,
        "failure_reason": result.failure_reason,
        "auth_token_present": result.auth_token_present,
        "ct0_present": result.ct0_present,
        "consecutive_failures": consecutive,
        "circuit_newly_tripped": newly_tripped,
    }
