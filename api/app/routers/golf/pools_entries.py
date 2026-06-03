"""Golf pool entry submission and write-in field routes."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.audit as audit
from app.db import get_db
from app.db.golf import GolfPlayer, GolfTournamentField
from app.db.golf_pools import GolfPool
from app.services.entitlement import EntitlementService
from app.services.entry_rate_limit import (
    ENTRY_RATE_WINDOW_SECONDS,
    check_entry_rate_limit,
)

from . import router
from .pools_helpers import (
    EntrySubmitRequest,
    count_entries_for_email,
    create_entry_and_picks,
    get_player_names,
    get_pool_or_404,
    validate_entry_picks,
)

_entitlement = EntitlementService()


# Synthetic dg_id range — matches scraper/scripts/setup_masters_pool.py
_SYNTHETIC_DG_ID_START = 900_000


class AddOtherPlayerRequest(BaseModel):
    player_name: str = Field(..., description="Player name in 'Last, First' format")


@router.post("/pools/{pool_id}/field/other")
async def add_other_player(
    pool_id: int,
    req: AddOtherPlayerRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add an 'other' player to a pool's tournament field by name.

    Creates the player in golf_players (with a synthetic dg_id) if they
    don't already exist, then adds them to the tournament field.  Returns
    the dg_id so the frontend can use it in a normal entry submission.

    Player name should be in 'Last, First' format.
    """
    pool = await get_pool_or_404(pool_id, db)
    name = req.player_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="player_name is required")

    # Check if this player already exists in the field (case-insensitive)
    existing = await db.execute(
        select(GolfTournamentField).where(
            GolfTournamentField.tournament_id == pool.tournament_id,
            sa_func.lower(GolfTournamentField.player_name) == name.lower(),
        )
    )
    existing_row = existing.scalars().first()
    if existing_row:
        return {
            "status": "existing",
            "dg_id": existing_row.dg_id,
            "player_name": existing_row.player_name,
        }

    # Check if player exists in golf_players by name
    player_result = await db.execute(
        select(GolfPlayer).where(
            sa_func.lower(GolfPlayer.player_name) == name.lower()
        )
    )
    player = player_result.scalars().first()

    if player:
        dg_id = player.dg_id
    else:
        # Create with synthetic dg_id
        max_result = await db.execute(
            select(sa_func.coalesce(sa_func.max(GolfPlayer.dg_id), _SYNTHETIC_DG_ID_START - 1)).where(
                GolfPlayer.dg_id >= _SYNTHETIC_DG_ID_START
            )
        )
        next_id = (max_result.scalar() or _SYNTHETIC_DG_ID_START - 1) + 1

        new_player = GolfPlayer(
            dg_id=next_id,
            player_name=name,
            amateur=False,
        )
        db.add(new_player)
        await db.flush()
        dg_id = next_id

    # Add to tournament field
    field_entry = GolfTournamentField(
        tournament_id=pool.tournament_id,
        dg_id=dg_id,
        player_name=name,
        status="active",
    )
    db.add(field_entry)
    await db.flush()

    return {
        "status": "added",
        "dg_id": dg_id,
        "player_name": name,
    }


