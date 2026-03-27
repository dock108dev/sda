"""NCAAB rotation reconstruction from game data.

Identifies starter and bench units from ``NCAABPlayerAdvancedStats``
using minutes played.  Top 5 by minutes = starters; rest = bench.

For future games, falls back to the team's most recent completed game.
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
    """Extract starter/bench units from player advanced stats.

    Returns:
        ``{"starters": [...], "bench": [...], "starter_minutes_share": float}``
        or ``None`` if insufficient data.
    """
    from app.db.ncaab_advanced import NCAABPlayerAdvancedStats

    stmt = (
        select(NCAABPlayerAdvancedStats)
        .where(
            NCAABPlayerAdvancedStats.game_id == game_id,
            NCAABPlayerAdvancedStats.team_id == team_id,
        )
        .order_by(NCAABPlayerAdvancedStats.minutes.desc().nullslast())
    )
    result = await db.execute(stmt)
    players = result.scalars().all()

    if len(players) < 5:
        return None

    active = [p for p in players if p.minutes and p.minutes > 0]
    if len(active) < 5:
        return None

    starters = [
        {
            "external_ref": p.player_external_ref,
            "name": p.player_name,
            "minutes": float(p.minutes),
        }
        for p in active[:5]
    ]
    bench = [
        {
            "external_ref": p.player_external_ref,
            "name": p.player_name,
            "minutes": float(p.minutes),
        }
        for p in active[5:]
    ]

    total_minutes = sum(p.minutes for p in active)
    starter_minutes = sum(s["minutes"] for s in starters)
    starter_share = starter_minutes / total_minutes if total_minutes > 0 else 0.70

    return {
        "starters": starters,
        "bench": bench,
        "starter_minutes_share": round(starter_share, 3),
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
