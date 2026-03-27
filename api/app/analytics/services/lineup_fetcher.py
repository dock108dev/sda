"""Fetch probable lineups for upcoming MLB games.

For scheduled/pregame games where PBP doesn't exist yet:

- **Probable pitcher:** Fetched from the MLB Stats API schedule endpoint
  which publishes probable starters typically 1-2 days before game time.
- **Batting order:** Uses the team's most recent actual lineup
  reconstructed from their last completed game's PBP.  MLB teams
  typically run similar lineups game to game, making this a reasonable
  proxy.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def fetch_probable_starter(
    game_date: date,
    team_external_ref: str,
) -> dict[str, str] | None:
    """Fetch the probable starting pitcher from the MLB Stats API.

    The schedule endpoint ``/api/v1/schedule`` with
    ``hydrate=probablePitcher`` returns announced starters for each game.

    Args:
        game_date: Date of the game.
        team_external_ref: MLB Stats API team ID (e.g., ``"147"``).

    Returns:
        ``{"external_ref": str, "name": str}`` or ``None`` if not
        announced or API unavailable.
    """
    import httpx

    date_str = game_date.isoformat()
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?date={date_str}&sportId=1&hydrate=probablePitcher"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.warning(
            "probable_pitcher_api_failed",
            extra={"date": date_str, "team_ref": team_external_ref},
        )
        return None

    for game_date_entry in data.get("dates", []):
        for game in game_date_entry.get("games", []):
            # Check if this team is home or away
            teams = game.get("teams", {})
            for side in ("home", "away"):
                team_data = teams.get(side, {})
                team_info = team_data.get("team", {})
                if str(team_info.get("id", "")) == str(team_external_ref):
                    pitcher = team_data.get("probablePitcher", {})
                    pitcher_id = str(pitcher.get("id", ""))
                    pitcher_name = pitcher.get("fullName", "")
                    if pitcher_id:
                        return {
                            "external_ref": pitcher_id,
                            "name": pitcher_name,
                        }
    return None


async def fetch_recent_lineup(
    db: AsyncSession,
    team_id: int,
    before_game_id: int | None = None,
) -> list[dict[str, str]] | None:
    """Get the team's most recent batting order from PBP.

    Looks at the team's last completed game and reconstructs the
    starting lineup from play-by-play data.

    Args:
        db: Async database session.
        team_id: Team ID.
        before_game_id: If provided, only consider games before this one
            (prevents using the same game we're simulating).

    Returns:
        List of ``{"external_ref": str, "name": str}`` in batting order,
        or ``None`` if no recent PBP data found.
    """
    from app.db.sports import SportsGame

    # Find the team's most recent final game with PBP
    stmt = (
        select(SportsGame.id)
        .where(
            SportsGame.status.in_(["final", "archived"]),
            (SportsGame.home_team_id == team_id) | (SportsGame.away_team_id == team_id),
        )
        .order_by(SportsGame.game_date.desc())
        .limit(1)
    )
    if before_game_id is not None:
        stmt = stmt.where(SportsGame.id != before_game_id)

    result = await db.execute(stmt)
    recent_game_id = result.scalar_one_or_none()

    if recent_game_id is None:
        return None

    from app.analytics.services.lineup_reconstruction import (
        reconstruct_lineup_from_pbp,
    )

    lineup_data = await reconstruct_lineup_from_pbp(db, recent_game_id, team_id)
    if lineup_data is None:
        return None

    return lineup_data["batters"]


async def get_team_external_ref(
    db: AsyncSession,
    team_id: int,
) -> str | None:
    """Look up a team's MLB Stats API ID from the DB."""
    from app.db.sports import SportsTeam

    stmt = select(SportsTeam.external_ref).where(SportsTeam.id == team_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
