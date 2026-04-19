"""Celery task for re-generating a game flow after a quality-gate failure (ISSUE-053).

Dispatched by grade_flow_task when the 3-tier grader returns a score below
GATE_THRESHOLD.  Calls the pipeline API to start a fresh pipeline run for the
same game, injecting the structured failure reasons as prompt context.

One regen attempt is permitted (MAX_REGEN_ATTEMPTS == 1).  If the second run
also fails the gate, grade_flow_task handles the template_fallback path directly.
"""

from __future__ import annotations

import logging

from celery import shared_task

from ..celery_app import DEFAULT_QUEUE
from ..logging import logger as scraper_logger

logger = logging.getLogger(__name__)


@shared_task(
    name="regen_flow_task",
    bind=True,
    queue=DEFAULT_QUEUE,
    max_retries=1,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=False,
)
def regen_flow_task(
    self,
    game_id: int,
    sport: str,
    failure_reasons: list[str],
    regen_attempt: int,
) -> dict:
    """Re-trigger the pipeline for a game with quality-gate failure context.

    Args:
        game_id: PK of the SportsGame to regenerate.
        sport: League code (e.g. "NBA").
        failure_reasons: Structured list of grader failure reasons collected
            from the Tier 1 result and Tier 2 rubric.  Passed to the pipeline
            so the next RENDER_BLOCKS invocation can include them as prompt
            context.
        regen_attempt: How many regen attempts have already run for this game.
            The API pipeline will increment this before dispatching the next
            grade_flow_task, so if the re-run also fails the gate the
            template_fallback path is triggered.

    Returns:
        Dict with regeneration result summary.
    """
    next_regen_attempt = regen_attempt + 1

    scraper_logger.info(
        "regen_flow_task_start",
        extra={
            "game_id": game_id,
            "sport": sport,
            "failure_count": len(failure_reasons),
            "next_regen_attempt": next_regen_attempt,
        },
    )

    result = _call_pipeline_regen(
        game_id=game_id,
        failure_reasons=failure_reasons,
        regen_attempt=next_regen_attempt,
    )

    scraper_logger.info(
        "regen_flow_task_complete",
        extra={
            "game_id": game_id,
            "sport": sport,
            "result_status": result.get("status"),
        },
    )

    return {
        "game_id": game_id,
        "sport": sport,
        "regen_attempt": next_regen_attempt,
        "failure_reasons": failure_reasons,
        "pipeline_result": result,
    }


def _call_pipeline_regen(
    game_id: int,
    failure_reasons: list[str],
    regen_attempt: int,
) -> dict:
    """Call the internal pipeline API to re-run flow generation with failure context."""
    import httpx

    from ..api_client import get_api_headers
    from ..config import settings

    api_base = settings.api_internal_url

    try:
        with httpx.Client(timeout=300.0, headers=get_api_headers()) as client:
            response = client.post(
                f"{api_base}/api/admin/sports/pipeline/{game_id}/run-full",
                json={
                    "triggered_by": "grade_gate_regen",
                    "regen_attempt": regen_attempt,
                    "failure_reasons": failure_reasons,
                },
            )
            response.raise_for_status()
            result = response.json()

        logger.info(
            "regen_pipeline_api_success",
            extra={
                "game_id": game_id,
                "regen_attempt": regen_attempt,
                "status": result.get("status"),
            },
        )
        return {"status": "success", "result": result}

    except httpx.HTTPStatusError as exc:
        logger.error(
            "regen_pipeline_api_http_error",
            extra={
                "game_id": game_id,
                "status_code": exc.response.status_code,
                "error": exc.response.text[:500],
            },
        )
        if 400 <= exc.response.status_code < 500:
            # 4xx: not retryable (bad request, game not found, etc.)
            return {
                "status": "error",
                "error": f"HTTP {exc.response.status_code}",
            }
        raise  # 5xx: let Celery retry

    except Exception as exc:
        logger.error(
            "regen_pipeline_api_error",
            exc_info=True,
            extra={"game_id": game_id, "error": str(exc)},
        )
        raise
