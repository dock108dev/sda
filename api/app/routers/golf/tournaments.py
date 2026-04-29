"""Golf tournament endpoints."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.golf import (
    GolfLeaderboard,
    GolfPlayer,
    GolfRound,
    GolfTournament,
    GolfTournamentField,
)

from . import router

_SYNTHETIC_DG_ID_START = 900_000


@router.get("/tournaments/upcoming")
async def list_upcoming_tournaments(
    days_ahead: int = Query(90, ge=1, le=365, description="Lookahead window in days"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List tournaments starting within the next `days_ahead` days.

    Each result includes field_available: true when DataGolf field data exists.
    Intended for the pool creation form tournament selector.
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    stmt = (
        select(GolfTournament)
        .where(GolfTournament.start_date >= today)
        .where(GolfTournament.start_date <= cutoff)
        .order_by(GolfTournament.start_date.asc())
    )
    result = await db.execute(stmt)
    tournaments = result.scalars().all()

    # Batch-fetch field counts for all matched tournaments.
    field_counts: dict[int, int] = {}
    t_ids = [t.id for t in tournaments]
    if t_ids:
        count_stmt = (
            select(GolfTournamentField.tournament_id, sa_func.count(GolfTournamentField.dg_id))
            .where(GolfTournamentField.tournament_id.in_(t_ids))
            .group_by(GolfTournamentField.tournament_id)
        )
        count_result = await db.execute(count_stmt)
        for row in count_result:
            field_counts[row[0]] = row[1]

    return {
        "tournaments": [
            {
                "tournament_id": t.id,
                "name": t.event_name,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "end_date": t.end_date.isoformat() if t.end_date else None,
                "field_available": field_counts.get(t.id, 0) > 0,
            }
            for t in tournaments
        ],
        "count": len(tournaments),
    }


@router.get("/tournaments")
async def list_tournaments(
    tour: str | None = Query(None, description="Filter by tour (e.g. pga, euro)"),
    season: int | None = Query(None, description="Filter by season year"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List golf tournaments with optional filters."""
    stmt = select(GolfTournament).order_by(GolfTournament.start_date.desc()).limit(limit)

    if tour:
        stmt = stmt.where(GolfTournament.tour == tour)
    if season:
        stmt = stmt.where(GolfTournament.season == season)
    if status:
        stmt = stmt.where(GolfTournament.status == status)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "tournaments": [
            {
                "id": t.id,
                "event_id": t.event_id,
                "tour": t.tour,
                "event_name": t.event_name,
                "course": t.course,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "end_date": t.end_date.isoformat() if t.end_date else None,
                "season": t.season,
                "purse": t.purse,
                "currency": t.currency,
                "country": t.country,
                "status": t.status,
                "current_round": t.current_round,
            }
            for t in rows
        ],
        "count": len(rows),
    }


