"""Golf pool admin endpoints — create, update, delete, buckets, CSV upload/export."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.club import Club
from app.db.golf import GolfTournament, GolfTournamentField
from app.db.golf_pools import (
    GolfPool,
    GolfPoolBucket,
    GolfPoolBucketPlayer,
)
from app.dependencies.roles import require_admin
from app.services.entitlement import EntitlementService
from app.services.pool_lifecycle import ACTION_MAP, PoolStateMachine, TransitionError

from . import router
from .pools_helpers import (
    BucketCreateRequest,
    PoolCreateRequest,
    PoolUpdateRequest,
    get_pool_or_404,
    serialize_pool,
)

_CSV_BATCH = 500

# Maps the target status string to the ACTION_MAP key used by PoolStateMachine.
_STATUS_TO_ACTION: dict[str, str] = {v.value: k for k, v in ACTION_MAP.items()}

_entitlement = EntitlementService()


# ---------------------------------------------------------------------------
# Pool CRUD
# ---------------------------------------------------------------------------


@router.post("/pools")
async def create_pool(
    req: PoolCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new golf pool."""
    t_result = await db.execute(
        select(GolfTournament.id).where(GolfTournament.id == req.tournament_id)
    )
    if t_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    club_result = await db.execute(select(Club).where(Club.slug == req.club_code))
    club = club_result.scalar_one_or_none()
    if club is not None:
        await _entitlement.check_pool_limit(club.id, db)

    pool = GolfPool(
        code=req.code,
        name=req.name,
        club_code=req.club_code,
        tournament_id=req.tournament_id,
        status=req.status,
        rules_json=req.rules_json,
        entry_deadline=datetime.fromisoformat(req.entry_deadline) if req.entry_deadline else None,
        entry_open_at=datetime.fromisoformat(req.entry_open_at) if req.entry_open_at else None,
        max_entries_per_email=req.max_entries_per_email,
        scoring_enabled=req.scoring_enabled,
        require_upload=req.require_upload,
        allow_self_service_entry=req.allow_self_service_entry,
        notes=req.notes,
    )
    db.add(pool)
    await db.flush()
    await db.refresh(pool)
    return {"status": "created", **serialize_pool(pool)}


@router.patch("/pools/{pool_id}")
async def update_pool(
    pool_id: int,
    req: PoolUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a pool."""
    pool = await get_pool_or_404(pool_id, db)

    if req.name is not None:
        pool.name = req.name
    if req.status is not None:
        action = _STATUS_TO_ACTION.get(req.status)
        if action is None:
            raise HTTPException(status_code=400, detail=f"Cannot transition pool to status {req.status!r} via PATCH")
        try:
            await PoolStateMachine(pool, db).transition(action)
        except TransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    if req.rules_json is not None:
        pool.rules_json = req.rules_json
    if req.entry_deadline is not None:
        pool.entry_deadline = datetime.fromisoformat(req.entry_deadline)
    if req.entry_open_at is not None:
        pool.entry_open_at = datetime.fromisoformat(req.entry_open_at)
    if req.max_entries_per_email is not None:
        pool.max_entries_per_email = req.max_entries_per_email
    if req.scoring_enabled is not None:
        pool.scoring_enabled = req.scoring_enabled
    if req.require_upload is not None:
        pool.require_upload = req.require_upload
    if req.allow_self_service_entry is not None:
        pool.allow_self_service_entry = req.allow_self_service_entry
    if req.notes is not None:
        pool.notes = req.notes

    await db.flush()
    await db.refresh(pool)
    return {"status": "updated", **serialize_pool(pool)}


@router.delete("/pools/{pool_id}")
async def delete_pool(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a pool and all related data (cascades)."""
    pool = await get_pool_or_404(pool_id, db)
    name = pool.name
    await db.delete(pool)
    return {"status": "deleted", "id": pool_id, "name": name}


@router.post("/pools/{pool_id}/duplicate", status_code=201)
async def duplicate_pool(
    pool_id: int,
    club_code: str = Query(..., description="Club code of the requesting club — must match the pool's club"),
    db: AsyncSession = Depends(get_db),
    _role: str = Depends(require_admin),
) -> JSONResponse:
    """Clone structural fields of a pool into a new draft pool.

    Temporal and state fields are reset: tournament_id=null, entry_open_at=null,
    entry_deadline=null, status=draft, code=new UUID. Entries, picks, and
    standings are NOT copied. Returns 201 with a Location header.
    """
    pool = await get_pool_or_404(pool_id, db)

    if pool.club_code != club_code:
        raise HTTPException(status_code=403, detail="Pool belongs to a different club")

    new_pool = GolfPool(
        code=uuid.uuid4().hex[:12],
        name=f"{pool.name} (Copy)",
        club_code=pool.club_code,
        club_id=pool.club_id,
        tournament_id=None,
        status="draft",
        rules_json=pool.rules_json,
        entry_open_at=None,
        entry_deadline=None,
        scoring_enabled=pool.scoring_enabled,
        max_entries_per_email=pool.max_entries_per_email,
        require_upload=pool.require_upload,
        allow_self_service_entry=pool.allow_self_service_entry,
        notes=pool.notes,
    )
    db.add(new_pool)
    await db.flush()
    await db.refresh(new_pool)

    return JSONResponse(
        status_code=201,
        content={"result": "created", **serialize_pool(new_pool)},
        headers={"Location": f"/pools/{new_pool.id}/setup"},
    )


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------


@router.post("/pools/{pool_id}/buckets")
async def create_or_replace_buckets(
    pool_id: int,
    req: BucketCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create or replace bucket assignments for a pool (Crestmont)."""
    pool = await get_pool_or_404(pool_id, db)

    existing = await db.execute(
        select(GolfPoolBucket.id).where(GolfPoolBucket.pool_id == pool_id)
    )
    existing_ids = [row.id for row in existing]
    if existing_ids:
        await db.execute(
            delete(GolfPoolBucketPlayer).where(
                GolfPoolBucketPlayer.bucket_id.in_(existing_ids)
            )
        )
        await db.execute(
            delete(GolfPoolBucket).where(GolfPoolBucket.pool_id == pool_id)
        )
        await db.flush()

    created_count = 0
    for bucket_item in req.buckets:
        bucket = GolfPoolBucket(
            pool_id=pool.id,
            bucket_number=bucket_item.bucket_number,
            label=bucket_item.label,
        )
        db.add(bucket)
        await db.flush()
        await db.refresh(bucket)

        for player in bucket_item.players:
            db.add(
                GolfPoolBucketPlayer(
                    bucket_id=bucket.id,
                    dg_id=player.dg_id,
                    player_name_snapshot=player.player_name,
                )
            )
            created_count += 1

    await db.flush()
    return {
        "status": "created",
        "pool_id": pool_id,
        "buckets_count": len(req.buckets),
        "players_count": created_count,
    }

# Import companion routes for registration on the shared golf router.
from . import pools_admin_entries as _pools_admin_entries  # noqa: E402,F401
