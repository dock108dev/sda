"""Admin endpoint for triggering any registered Celery task on-demand."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ...celery_client import get_celery_app
from ...config import settings

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

logger = logging.getLogger(__name__)

router = APIRouter()

HOLD_KEY = "sports:tasks_held"


def _redis() -> redis.Redis:
    # Use the Celery broker URL (Redis db 2) so the hold key lands in the same
    # database the scraper worker checks.  settings.redis_url may point to a
    # different database (db 0 in production).
    url = settings.celery_broker_url or settings.redis_url
    return redis.from_url(url, decode_responses=True)


class TaskRegistryEntry(BaseModel):
    name: str
    queue: str
    description: str


class TriggerRequest(BaseModel):
    task_name: str
    args: list[Any] = []


class TriggerResponse(BaseModel):
    model_config = _ALIAS_CFG

    status: str
    task_name: str
    task_id: str


class HoldStatusResponse(BaseModel):
    held: bool


class SessionHealthResponse(BaseModel):
    model_config = _ALIAS_CFG

    is_valid: bool
    checked_at: Optional[str] = None
    failure_reason: Optional[str] = None
    auth_token_present: bool = False
    ct0_present: bool = False
    circuit_open: bool = False
    stale: bool = False


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
        TaskRegistryEntry(
            name="ingest_nba_historical",
            queue="sports-scraper",
            description="Backfill NBA boxscores and PBP from Basketball Reference",
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
        # Social — session health
        TaskRegistryEntry(
            name="check_playwright_session_health",
            queue="social-scraper",
            description="Run a Playwright session health probe against X/Twitter",
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


_HEALTH_KEY = "playwright:session:health"
_CIRCUIT_OPEN_KEY = "playwright:session:circuit_open"
# Health snapshot is considered stale if older than 35 min (one probe cadence + margin)
_HEALTH_STALE_SECONDS = 35 * 60


@router.get("/social/session-health", response_model=SessionHealthResponse)
async def get_session_health() -> SessionHealthResponse:
    """Return the most recent Playwright session health snapshot from Redis.

    Updated every 30 minutes by the check_playwright_session_health beat task.
    The ``stale`` flag is set when the snapshot is older than 35 minutes,
    indicating that the probe has not run recently (e.g. worker is down).
    """
    r = _redis()
    raw = r.get(_HEALTH_KEY)
    circuit_open = r.get(_CIRCUIT_OPEN_KEY) == "1"

    if not raw:
        return SessionHealthResponse(
            is_valid=False,
            circuit_open=circuit_open,
            failure_reason="no health snapshot — probe has not run yet",
            stale=True,
        )

    try:
        data = json.loads(raw)
    except Exception:
        return SessionHealthResponse(
            is_valid=False,
            circuit_open=circuit_open,
            failure_reason="malformed health snapshot in Redis",
            stale=True,
        )

    stale = False
    checked_at_str = data.get("checked_at")
    if checked_at_str:
        try:
            checked_at = datetime.fromisoformat(checked_at_str)
            age = (datetime.now(timezone.utc) - checked_at).total_seconds()
            stale = age > _HEALTH_STALE_SECONDS
        except Exception:
            stale = True

    return SessionHealthResponse(
        is_valid=data.get("is_valid", False),
        checked_at=checked_at_str,
        failure_reason=data.get("failure_reason"),
        auth_token_present=data.get("auth_token_present", False),
        ct0_present=data.get("ct0_present", False),
        circuit_open=circuit_open,
        stale=stale,
    )


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
