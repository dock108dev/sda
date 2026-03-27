"""NHL rotation reconstruction from game data.

Identifies top-line and depth units from ``NHLSkaterAdvancedStats``
using time-on-ice.  Top 10 skaters by TOI (typically top-6F + top-4D)
form the starter unit; remaining skaters form the depth unit.

Starting goalie identified from ``NHLGoalieAdvancedStats`` by most
shots faced.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def reconstruct_rotation_from_stats(
    db: AsyncSession,
    game_id: int,
    team_id: int,
) -> dict[str, Any] | None:
    """Extract top-line/depth units and starting goalie.

    Returns:
        ``{"starters": [...], "bench": [...], "starter_minutes_share": float,
           "goalie": {"external_ref", "name", "save_pct"} | None}``
        or ``None`` if insufficient data.
    """
    from app.db.nhl_advanced import NHLGoalieAdvancedStats, NHLSkaterAdvancedStats

    # Skaters sorted by TOI
    stmt = (
        select(NHLSkaterAdvancedStats)
        .where(
            NHLSkaterAdvancedStats.game_id == game_id,
            NHLSkaterAdvancedStats.team_id == team_id,
        )
        .order_by(NHLSkaterAdvancedStats.toi_minutes.desc().nullslast())
    )
    result = await db.execute(stmt)
    skaters = result.scalars().all()

    # Need TOI to rank — filter to those with it
    active = [s for s in skaters if s.toi_minutes and s.toi_minutes > 0]
    if len(active) < 6:
        return None

    # Top 10 by TOI = starter unit (top-6 forwards + top-4 defensemen)
    # If fewer than 10, take what we have
    split = min(10, len(active))
    starters = [
        {
            "external_ref": s.player_external_ref,
            "name": s.player_name,
            "toi_minutes": float(s.toi_minutes),
        }
        for s in active[:split]
    ]
    bench = [
        {
            "external_ref": s.player_external_ref,
            "name": s.player_name,
            "toi_minutes": float(s.toi_minutes),
        }
        for s in active[split:]
    ]

    total_toi = sum(s.toi_minutes for s in active)
    starter_toi = sum(s["toi_minutes"] for s in starters)
    starter_share = starter_toi / total_toi if total_toi > 0 else 0.65

    # Starting goalie (most shots against)
    goalie_stmt = (
        select(NHLGoalieAdvancedStats)
        .where(
            NHLGoalieAdvancedStats.game_id == game_id,
            NHLGoalieAdvancedStats.team_id == team_id,
        )
        .order_by(NHLGoalieAdvancedStats.shots_against.desc().nullslast())
        .limit(1)
    )
    goalie_result = await db.execute(goalie_stmt)
    goalie = goalie_result.scalar_one_or_none()

    goalie_info = None
    if goalie:
        goalie_info = {
            "external_ref": goalie.player_external_ref,
            "name": goalie.player_name,
            "save_pct": float(goalie.save_pct) if goalie.save_pct else None,
        }

    return {
        "starters": starters,
        "bench": bench,
        "starter_minutes_share": round(starter_share, 3),
        "goalie": goalie_info,
    }


async def get_recent_rotation(
    db: AsyncSession,
    team_id: int,
    exclude_game_id: int | None = None,
) -> dict[str, Any] | None:
    """Get the team's rotation from their most recent completed game."""
    from app.db.sports import SportsGame

    stmt = (
        select(SportsGame.id)
        .where(
            SportsGame.status.in_(["final", "archived"]),
            (SportsGame.home_team_id == team_id) | (SportsGame.away_team_id == team_id),
        )
        .order_by(SportsGame.game_date.desc())
        .limit(1)
    )
    if exclude_game_id is not None:
        stmt = stmt.where(SportsGame.id != exclude_game_id)

    result = await db.execute(stmt)
    recent_game_id = result.scalar_one_or_none()

    if recent_game_id is None:
        return None

    return await reconstruct_rotation_from_stats(db, recent_game_id, team_id)
