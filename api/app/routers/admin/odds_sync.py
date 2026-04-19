"""Admin endpoint for on-demand odds synchronization."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


from ...celery_client import get_celery_app

router = APIRouter()


class OddsSyncResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    status: str
    league: str
    mainline_task_id: str
    prop_task_id: str


@router.post("/odds/sync", response_model=OddsSyncResponse)
async def trigger_odds_sync(
    league: str | None = Query(None, description="League code (e.g. NBA). Omit for all leagues."),
) -> OddsSyncResponse:
    """Dispatch mainline and prop odds sync tasks.

    Accepts an optional league filter so the UI can sync a single league
    on-demand without touching the others.
    """
    celery = get_celery_app()
    mainline = celery.send_task(
        "sync_mainline_odds",
        args=[league],
        queue="sports-scraper",
        routing_key="sports-scraper",
    )
    props = celery.send_task(
        "sync_prop_odds",
        args=[league],
        queue="sports-scraper",
        routing_key="sports-scraper",
    )
    return OddsSyncResponse(
        status="dispatched",
        league=league or "all",
        mainline_task_id=mainline.id,
        prop_task_id=props.id,
    )
