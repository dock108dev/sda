"""Admin webhook dead-letter endpoint — GET /api/admin/webhooks/dead-letters."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.stripe import WebhookDeliveryAttempt

router = APIRouter()

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DeadLetterItem(BaseModel):
    model_config = _ALIAS_CFG

    id: int
    event_id: str
    event_type: str
    attempt_num: int
    attempted_at: datetime
    error_detail: str | None


class DeadLettersResponse(BaseModel):
    model_config = _ALIAS_CFG

    items: list[DeadLetterItem]
    total: int


@router.get(
    "/webhooks/dead-letters",
    response_model=DeadLettersResponse,
    response_model_by_alias=False,
    summary="List unresolved dead-lettered Stripe webhook events",
)
async def list_dead_letters(
    db: AsyncSession = Depends(get_db),
) -> DeadLettersResponse:
    """Return webhook events that exhausted all retry attempts.

    Each item represents the final failed delivery attempt for a Stripe event.
    Ordered newest-first by ``attempted_at``.
    """
    result = await db.execute(
        select(WebhookDeliveryAttempt)
        .where(WebhookDeliveryAttempt.is_dead_letter.is_(True))
        .order_by(WebhookDeliveryAttempt.attempted_at.desc())
    )
    rows = result.scalars().all()

    items = [
        DeadLetterItem(
            id=row.id,
            event_id=row.event_id,
            event_type=row.event_type,
            attempt_num=row.attempt_num,
            attempted_at=row.attempted_at,
            error_detail=row.error_detail,
        )
        for row in rows
    ]
    return DeadLettersResponse(items=items, total=len(items))
