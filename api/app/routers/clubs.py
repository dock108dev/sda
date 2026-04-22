"""Public club lookup endpoint — no authentication required."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.club import Club
from app.db.golf_pools import GolfPool

router = APIRouter(prefix="/api/v1/clubs", tags=["clubs"])

_ACTIVE_POOL_STATUSES = ("open", "locked", "live")


def _serialize_pool(p: GolfPool) -> dict[str, Any]:
    return {
        "pool_id": p.id,
        "name": p.name,
        "status": p.status,
        "tournament_id": p.tournament_id,
        "entry_deadline": p.entry_deadline.isoformat() if p.entry_deadline else None,
        "allow_self_service_entry": p.allow_self_service_entry,
    }


@router.get("/{slug}")
async def get_club_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return club info and active pools for a given slug.

    Returns 404 if the slug is unknown or the club status is not 'active'.
    No authentication required — suitable for public club landing pages.
    """
    result = await db.execute(select(Club).where(Club.slug == slug))
    club = result.scalar_one_or_none()

    if club is None or club.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Club not found",
        )

    pools_result = await db.execute(
        select(GolfPool)
        .where(
            GolfPool.club_id == club.id,
            GolfPool.status.in_(_ACTIVE_POOL_STATUSES),
        )
        .order_by(GolfPool.created_at.desc())
    )
    active_pools = pools_result.scalars().all()

    payload: dict[str, Any] = {
        "club_id": club.club_id,
        "name": club.name,
        "slug": club.slug,
        "active_pools": [_serialize_pool(p) for p in active_pools],
    }
    if club.branding_json:
        payload["branding"] = club.branding_json
    return payload
