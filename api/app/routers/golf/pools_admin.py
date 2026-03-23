"""Golf pool admin endpoints — create, update, delete, buckets, CSV upload."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fastapi import Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.golf import GolfTournament, GolfTournamentField
from app.db.golf_pools import (
    GolfPool,
    GolfPoolBucket,
    GolfPoolBucketPlayer,
    GolfPoolEntry,
)

from . import router
from .pools_helpers import (
    BucketCreateRequest,
    PickRequest,
    PoolCreateRequest,
    PoolUpdateRequest,
    count_entries_for_email,
    create_entry_and_picks,
    get_player_names,
    get_pool_or_404,
    serialize_entry,
    serialize_pool,
    validate_entry_picks,
)


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
        pool.status = req.status
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


# ---------------------------------------------------------------------------
# Entry management
# ---------------------------------------------------------------------------


@router.get("/pools/{pool_id}/entries")
async def admin_list_entries(
    pool_id: int,
    email: str | None = Query(None, description="Filter by email"),
    status: str | None = Query(None, description="Filter by status"),
    source: str | None = Query(None, description="Filter by source"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Admin: list all entries for a pool with optional filters."""
    await get_pool_or_404(pool_id, db)

    stmt = (
        select(GolfPoolEntry)
        .where(GolfPoolEntry.pool_id == pool_id)
        .order_by(GolfPoolEntry.created_at.desc())
        .limit(limit)
    )
    if email:
        stmt = stmt.where(GolfPoolEntry.email == email.lower())
    if status:
        stmt = stmt.where(GolfPoolEntry.status == status)
    if source:
        stmt = stmt.where(GolfPoolEntry.source == source)

    result = await db.execute(stmt)
    entries = result.scalars().all()
    return {
        "entries": [serialize_entry(e) for e in entries],
        "count": len(entries),
    }


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


@router.post("/pools/{pool_id}/rescore")
async def trigger_rescore(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger manual rescoring for a pool via Celery."""
    await get_pool_or_404(pool_id, db)  # validates pool exists

    from app.celery_client import get_celery_app

    celery = get_celery_app()
    task = celery.send_task(
        "rescore_golf_pool",
        args=[pool_id],
        queue="sports-scraper",
    )
    return {"status": "dispatched", "pool_id": pool_id, "task_id": task.id}


@router.post("/pools/{pool_id}/lock")
async def lock_pool(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Lock pool entries (set status to locked)."""
    pool = await get_pool_or_404(pool_id, db)
    pool.status = "locked"
    await db.flush()
    await db.refresh(pool)
    return {"status": "locked", **serialize_pool(pool)}


# ---------------------------------------------------------------------------
# CSV Upload
# ---------------------------------------------------------------------------


@router.post("/pools/{pool_id}/entries/upload")
async def upload_entries_csv(
    pool_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Bulk import entries from a CSV file.

    Expected CSV columns: email, entry_name, pick_1, pick_2, ..., pick_N
    where pick values are dg_id integers.
    """
    pool = await get_pool_or_404(pool_id, db)
    rules_json = pool.rules_json or {}
    uses_buckets = rules_json.get("uses_buckets", False)
    pick_count = rules_json.get("pick_count", 7)

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    results: list[dict[str, Any]] = []
    created_count = 0
    error_count = 0

    field_result = await db.execute(
        select(GolfTournamentField.dg_id).where(
            GolfTournamentField.tournament_id == pool.tournament_id
        )
    )
    valid_dg_ids = {row.dg_id for row in field_result}
    player_names = await get_player_names(list(valid_dg_ids), db)

    for row_num, row in enumerate(reader, start=2):
        row_errors: list[str] = []
        email = (row.get("email") or "").strip().lower()
        entry_name = (row.get("entry_name") or "").strip() or None

        if not email:
            row_errors.append("Missing email")
            results.append({"row": row_num, "status": "error", "errors": row_errors})
            error_count += 1
            continue

        picks: list[PickRequest] = []
        for slot in range(1, pick_count + 1):
            dg_id_str = (row.get(f"pick_{slot}") or "").strip()
            if not dg_id_str:
                row_errors.append(f"Missing pick_{slot}")
                continue
            try:
                dg_id = int(dg_id_str)
            except ValueError:
                row_errors.append(f"Invalid pick_{slot}: {dg_id_str}")
                continue

            bucket_number = None
            if uses_buckets:
                bucket_str = (row.get(f"pick_{slot}_bucket") or "").strip()
                if bucket_str:
                    try:
                        bucket_number = int(bucket_str)
                    except ValueError:
                        row_errors.append(f"Invalid pick_{slot}_bucket: {bucket_str}")
                        continue

            picks.append(PickRequest(dg_id=dg_id, pick_slot=slot, bucket_number=bucket_number))

        if row_errors:
            results.append({"row": row_num, "status": "error", "errors": row_errors})
            error_count += 1
            continue

        validation_errors = await validate_entry_picks(pool, picks, player_names, db)
        if validation_errors:
            results.append({"row": row_num, "status": "error", "errors": validation_errors})
            error_count += 1
            continue

        if pool.max_entries_per_email:
            count = await count_entries_for_email(pool_id, email, db)
            if count >= pool.max_entries_per_email:
                results.append({
                    "row": row_num,
                    "status": "error",
                    "errors": [f"Max entries ({pool.max_entries_per_email}) reached for {email}"],
                })
                error_count += 1
                continue

        entry = await create_entry_and_picks(
            pool, email, entry_name, picks, player_names, db,
            source="csv_upload", upload_filename=file.filename,
        )
        results.append({"row": row_num, "status": "created", "entry_id": entry.id})
        created_count += 1

    return {
        "status": "completed",
        "pool_id": pool_id,
        "filename": file.filename,
        "created": created_count,
        "errors": error_count,
        "total_rows": created_count + error_count,
        "details": results,
    }
