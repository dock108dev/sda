"""Admin endpoint for triggering any registered Celery task on-demand."""

from __future__ import annotations

import logging
from typing import Any

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


# ---------------------------------------------------------------------------
# Task registry — whitelist of tasks that can be triggered via the admin UI.
# Only tasks listed here are dispatchable.  The queue value determines which
# Celery worker picks up the task.
# ---------------------------------------------------------------------------

TASK_REGISTRY: dict[str, TaskRegistryEntry] = {
    entry.name: entry
    for entry in [
        TaskRegistryEntry(
            name="poll_live_pbp",
            queue="sports-scraper",
            description="Poll play-by-play, player stats, team stats, and boxscores",
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
