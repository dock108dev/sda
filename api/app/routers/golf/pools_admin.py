"""Golf pool admin endpoints — create, update, delete, buckets, CSV upload/export."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.club import Club
from app.db.golf import GolfTournament, GolfTournamentField
from app.db.golf_pools import (
    GolfPool,
    GolfPoolBucket,
    GolfPoolBucketPlayer,
    GolfPoolEntry,
    GolfPoolEntryPick,
    GolfPoolEntryScore,
    GolfPoolEntryScorePlayer,
)
from app.dependencies.roles import require_admin
from app.services.entitlement import EntitlementService
from app.services.pool_lifecycle import ACTION_MAP, PoolStateMachine, TransitionError

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

    # Load picks for all entries so we can include count + player names
    from app.db.golf_pools import GolfPoolEntryPick

    entry_ids = [e.id for e in entries]
    picks_by_entry: dict[int, list] = {}
    if entry_ids:
        picks_result = await db.execute(
            select(GolfPoolEntryPick)
            .where(GolfPoolEntryPick.entry_id.in_(entry_ids))
            .order_by(GolfPoolEntryPick.pick_slot)
        )
        for pk in picks_result.scalars().all():
            picks_by_entry.setdefault(pk.entry_id, []).append(pk)

    serialized = []
    for e in entries:
        entry_data = serialize_entry(e)
        picks = picks_by_entry.get(e.id, [])
        entry_data["picks_count"] = len(picks)
        entry_data["picks"] = [
            {"dg_id": pk.dg_id, "player_name": pk.player_name_snapshot, "pick_slot": pk.pick_slot}
            for pk in picks
        ]
        serialized.append(entry_data)

    return {
        "entries": serialized,
        "count": len(serialized),
    }


@router.delete("/pools/{pool_id}/entries/{entry_id}")
async def delete_entry(
    pool_id: int,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a single entry and all related data (picks, scores)."""
    await get_pool_or_404(pool_id, db)

    entry = await db.get(GolfPoolEntry, entry_id)
    if entry is None or entry.pool_id != pool_id:
        raise HTTPException(status_code=404, detail="Entry not found")

    email = entry.email
    entry_name = entry.entry_name

    # Delete related scoring data first (FK cascade should handle this,
    # but being explicit for clarity)
    await db.execute(
        delete(GolfPoolEntryScorePlayer).where(
            GolfPoolEntryScorePlayer.entry_id == entry_id
        )
    )
    await db.execute(
        delete(GolfPoolEntryScore).where(GolfPoolEntryScore.entry_id == entry_id)
    )
    await db.execute(
        delete(GolfPoolEntryPick).where(GolfPoolEntryPick.entry_id == entry_id)
    )
    await db.delete(entry)

    return {
        "status": "deleted",
        "entry_id": entry_id,
        "email": email,
        "entry_name": entry_name,
    }


