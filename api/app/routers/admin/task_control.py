"""Admin endpoint for triggering any registered Celery task on-demand."""

from __future__ import annotations

import logging
from typing import Any

import redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...celery_client import get_celery_app
from ...config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

HOLD_KEY = "sports:tasks_held"


def _redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


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


class HoldStatusResponse(BaseModel):
    held: bool


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
            description="Collect social for games with odds but missing/stale social data",
        ),
        TaskRegistryEntry(
            name="collect_social_for_league",
            queue="social-scraper",
            description="Collect social content for a specific league",
        ),
        TaskRegistryEntry(
            name="map_social_to_games",
            queue="social-bulk",
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
        # Live orchestrator + odds
        TaskRegistryEntry(
            name="live_orchestrator_tick",
            queue="sports-scraper",
            description="Run one live orchestrator tick (dispatches per-game polling tasks)",
        ),
        TaskRegistryEntry(
            name="poll_live_odds_mainline",
            queue="sports-scraper",
            description="Poll live mainline odds for a league (args: [league_code, [game_ids]])",
        ),
        TaskRegistryEntry(
            name="poll_live_odds_props",
            queue="sports-scraper",
            description="Poll live prop odds for a league (args: [league_code, [game_ids]])",
        ),
        # Analytics (runs on api-worker via default celery queue)
        TaskRegistryEntry(
            name="train_analytics_model",
            queue="celery",
            description="Train an analytics model (args: [training_job_id])",
        ),
        TaskRegistryEntry(
            name="backtest_analytics_model",
            queue="celery",
            description="Backtest a trained model (args: [backtest_job_id])",
        ),
        TaskRegistryEntry(
            name="batch_simulate_games",
            queue="celery",
            description="Run batch Monte Carlo simulations (args: [batch_sim_job_id])",
        ),
        TaskRegistryEntry(
            name="record_completed_outcomes",
            queue="celery",
            description="Match pending predictions against finalized game outcomes",
        ),
        TaskRegistryEntry(
            name="check_model_degradation",
            queue="celery",
            description="Check for model degradation via Brier score comparison (args: [sport])",
        ),
        TaskRegistryEntry(
            name="train_calibration_model",
            queue="celery",
            description="Train sim probability calibration model from historical predictions + closing lines (args: [sport])",
        ),
        # Golf
        TaskRegistryEntry(
            name="golf_sync_schedule",
            queue="sports-scraper",
            description="Sync PGA Tour tournament schedule from DataGolf (args: [tour, season])",
        ),
        TaskRegistryEntry(
            name="golf_sync_players",
            queue="sports-scraper",
            description="Sync full golf player catalog from DataGolf",
        ),
        TaskRegistryEntry(
            name="golf_sync_field",
            queue="sports-scraper",
            description="Sync tournament field updates from DataGolf (args: [tour])",
        ),
        TaskRegistryEntry(
            name="golf_sync_leaderboard",
            queue="sports-scraper",
            description="Sync live leaderboard and tournament stats from DataGolf",
        ),
        TaskRegistryEntry(
            name="golf_sync_odds",
            queue="sports-scraper",
            description="Sync outright golf odds for all markets (args: [tour])",
        ),
        TaskRegistryEntry(
            name="golf_sync_dfs",
            queue="sports-scraper",
            description="Sync DFS projections for all supported sites (args: [tour])",
        ),
        TaskRegistryEntry(
            name="golf_sync_stats",
            queue="sports-scraper",
            description="Sync player skill ratings from DataGolf (args: [tour])",
        ),
        TaskRegistryEntry(
            name="golf_score_pools",
            queue="sports-scraper",
            description="Score all live golf pools and write materialized results",
        ),
    ]
}


@router.get("/tasks/hold", response_model=HoldStatusResponse)
async def get_hold_status() -> HoldStatusResponse:
    """Return whether task dispatch is currently held."""
    held = _redis().get(HOLD_KEY) == "1"
    return HoldStatusResponse(held=held)


@router.put("/tasks/hold", response_model=HoldStatusResponse)
async def set_hold_status(body: HoldStatusResponse) -> HoldStatusResponse:
    """Enable or disable the global task hold."""
    r = _redis()
    if body.held:
        r.set(HOLD_KEY, "1")
        logger.info("Admin HELD all task dispatch")
    else:
        r.delete(HOLD_KEY)
        logger.info("Admin RELEASED task hold")
    return HoldStatusResponse(held=body.held)


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
        headers={"manual_trigger": True},
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
