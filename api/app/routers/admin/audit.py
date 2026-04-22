"""Admin audit log endpoint — GET /api/admin/audit."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.audit import AuditEvent

router = APIRouter()

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


class AuditEventResponse(BaseModel):
    model_config = _ALIAS_CFG

    id: int
    event_id: str
    event_type: str
    actor_type: str
    actor_id: str | None
    club_id: int | None
    resource_type: str
    resource_id: str
    payload: dict | None
    created_at: datetime


class AuditListResponse(BaseModel):
    model_config = _ALIAS_CFG

    events: list[AuditEventResponse]
    next_cursor: int | None


@router.get(
    "/audit",
    response_model=AuditListResponse,
    response_model_by_alias=False,
    summary="List audit events with optional filtering and cursor pagination",
)
async def list_audit_events(
    club_id: int | None = Query(None, description="Filter by club integer ID"),
    event_type: str | None = Query(None, description="Filter by event_type"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: int | None = Query(
        None,
        description="Pagination cursor — return events with id < cursor (newest-first)",
    ),
    db: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    """Return audit events in reverse-chronological order (newest first).

    Cursor-based pagination: pass the ``next_cursor`` from the previous
    response as ``cursor`` to retrieve the next page. Returns ``next_cursor:
    null`` when no further pages exist.
    """
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit + 1)

    if cursor is not None:
        stmt = stmt.where(AuditEvent.id < cursor)
    if club_id is not None:
        stmt = stmt.where(AuditEvent.club_id == club_id)
    if event_type is not None:
        stmt = stmt.where(AuditEvent.event_type == event_type)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = page[-1].id if has_more and page else None

    events = [
        AuditEventResponse(
            id=row.id,
            event_id=row.event_id,
            event_type=row.event_type,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            club_id=row.club_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            payload=row.payload,
            created_at=row.created_at,
        )
        for row in page
    ]

    return AuditListResponse(events=events, next_cursor=next_cursor)
