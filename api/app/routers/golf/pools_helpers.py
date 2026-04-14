"""Shared models, serializers, and helpers for golf pool endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.golf import GolfTournamentField
from app.db.golf_pools import (
    GolfPool,
    GolfPoolBucket,
    GolfPoolBucketPlayer,
    GolfPoolEntry,
    GolfPoolEntryPick,
)
from app.services.golf_pool_scoring import Pick, rules_from_json, validate_picks


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class PickRequest(BaseModel):
    dg_id: int
    pick_slot: int
    bucket_number: int | None = None
    player_name: str | None = Field(None, description="For write-in 'other' picks (dg_id=0): player name in 'Last, First' format")


class EntrySubmitRequest(BaseModel):
    email: str = Field(..., description="Entrant email address")
    entry_name: str | None = Field(None, description="Display name for the entry")
    picks: list[PickRequest] = Field(..., description="List of golfer picks")


class PoolCreateRequest(BaseModel):
    code: str = Field(..., description="Unique pool code within tournament")
    name: str = Field(..., description="Display name")
    club_code: str = Field(..., description="Club identifier (e.g. rvcc, crestmont)")
    tournament_id: int = Field(..., description="FK to golf_tournaments.id")
    rules_json: dict[str, Any] | None = Field(None, description="Pool rules as JSON")
    entry_deadline: str | None = Field(None, description="ISO datetime for entry cutoff")
    entry_open_at: str | None = Field(None, description="ISO datetime when entries open")
    status: str = Field("draft", description="Pool status")
    max_entries_per_email: int | None = None
    scoring_enabled: bool = False
    require_upload: bool = False
    allow_self_service_entry: bool = True
    notes: str | None = None


class PoolUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    rules_json: dict[str, Any] | None = None
    entry_deadline: str | None = None
    entry_open_at: str | None = None
    max_entries_per_email: int | None = None
    scoring_enabled: bool | None = None
    require_upload: bool | None = None
    allow_self_service_entry: bool | None = None
    notes: str | None = None


class BucketPlayerItem(BaseModel):
    dg_id: int
    player_name: str


class BucketItem(BaseModel):
    bucket_number: int
    label: str | None = None
    players: list[BucketPlayerItem]


class BucketCreateRequest(BaseModel):
    buckets: list[BucketItem] = Field(..., description="Bucket definitions with players")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_pool(p: GolfPool) -> dict[str, Any]:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "club_code": p.club_code,
        "tournament_id": p.tournament_id,
        "status": p.status,
        "rules_json": p.rules_json,
        "entry_open_at": p.entry_open_at.isoformat() if p.entry_open_at else None,
        "entry_deadline": p.entry_deadline.isoformat() if p.entry_deadline else None,
        "scoring_enabled": p.scoring_enabled,
        "max_entries_per_email": p.max_entries_per_email,
        "require_upload": p.require_upload,
        "allow_self_service_entry": p.allow_self_service_entry,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def serialize_entry(e: GolfPoolEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "pool_id": e.pool_id,
        "email": e.email,
        "entry_name": e.entry_name,
        "entry_number": e.entry_number,
        "status": e.status,
        "source": e.source,
        "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def serialize_pick(pk: GolfPoolEntryPick) -> dict[str, Any]:
    return {
        "id": pk.id,
        "dg_id": pk.dg_id,
        "player_name": pk.player_name_snapshot,
        "pick_slot": pk.pick_slot,
        "bucket_number": pk.bucket_number,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_pool_or_404(pool_id: int, db: AsyncSession) -> GolfPool:
    pool = await db.get(GolfPool, pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool not found")
    return pool


async def get_player_names(dg_ids: list[int], db: AsyncSession) -> dict[int, str]:
    """Resolve dg_ids to player names from the tournament field."""
    if not dg_ids:
        return {}
    result = await db.execute(
        select(GolfTournamentField.dg_id, GolfTournamentField.player_name).where(
            GolfTournamentField.dg_id.in_(dg_ids)
        )
    )
    return {row.dg_id: row.player_name or f"Player {row.dg_id}" for row in result}


async def get_bucket_players(pool_id: int, db: AsyncSession) -> dict[int, set[int]]:
    """Return {bucket_number: {dg_id, ...}} for a pool."""
    result = await db.execute(
        select(GolfPoolBucket.bucket_number, GolfPoolBucketPlayer.dg_id)
        .join(GolfPoolBucketPlayer, GolfPoolBucketPlayer.bucket_id == GolfPoolBucket.id)
        .where(GolfPoolBucket.pool_id == pool_id)
    )
    mapping: dict[int, set[int]] = {}
    for row in result:
        mapping.setdefault(row.bucket_number, set()).add(row.dg_id)
    return mapping


async def count_entries_for_email(pool_id: int, email: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(sa_func.count(GolfPoolEntry.id)).where(
            GolfPoolEntry.pool_id == pool_id,
            GolfPoolEntry.email == email.lower(),
        )
    )
    return result.scalar() or 0


async def next_entry_number(pool_id: int, email: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(sa_func.coalesce(sa_func.max(GolfPoolEntry.entry_number), 0)).where(
            GolfPoolEntry.pool_id == pool_id,
            GolfPoolEntry.email == email.lower(),
        )
    )
    return (result.scalar() or 0) + 1


def _strip_trailing_duplicate_suffix(name: str) -> str:
    """Strip trailing `` (N)`` suffixes (N decimal digits), iteratively.

    Replaces a regex on entry names to avoid ReDoS on uncontrolled input; work
    is linear in string length.
    """
    s = name.rstrip()
    while s.endswith(")"):
        open_idx = s.rfind("(")
        if open_idx < 0:
            break
        inner = s[open_idx + 1 : -1].strip()
        if not inner.isdigit():
            break
        s = s[:open_idx].rstrip()
    return s


async def _dedup_entry_names(pool_id: int, entry_name: str | None, db: AsyncSession) -> None:
    """Number duplicate entry names within a pool.

    When multiple entries share the same name (case-insensitive), all of
    them get a suffix: ``Name (1)``, ``Name (2)``, etc., ordered by
    ``created_at``.  The first entry to be submitted gets ``(1)``.
    """
    if not entry_name:
        return

    # Find all entries in this pool with the same base name (case-insensitive).
    # Strip any existing " (N)" suffix before comparing so re-runs are idempotent.
    result = await db.execute(
        select(GolfPoolEntry)
        .where(
            GolfPoolEntry.pool_id == pool_id,
        )
        .order_by(GolfPoolEntry.created_at)
    )
    all_entries = result.scalars().all()

    def _base_name(name: str | None) -> str:
        if not name:
            return ""
        return _strip_trailing_duplicate_suffix(name).strip().lower()

    target_base = _base_name(entry_name)
    if not target_base:
        return

    dupes = [e for e in all_entries if _base_name(e.entry_name) == target_base]

    if len(dupes) < 2:
        return

    # Get the canonical casing from the first entry's base name
    canonical = _strip_trailing_duplicate_suffix(dupes[0].entry_name or "").strip()

    for i, entry in enumerate(dupes, 1):
        new_name = f"{canonical} ({i})"
        if entry.entry_name != new_name:
            entry.entry_name = new_name

    await db.flush()


async def create_entry_and_picks(
    pool: GolfPool,
    email: str,
    entry_name: str | None,
    picks: list[PickRequest],
    player_names: dict[int, str],
    db: AsyncSession,
    *,
    source: str = "self_service",
    upload_filename: str | None = None,
) -> GolfPoolEntry:
    """Create a GolfPoolEntry + GolfPoolEntryPick rows atomically."""
    entry_number = await next_entry_number(pool.id, email, db)
    entry = GolfPoolEntry(
        pool_id=pool.id,
        email=email.lower(),
        entry_name=entry_name,
        entry_number=entry_number,
        status="submitted",
        source=source,
        upload_filename=upload_filename,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)

    for pk in picks:
        db.add(
            GolfPoolEntryPick(
                entry_id=entry.id,
                dg_id=pk.dg_id,
                player_name_snapshot=player_names.get(pk.dg_id, f"Player {pk.dg_id}"),
                pick_slot=pk.pick_slot,
                bucket_number=pk.bucket_number,
            )
        )
    await db.flush()

    # Number duplicate entry names: "Mike" + "Mike" → "Mike (1)", "Mike (2)"
    await _dedup_entry_names(pool.id, entry_name, db)
    await db.refresh(entry)

    return entry


async def validate_entry_picks(
    pool: GolfPool,
    picks: list[PickRequest],
    player_names: dict[int, str],
    db: AsyncSession,
) -> list[str]:
    """Validate picks against pool rules.  Returns list of error strings."""
    rules_json = pool.rules_json or {}
    if not rules_json.get("variant"):
        return ["Pool has no rules configured"]

    rules = rules_from_json(rules_json)
    scoring_picks = [
        Pick(
            dg_id=pk.dg_id,
            player_name=player_names.get(pk.dg_id, f"Player {pk.dg_id}"),
            pick_slot=pk.pick_slot,
            bucket_number=pk.bucket_number,
        )
        for pk in picks
    ]

    field_result = await db.execute(
        select(GolfTournamentField.dg_id).where(
            GolfTournamentField.tournament_id == pool.tournament_id
        )
    )
    valid_dg_ids = {row.dg_id for row in field_result}

    bucket_players = None
    if rules.uses_buckets:
        bucket_players = await get_bucket_players(pool.id, db)

    return validate_picks(scoring_picks, rules, valid_dg_ids, bucket_players)