@router.get("/tournaments/{event_id}")
async def get_tournament(
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get tournament detail by event_id."""
    stmt = select(GolfTournament).where(GolfTournament.event_id == event_id)
    result = await db.execute(stmt)
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {
        "id": t.id,
        "event_id": t.event_id,
        "tour": t.tour,
        "event_name": t.event_name,
        "course": t.course,
        "course_key": t.course_key,
        "start_date": t.start_date.isoformat() if t.start_date else None,
        "end_date": t.end_date.isoformat() if t.end_date else None,
        "season": t.season,
        "purse": t.purse,
        "currency": t.currency,
        "country": t.country,
        "latitude": t.latitude,
        "longitude": t.longitude,
        "status": t.status,
        "current_round": t.current_round,
    }


@router.get("/tournaments/{event_id}/field")
async def get_tournament_field(
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the entry list / field for a tournament."""
    # Resolve tournament
    t_result = await db.execute(
        select(GolfTournament.id).where(GolfTournament.event_id == event_id)
    )
    tournament_id = t_result.scalar_one_or_none()
    if tournament_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    stmt = select(GolfTournamentField).where(
        GolfTournamentField.tournament_id == tournament_id
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "event_id": event_id,
        "field": [
            {
                "dg_id": f.dg_id,
                "player_name": f.player_name,
                "status": f.status,
                "tee_time_r1": f.tee_time_r1,
                "tee_time_r2": f.tee_time_r2,
                "early_late": f.early_late,
                "course": f.course,
                "dk_salary": f.dk_salary,
                "fd_salary": f.fd_salary,
            }
            for f in rows
        ],
        "count": len(rows),
    }


class AddFieldPlayerRequest(BaseModel):
    player_name: str = Field(..., description="Player name in 'Last, First' format")


@router.post("/tournaments/{event_id}/field")
async def add_field_player(
    event_id: str,
    req: AddFieldPlayerRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add a player to the tournament field by name.

    Creates the player in golf_players if they don't exist.
    """
    t_result = await db.execute(
        select(GolfTournament.id).where(GolfTournament.event_id == event_id)
    )
    tournament_id = t_result.scalar_one_or_none()
    if tournament_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    name = req.player_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="player_name is required")

    # Check if already in field
    existing = await db.execute(
        select(GolfTournamentField).where(
            GolfTournamentField.tournament_id == tournament_id,
            sa_func.lower(GolfTournamentField.player_name) == name.lower(),
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"{name} is already in the field")

    # Find or create player
    player_result = await db.execute(
        select(GolfPlayer).where(
            sa_func.lower(GolfPlayer.player_name) == name.lower()
        )
    )
    player = player_result.scalars().first()

    if player:
        dg_id = player.dg_id
    else:
        max_result = await db.execute(
            select(sa_func.coalesce(sa_func.max(GolfPlayer.dg_id), _SYNTHETIC_DG_ID_START - 1)).where(
                GolfPlayer.dg_id >= _SYNTHETIC_DG_ID_START
            )
        )
        dg_id = (max_result.scalar() or _SYNTHETIC_DG_ID_START - 1) + 1
        db.add(GolfPlayer(dg_id=dg_id, player_name=name, amateur=False))
        await db.flush()

    db.add(GolfTournamentField(
        tournament_id=tournament_id,
        dg_id=dg_id,
        player_name=name,
        status="active",
    ))
    await db.flush()

    return {"status": "added", "dg_id": dg_id, "player_name": name}


@router.delete("/tournaments/{event_id}/field/{dg_id}")
async def remove_field_player(
    event_id: str,
    dg_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Remove a player from the tournament field."""
    t_result = await db.execute(
        select(GolfTournament.id).where(GolfTournament.event_id == event_id)
    )
    tournament_id = t_result.scalar_one_or_none()
    if tournament_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    entry = await db.execute(
        select(GolfTournamentField).where(
            GolfTournamentField.tournament_id == tournament_id,
            GolfTournamentField.dg_id == dg_id,
        )
    )
    row = entry.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Player not in field")

    player_name = row.player_name
    await db.delete(row)

    return {"status": "removed", "dg_id": dg_id, "player_name": player_name}


@router.get("/tournaments/{event_id}/leaderboard")
async def get_tournament_leaderboard(
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current or final leaderboard for a tournament."""
    t_result = await db.execute(
        select(GolfTournament.id).where(GolfTournament.event_id == event_id)
    )
    tournament_id = t_result.scalar_one_or_none()
    if tournament_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    stmt = (
        select(GolfLeaderboard)
        .where(GolfLeaderboard.tournament_id == tournament_id)
        .order_by(GolfLeaderboard.position.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "event_id": event_id,
        "leaderboard": [
            {
                "dg_id": lb.dg_id,
                "player_name": lb.player_name,
                "position": lb.position,
                "total_score": lb.total_score,
                "today_score": lb.today_score,
                "thru": lb.thru,
                "total_strokes": lb.total_strokes,
                "r1": lb.r1,
                "r2": lb.r2,
                "r3": lb.r3,
                "r4": lb.r4,
                "status": lb.status,
                "sg_total": lb.sg_total,
                "sg_ott": lb.sg_ott,
                "sg_app": lb.sg_app,
                "sg_arg": lb.sg_arg,
                "sg_putt": lb.sg_putt,
                "win_prob": lb.win_prob,
                "top_5_prob": lb.top_5_prob,
                "top_10_prob": lb.top_10_prob,
                "make_cut_prob": lb.make_cut_prob,
            }
            for lb in rows
        ],
        "count": len(rows),
    }


@router.get("/tournaments/{event_id}/rounds")
async def get_tournament_rounds(
    event_id: str,
    round_num: int | None = Query(None, description="Filter by round number"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get round-by-round scoring for a tournament."""
    t_result = await db.execute(
        select(GolfTournament.id).where(GolfTournament.event_id == event_id)
    )
    tournament_id = t_result.scalar_one_or_none()
    if tournament_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    stmt = select(GolfRound).where(GolfRound.tournament_id == tournament_id)
    if round_num is not None:
        stmt = stmt.where(GolfRound.round_num == round_num)
    stmt = stmt.order_by(GolfRound.round_num, GolfRound.score)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "event_id": event_id,
        "rounds": [
            {
                "dg_id": r.dg_id,
                "round_num": r.round_num,
                "score": r.score,
                "strokes": r.strokes,
                "sg_total": r.sg_total,
                "sg_ott": r.sg_ott,
                "sg_app": r.sg_app,
                "sg_arg": r.sg_arg,
                "sg_putt": r.sg_putt,
                "driving_dist": r.driving_dist,
                "driving_acc": r.driving_acc,
                "gir": r.gir,
                "scrambling": r.scrambling,
                "prox": r.prox,
                "putts_per_round": r.putts_per_round,
            }
            for r in rows
        ],
        "count": len(rows),
    }
