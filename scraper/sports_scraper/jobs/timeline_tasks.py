"""Celery tasks for timeline generation."""

from __future__ import annotations

from celery import shared_task

from ..logging import logger
from ..services.timeline_generator import (
    SCHEDULED_DAYS_BACK,
    generate_all_needed_timelines,
    generate_missing_timelines,
)


@shared_task(
    name="generate_missing_timelines",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def generate_missing_timelines_task(
    league_code: str,
    days_back: int | None = None,
    max_games: int | None = None,
) -> dict:
    """
    Generate timeline artifacts for games missing them.

    This task finds completed games with play-by-play data but no timeline
    artifacts, and triggers timeline generation for each one.

    Args:
        league_code: League to process (required)
        days_back: How many days back to check (None = ALL games)
        max_games: Maximum number of games to process (None = all)

    Returns:
        Summary dict with counts of processed/successful/failed games
    """
    logger.info(
        "timeline_gen_task_started",
        league=league_code,
        days_back=days_back,
        max_games=max_games,
    )

    summary = generate_missing_timelines(
        league_code=league_code,
        days_back=days_back,
        max_games=max_games,
    )

    logger.info("timeline_gen_task_completed", **summary)

    return summary


@shared_task(
    name="regenerate_timeline",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def regenerate_timeline_task(
    game_id: int,
    reason: str = "manual",
) -> dict:
    """
    Regenerate timeline artifact for a specific game.

    This task calls the API endpoint to regenerate the timeline for a single game.
    Used by auto-regeneration after social backfill or manual regeneration requests.

    Args:
        game_id: Game ID to regenerate timeline for
        reason: Reason for regeneration (e.g., "social_backfill", "manual")

    Returns:
        Result dict with success/failure status
    """
    import httpx

    from ..api_client import get_api_headers
    from ..config import settings

    logger.info(
        "timeline_regen_task_started",
        game_id=game_id,
        reason=reason,
    )

    api_url = f"{settings.api_internal_url}/api/admin/sports/timelines/generate/{game_id}"

    try:
        response = httpx.post(
            api_url,
            json={"timeline_version": "v1"},
            headers=get_api_headers(),
            timeout=600,  # 10 minute timeout for large games
        )
        response.raise_for_status()
        result = response.json()

        logger.info(
            "timeline_regen_task_completed",
            game_id=game_id,
            reason=reason,
            success=True,
        )

        return {
            "game_id": game_id,
            "success": True,
            "reason": reason,
            "result": result,
        }

    except httpx.HTTPStatusError as exc:
        logger.error(
            "timeline_regen_task_failed",
            game_id=game_id,
            reason=reason,
            status_code=exc.response.status_code,
            error=exc.response.text,
        )
        return {
            "game_id": game_id,
            "success": False,
            "reason": reason,
            "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
        }

    except Exception as exc:
        logger.error(
            "timeline_regen_task_failed",
            game_id=game_id,
            reason=reason,
            error=str(exc),
        )
        return {
            "game_id": game_id,
            "success": False,
            "reason": reason,
            "error": str(exc),
        }


@shared_task(
    name="run_scheduled_timeline_generation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_scheduled_timeline_generation() -> dict:
    """
    Scheduled task to generate/regenerate timelines for all games that need them.

    This runs after the scheduled ingestion (90 minutes later) and processes:
    - Games that completed and are missing timeline artifacts
    - Games where PBP or social data was updated after timeline was generated

    Uses the same lookback window as the scheduler (96 hours / 4 days).
    """
    from ..config_sports import get_scheduled_leagues
    from ..services.job_runs import track_job_run

    leagues = list(get_scheduled_leagues())

    total_summary = {
        "leagues_processed": 0,
        "total_games_found": 0,
        "total_games_missing": 0,
        "total_games_stale": 0,
        "total_games_processed": 0,
        "total_games_successful": 0,
        "total_games_failed": 0,
    }

    logger.info(
        "scheduled_timeline_gen_start",
        leagues=leagues,
        days_back=SCHEDULED_DAYS_BACK,
    )

    with track_job_run("timeline_generation", leagues) as tracker:
        for league_code in leagues:
            try:
                summary = generate_all_needed_timelines(
                    league_code=league_code,
                    days_back=SCHEDULED_DAYS_BACK,
                    max_games=None,  # Process all games
                )

                total_summary["leagues_processed"] += 1
                total_summary["total_games_found"] += summary.get("games_found", 0)
                total_summary["total_games_missing"] += summary.get("games_missing", 0)
                total_summary["total_games_stale"] += summary.get("games_stale", 0)
                total_summary["total_games_processed"] += summary.get("games_processed", 0)
                total_summary["total_games_successful"] += summary.get("games_successful", 0)
                total_summary["total_games_failed"] += summary.get("games_failed", 0)

            except Exception as exc:
                logger.exception(
                    "scheduled_timeline_gen_league_failed",
                    league=league_code,
                    error=str(exc),
                )

        tracker.summary_data = total_summary

    logger.info("scheduled_timeline_gen_complete", **total_summary)

    return total_summary