async def _resolve_write_in_picks(
    pool: GolfPool,
    picks: list,
    db: AsyncSession,
) -> list:
    """Resolve write-in picks (dg_id=0 with player_name).

    For each write-in, find or create the player and add them to the
    tournament field, then swap in the real dg_id.  Returns the updated
    picks list with all dg_ids resolved.
    """
    resolved = []
    for pk in picks:
        if pk.dg_id != 0 or not pk.player_name:
            resolved.append(pk)
            continue

        name = pk.player_name.strip()
        if not name:
            resolved.append(pk)
            continue

        # Check if already in the field (case-insensitive)
        existing = await db.execute(
            select(GolfTournamentField).where(
                GolfTournamentField.tournament_id == pool.tournament_id,
                sa_func.lower(GolfTournamentField.player_name) == name.lower(),
            )
        )
        existing_row = existing.scalars().first()

        if existing_row:
            pk.dg_id = existing_row.dg_id
            resolved.append(pk)
            continue

        # Check if player exists in golf_players by name
        player_result = await db.execute(
            select(GolfPlayer).where(
                sa_func.lower(GolfPlayer.player_name) == name.lower()
            )
        )
        player = player_result.scalars().first()

        if player:
            dg_id = player.dg_id
        else:
            # Create with synthetic dg_id
            max_result = await db.execute(
                select(sa_func.coalesce(sa_func.max(GolfPlayer.dg_id), _SYNTHETIC_DG_ID_START - 1)).where(
                    GolfPlayer.dg_id >= _SYNTHETIC_DG_ID_START
                )
            )
            dg_id = (max_result.scalar() or _SYNTHETIC_DG_ID_START - 1) + 1
            db.add(GolfPlayer(dg_id=dg_id, player_name=name, amateur=False))
            await db.flush()

        # Add to tournament field
        db.add(GolfTournamentField(
            tournament_id=pool.tournament_id,
            dg_id=dg_id,
            player_name=name,
            status="active",
        ))
        await db.flush()

        pk.dg_id = dg_id
        resolved.append(pk)

    return resolved


_DEFAULT_MAX_ENTRIES_PER_EMAIL = 3


@router.post("/pools/{pool_id}/entries", status_code=201)
async def submit_entry(
    pool_id: int,
    req: EntrySubmitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Submit a pool entry with picks.

    Write-in picks: send ``dg_id: 0`` with ``player_name: "Last, First"``
    and the backend will resolve/create the player automatically.
    """
    # Honeypot: bots populate hidden ``website`` field. Return 201 silently
    # without persisting so they can't distinguish success from rejection.
    if req.website:
        return JSONResponse(
            status_code=201,
            content={"status": "submitted", "entry": None},
        )

    pool = await get_pool_or_404(pool_id, db)

    client_ip = request.client.host if request.client else "unknown"
    club_key = pool.club_code or (
        f"club:{pool.club_id}" if pool.club_id is not None else f"pool:{pool_id}"
    )
    allowed, retry_after = await check_entry_rate_limit(club_key, client_ip, pool_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many entry submissions. Please try again later.",
            headers={"Retry-After": str(retry_after or ENTRY_RATE_WINDOW_SECONDS)},
        )

    if pool.status not in ("open", "draft"):
        raise HTTPException(status_code=400, detail="Pool is not accepting entries")

    if pool.entry_deadline and datetime.now(UTC) > pool.entry_deadline:
        raise HTTPException(status_code=400, detail="Entry deadline has passed")

    effective_max = (
        pool.max_entries_per_email
        if pool.max_entries_per_email is not None
        else _DEFAULT_MAX_ENTRIES_PER_EMAIL
    )
    count = await count_entries_for_email(pool_id, req.email, db)
    if count >= effective_max:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ENTRY_LIMIT_EXCEEDED",
                "message": f"Maximum {effective_max} entries per email reached",
                "max_entries_per_email": effective_max,
            },
        )

    if pool.club_id is not None:
        await _entitlement.check_entry_limit(pool.club_id, pool_id, db)

    # Resolve write-in picks (dg_id=0) before validation
    req.picks = await _resolve_write_in_picks(pool, req.picks, db)

    dg_ids = [pk.dg_id for pk in req.picks]
    player_names = await get_player_names(dg_ids, db)

    errors = await validate_entry_picks(pool, req.picks, player_names, db)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    entry = await create_entry_and_picks(pool, req.email, req.entry_name, req.picks, player_names, db)

    # 1% sample to avoid audit volume from high-frequency entry submissions.
    if random.random() < 0.01:
        audit.emit(
            "entry_submitted",
            actor_type="user",
            club_id=pool.club_id,
            resource_type="entry",
            resource_id=str(entry.id),
            payload={"pool_id": pool.id},
        )

    picks_response = [
        {"pick_slot": pk.pick_slot, "player_name": player_names.get(pk.dg_id, pk.player_name or f"Player {pk.dg_id}")}
        for pk in req.picks
    ]

    return {
        "status": "submitted",
        "entry": {
            "id": entry.id,
            "pool_id": entry.pool_id,
            "email": entry.email,
            "entry_name": entry.entry_name,
            "picks": picks_response,
        },
    }