@router.get("/pools/{pool_id}/entries/export")
async def export_entries_csv(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all entries with picks as a CSV download."""
    pool = await get_pool_or_404(pool_id, db)
    pick_count = (pool.rules_json or {}).get("pick_count", 7)

    # Load entries
    stmt = (
        select(GolfPoolEntry)
        .where(GolfPoolEntry.pool_id == pool_id)
        .order_by(GolfPoolEntry.created_at)
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    # Load all picks keyed by entry_id
    picks_stmt = (
        select(GolfPoolEntryPick)
        .where(
            GolfPoolEntryPick.entry_id.in_([e.id for e in entries])
        )
        .order_by(GolfPoolEntryPick.pick_slot)
    )
    picks_result = await db.execute(picks_stmt)
    all_picks = picks_result.scalars().all()

    picks_by_entry: dict[int, list] = {}
    for pk in all_picks:
        picks_by_entry.setdefault(pk.entry_id, []).append(pk)

    # Build CSV
    output = io.StringIO()
    pick_headers = []
    for i in range(1, pick_count + 1):
        pick_headers.extend([f"pick_{i}_name", f"pick_{i}_dg_id"])

    writer = csv.writer(output)
    writer.writerow([
        "entry_id", "email", "entry_name", "entry_number",
        "status", "source", "submitted_at",
        *pick_headers,
    ])

    for entry in entries:
        entry_picks = picks_by_entry.get(entry.id, [])
        pick_cells: list[str] = []
        for slot in range(1, pick_count + 1):
            pk = next((p for p in entry_picks if p.pick_slot == slot), None)
            if pk:
                pick_cells.extend([pk.player_name_snapshot, str(pk.dg_id)])
            else:
                pick_cells.extend(["", ""])

        writer.writerow([
            entry.id,
            entry.email,
            entry.entry_name or "",
            entry.entry_number,
            entry.status,
            entry.source,
            entry.submitted_at.isoformat() if entry.submitted_at else "",
            *pick_cells,
        ])

    csv_content = output.getvalue()
    filename = f"{pool.code}_entries.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _stream_entries_csv(
    pool_id: int,
    pick_count: int,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """Yield CSV chunks for pool entries in batches of _CSV_BATCH rows.

    Queries entries, picks, and scores in separate batches so the full
    dataset is never loaded into memory at once.
    """
    pick_headers = [f"pick_{i}" for i in range(1, pick_count + 1)]
    header_buf = io.StringIO()
    csv.writer(header_buf).writerow(["entry_id", "user_email", *pick_headers, "submitted_at", "score"])
    yield header_buf.getvalue()

    offset = 0
    while True:
        entries_stmt = (
            select(GolfPoolEntry)
            .where(GolfPoolEntry.pool_id == pool_id)
            .order_by(GolfPoolEntry.id)
            .offset(offset)
            .limit(_CSV_BATCH)
        )
        entries_result = await db.execute(entries_stmt)
        batch = entries_result.scalars().all()
        if not batch:
            break

        entry_ids = [e.id for e in batch]

        picks_result = await db.execute(
            select(GolfPoolEntryPick)
            .where(GolfPoolEntryPick.entry_id.in_(entry_ids))
            .order_by(GolfPoolEntryPick.pick_slot)
        )
        picks_by_entry: dict[int, list[GolfPoolEntryPick]] = {}
        for pk in picks_result.scalars().all():
            picks_by_entry.setdefault(pk.entry_id, []).append(pk)

        scores_result = await db.execute(
            select(GolfPoolEntryScore)
            .where(GolfPoolEntryScore.entry_id.in_(entry_ids))
        )
        scores_by_entry: dict[int, GolfPoolEntryScore] = {
            s.entry_id: s for s in scores_result.scalars().all()
        }

        chunk_buf = io.StringIO()
        writer = csv.writer(chunk_buf)
        for entry in batch:
            entry_picks = picks_by_entry.get(entry.id, [])
            pick_cells = []
            for slot in range(1, pick_count + 1):
                pk = next((p for p in entry_picks if p.pick_slot == slot), None)
                pick_cells.append(pk.player_name_snapshot if pk else "")

            score_obj = scores_by_entry.get(entry.id)
            score_val = score_obj.aggregate_score if score_obj is not None else ""

            writer.writerow([
                entry.id,
                entry.email,
                *pick_cells,
                entry.submitted_at.isoformat() if entry.submitted_at else "",
                "" if score_val is None else score_val,
            ])

        yield chunk_buf.getvalue()

        if len(batch) < _CSV_BATCH:
            break
        offset += _CSV_BATCH


@router.get("/pools/{pool_id}/export/entries.csv")
async def stream_entries_csv(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
    _role: str = Depends(require_admin),
) -> StreamingResponse:
    """Stream pool entries as CSV in batches of 500 rows.

    Columns: entry_id, user_email, pick_1..pick_N, submitted_at, score.
    Requires admin or pool-owner role.
    """
    pool = await get_pool_or_404(pool_id, db)
    pick_count = (pool.rules_json or {}).get("pick_count", 7)
    return StreamingResponse(
        _stream_entries_csv(pool_id, pick_count, db),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{pool.code}_entries.csv"',
            "X-Accel-Buffering": "no",
        },
    )


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


@router.post("/pools/{pool_id}/go-live")
async def go_live_pool(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Activate pool for live scoring (locked → live via state machine)."""
    pool = await get_pool_or_404(pool_id, db)
    try:
        await PoolStateMachine(pool, db).go_live()
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.refresh(pool)
    return {"status": "live", **serialize_pool(pool)}


@router.post("/pools/{pool_id}/lock")
async def lock_pool(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Lock pool entries (open → locked via state machine)."""
    pool = await get_pool_or_404(pool_id, db)
    try:
        await PoolStateMachine(pool, db).lock_pool()
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.refresh(pool)
    return {"status": "locked", **serialize_pool(pool)}


@router.post("/pools/{pool_id}/transitions/{action}")
async def pool_transition(
    pool_id: int,
    action: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Apply a named lifecycle transition to a pool.

    Valid actions: open, lock, go_live, finalize.
    Returns HTTP 409 on invalid or guard-failing transitions.
    """
    pool = await get_pool_or_404(pool_id, db)
    if action not in ACTION_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action {action!r}. Valid actions: {sorted(ACTION_MAP)}",
        )
    try:
        await PoolStateMachine(pool, db).transition(action)
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.refresh(pool)
    return {"action": action, "status": pool.status, **serialize_pool(pool)}


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
