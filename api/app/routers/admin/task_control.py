"""Admin endpoint for triggering any registered Celery task on-demand."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...celery_client import get_celery_app

logger = logging.getLogger(__name__)

router = APIRouter()


class TaskRegistryEntry(BaseModel):
    name: str
    queue: str
    description: str


class TriggerRequest(BaseModel):
    task_name: str
    args: list[Any] = []


class TriggerResponse(BaseModel):
    status: str
    task_name: str
    task_id: str


# ---------------------------------------------------------------------------
# Task registry — whitelist of tasks that can be triggered via the admin UI.
# Only tasks listed here are dispatchable.  The queue value determines which
# Celery worker picks up the task.
# ---------------------------------------------------------------------------

TASK_REGISTRY: dict[str, TaskRegistryEntry] = {
    entry.name: entry
    for entry in [
        # Ingestion
        TaskRegistryEntry(
            name="run_scheduled_ingestion",
            queue="sports-scraper",
            description="Full scheduled ingestion (NBA, NHL, NCAAB sequentially)",
        ),
        TaskRegistryEntry(
            name="run_daily_sweep",
            queue="sports-scraper",
            description="Daily truth repair and backfill sweep",
        ),
        # Polling
        TaskRegistryEntry(
            name="update_game_states",
            queue="sports-scraper",
            description="Update game state machine for all tracked games",
        ),
        TaskRegistryEntry(
            name="poll_live_pbp",
            queue="sports-scraper",
            description="Poll live play-by-play and boxscores",
        ),
        # Odds
        TaskRegistryEntry(
            name="sync_mainline_odds",
            queue="sports-scraper",
            description="Sync mainline odds (spreads, totals, moneyline)",
        ),
        TaskRegistryEntry(
            name="sync_prop_odds",
            queue="sports-scraper",
            description="Sync player/team prop odds for pregame events",
        ),
        # Social
        TaskRegistryEntry(
            name="collect_game_social",
            queue="social-scraper",
            description="Collect social media content for upcoming games",
        ),
        TaskRegistryEntry(
            name="collect_social_for_league",
            queue="social-scraper",
            description="Collect social content for a specific league",
        ),
        TaskRegistryEntry(
            name="map_social_to_games",
            queue="social-scraper",
            description="Map collected social posts to games",
        ),
        TaskRegistryEntry(
            name="run_final_whistle_social",
            queue="social-scraper",
            description="Collect post-game social content for a specific game",
        ),
        # Flows
        TaskRegistryEntry(
            name="run_scheduled_flow_generation",
            queue="sports-scraper",
            description="Run flow generation for all leagues",
        ),
        TaskRegistryEntry(
            name="run_scheduled_nba_flow_generation",
            queue="sports-scraper",
            description="Run flow generation for NBA games",
        ),
        TaskRegistryEntry(
            name="run_scheduled_nhl_flow_generation",
            queue="sports-scraper",
            description="Run flow generation for NHL games",
        ),
        TaskRegistryEntry(
            name="run_scheduled_ncaab_flow_generation",
            queue="sports-scraper",
            description="Run flow generation for NCAAB games (max 10)",
        ),
        TaskRegistryEntry(
            name="trigger_flow_for_game",
            queue="sports-scraper",
            description="Trigger flow generation for a specific game",
        ),
        # Timelines
        TaskRegistryEntry(
            name="run_scheduled_timeline_generation",
            queue="sports-scraper",
            description="Run scheduled timeline generation for all leagues",
        ),
        # MLB Advanced Stats
        TaskRegistryEntry(
            name="ingest_mlb_advanced_stats",
            queue="sports-scraper",
            description="Ingest Statcast-derived advanced stats for an MLB game",
        ),
        # Utility
        TaskRegistryEntry(
            name="clear_scraper_cache",
            queue="sports-scraper",
            description="Clear scraper cache for a league (optionally limit by days)",
        ),
    ]
}


@router.get("/tasks/registry", response_model=list[TaskRegistryEntry])
async def get_task_registry() -> list[TaskRegistryEntry]:
    """Return the list of tasks that can be triggered via the admin UI."""
    return list(TASK_REGISTRY.values())


@router.post("/tasks/trigger", response_model=TriggerResponse)
async def trigger_task(body: TriggerRequest) -> TriggerResponse:
    """Dispatch a registered Celery task by name with optional arguments."""
    entry = TASK_REGISTRY.get(body.task_name)
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task: {body.task_name}. Use GET /tasks/registry for available tasks.",
        )

    celery = get_celery_app()
    result = celery.send_task(
        entry.name,
        args=body.args if body.args else [],
        queue=entry.queue,
        routing_key=entry.queue,
    )

    logger.info(
        "Admin triggered task %s (id=%s) with args=%s",
        entry.name,
        result.id,
        body.args,
    )

    return TriggerResponse(
        status="dispatched",
        task_name=entry.name,
        task_id=result.id,
    )
