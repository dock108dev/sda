"""Golf pool public endpoints — entry submission, leaderboard, lookup."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
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

from . import router
from .pools_helpers import (
    get_pool_or_404,
    serialize_entry,
    serialize_pick,
    serialize_pool,
)

# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get("/pools")
async def list_pools(
    club_code: str | None = Query(None, description="Filter by club code"),
    tournament_id: int | None = Query(None, description="Filter by tournament"),
    status: str | None = Query(None, description="Filter by status"),
    active_only: bool = Query(False, description="Only open/live pools"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List golf pools with optional filters."""
    stmt = select(GolfPool).order_by(GolfPool.created_at.desc()).limit(limit)

    if club_code:
        stmt = stmt.where(GolfPool.club_code == club_code)
    if tournament_id is not None:
        stmt = stmt.where(GolfPool.tournament_id == tournament_id)
    if status:
        stmt = stmt.where(GolfPool.status == status)
    if active_only:
        stmt = stmt.where(GolfPool.status.in_(["open", "locked", "live"]))

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "pools": [serialize_pool(p) for p in rows],
        "count": len(rows),
    }


@router.get("/pools/{pool_id}")
async def get_pool(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get pool detail with rules and tournament info."""
    pool = await get_pool_or_404(pool_id, db)

    t_result = await db.execute(
        select(GolfTournament.event_name, GolfTournament.event_id).where(
            GolfTournament.id == pool.tournament_id
        )
    )
    tournament = t_result.one_or_none()

    data = serialize_pool(pool)
    data["tournament"] = {
        "event_name": tournament.event_name if tournament else None,
        "event_id": tournament.event_id if tournament else None,
    }
    return data


@router.get("/pools/{pool_id}/field")
async def get_pool_field(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the player field for a pool.

    For bucketed pools (Crestmont), returns players grouped by bucket.
    For flat pools (RVCC), returns a flat list.
    """
    pool = await get_pool_or_404(pool_id, db)
    rules_json = pool.rules_json or {}
    uses_buckets = rules_json.get("uses_buckets", False)

    if uses_buckets:
        bucket_result = await db.execute(
            select(GolfPoolBucket).where(GolfPoolBucket.pool_id == pool_id).order_by(
                GolfPoolBucket.bucket_number
            )
        )
        buckets = bucket_result.scalars().all()

        bucket_data = []
        for b in buckets:
            player_result = await db.execute(
                select(GolfPoolBucketPlayer).where(
                    GolfPoolBucketPlayer.bucket_id == b.id
                )
            )
            players = player_result.scalars().all()
            bucket_data.append({
                "bucket_number": b.bucket_number,
                "label": b.label,
                "players": [
                    {"dg_id": pl.dg_id, "player_name": pl.player_name_snapshot}
                    for pl in players
                ],
            })

        return {"pool_id": pool_id, "format": "bucketed", "buckets": bucket_data}

    stmt = select(GolfTournamentField).where(
        GolfTournamentField.tournament_id == pool.tournament_id
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "pool_id": pool_id,
        "format": "flat",
        "field": [
            {"dg_id": f.dg_id, "player_name": f.player_name, "status": f.status}
            for f in rows
        ],
        "count": len(rows),
    }

# Import companion entry routes for registration on the shared golf router.
from . import pools_entries as _pools_entries  # noqa: E402,F401


@router.get("/pools/{pool_id}/entries/by-email")
async def get_entries_by_email(
    pool_id: int,
    email: str = Query(..., description="Email to look up"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get all entries for an email address in a pool."""
    await get_pool_or_404(pool_id, db)

    stmt = select(GolfPoolEntry).where(
        GolfPoolEntry.pool_id == pool_id,
        GolfPoolEntry.email == email.lower(),
    ).order_by(GolfPoolEntry.entry_number)
    result = await db.execute(stmt)
    entries = result.scalars().all()

    entries_data = []
    for entry in entries:
        picks_result = await db.execute(
            select(GolfPoolEntryPick).where(GolfPoolEntryPick.entry_id == entry.id).order_by(
                GolfPoolEntryPick.pick_slot
            )
        )
        picks = picks_result.scalars().all()
        entries_data.append({
            "id": entry.id,
            "pool_id": entry.pool_id,
            "email": entry.email,
            "entry_name": entry.entry_name,
            "picks": [
                {"pick_slot": pk.pick_slot, "player_name": pk.player_name_snapshot}
                for pk in picks
            ],
        })

    return {"entries": entries_data, "count": len(entries_data)}


@router.get("/pools/{pool_id}/leaderboard")
async def get_pool_leaderboard(
    pool_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the materialized leaderboard for a pool."""
    await get_pool_or_404(pool_id, db)

    stmt = (
        select(GolfPoolEntryScore, GolfPoolEntry.email, GolfPoolEntry.entry_name)
        .join(GolfPoolEntry, GolfPoolEntry.id == GolfPoolEntryScore.entry_id)
        .where(GolfPoolEntryScore.pool_id == pool_id)
        .order_by(
            GolfPoolEntryScore.rank.asc().nullslast(),
            GolfPoolEntryScore.aggregate_score.asc().nullslast(),
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    leaderboard = []
    for score, email, entry_name in rows:
        player_result = await db.execute(
            select(GolfPoolEntryScorePlayer).where(
                GolfPoolEntryScorePlayer.entry_id == score.entry_id,
                GolfPoolEntryScorePlayer.pool_id == pool_id,
            ).order_by(GolfPoolEntryScorePlayer.pick_slot)
        )
        players = player_result.scalars().all()

        leaderboard.append({
            "entry_id": score.entry_id,
            "email": email,
            "entry_name": entry_name,
            "aggregate_score": score.aggregate_score,
            "qualified_golfers_count": score.qualified_golfers_count,
            "counted_golfers_count": score.counted_golfers_count,
            "qualification_status": score.qualification_status,
            "is_complete": score.is_complete,
            "rank": score.rank,
            "is_tied": score.is_tied,
            "last_scored_at": score.last_scored_at.isoformat() if score.last_scored_at else None,
            "picks": [
                {
                    "dg_id": sp.dg_id,
                    "player_name": sp.player_name_snapshot,
                    "pick_slot": sp.pick_slot,
                    "bucket_number": sp.bucket_number,
                    "status": sp.status_snapshot,
                    "position": sp.position_snapshot,
                    "total_score": sp.total_score_snapshot,
                    "thru": sp.thru_snapshot,
                    "r1": sp.r1,
                    "r2": sp.r2,
                    "r3": sp.r3,
                    "r4": sp.r4,
                    "made_cut": sp.made_cut_snapshot,
                    "counts_toward_total": sp.counts_toward_total,
                    "is_dropped": sp.is_dropped,
                }
                for sp in players
            ],
        })

    return {"pool_id": pool_id, "leaderboard": leaderboard, "count": len(leaderboard)}


@router.get("/pools/{pool_id}/entries/{entry_id}")
async def get_entry_detail(
    pool_id: int,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get entry detail with picks and scoring."""
    await get_pool_or_404(pool_id, db)

    entry_result = await db.execute(
        select(GolfPoolEntry).where(
            GolfPoolEntry.id == entry_id,
            GolfPoolEntry.pool_id == pool_id,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    picks_result = await db.execute(
        select(GolfPoolEntryPick).where(GolfPoolEntryPick.entry_id == entry_id).order_by(
            GolfPoolEntryPick.pick_slot
        )
    )
    picks = picks_result.scalars().all()

    score_result = await db.execute(
        select(GolfPoolEntryScore).where(GolfPoolEntryScore.entry_id == entry_id)
    )
    score = score_result.scalar_one_or_none()

    score_players = []
    if score:
        sp_result = await db.execute(
            select(GolfPoolEntryScorePlayer).where(
                GolfPoolEntryScorePlayer.entry_id == entry_id
            ).order_by(GolfPoolEntryScorePlayer.pick_slot)
        )
        score_players = sp_result.scalars().all()

    data = serialize_entry(entry)
    data["picks"] = [serialize_pick(pk) for pk in picks]
    data["scoring"] = None
    if score:
        data["scoring"] = {
            "aggregate_score": score.aggregate_score,
            "qualified_golfers_count": score.qualified_golfers_count,
            "counted_golfers_count": score.counted_golfers_count,
            "qualification_status": score.qualification_status,
            "is_complete": score.is_complete,
            "rank": score.rank,
            "is_tied": score.is_tied,
            "last_scored_at": score.last_scored_at.isoformat() if score.last_scored_at else None,
            "players": [
                {
                    "dg_id": sp.dg_id,
                    "player_name": sp.player_name_snapshot,
                    "pick_slot": sp.pick_slot,
                    "bucket_number": sp.bucket_number,
                    "status": sp.status_snapshot,
                    "position": sp.position_snapshot,
                    "total_score": sp.total_score_snapshot,
                    "thru": sp.thru_snapshot,
                    "r1": sp.r1,
                    "r2": sp.r2,
                    "r3": sp.r3,
                    "r4": sp.r4,
                    "made_cut": sp.made_cut_snapshot,
                    "counts_toward_total": sp.counts_toward_total,
                    "is_dropped": sp.is_dropped,
                }
                for sp in score_players
            ],
        }
    return data
