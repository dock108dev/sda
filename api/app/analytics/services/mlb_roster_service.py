"""MLB roster service.

Fetches active batters and pitchers for MLB teams from the database,
with fallback to the MLB Stats API when no recent data is available.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_team_roster(
    team_abbreviation: str,
    *,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Fetch active batters and pitchers for a team over the last 30 days.

    Returns a dict with ``batters`` and ``pitchers`` lists built from
    recent final games. Returns ``None`` if the team cannot be found.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import cast, func, select
    from sqlalchemy.types import Float

    from app.db.mlb_advanced import MLBPlayerAdvancedStats
    from app.db.sports import (
        SportsGame,
        SportsLeague,
        SportsPlayerBoxscore,
        SportsTeam,
    )

    from datetime import UTC

    # Resolve team via MLB league (same pattern as get_team_rolling_profile)
    mlb_league_sq = (
        select(SportsLeague.id)
        .where(SportsLeague.code == "MLB")
        .scalar_subquery()
    )
    team_result = await db.execute(
        select(SportsTeam)
        .where(
            SportsTeam.abbreviation == team_abbreviation.upper(),
            SportsTeam.league_id == mlb_league_sq,
        )
        .limit(1)
    )
    team = team_result.scalar_one_or_none()
    if team is None:
        logger.warning(
            "team_not_found_for_roster",
            extra={"abbreviation": team_abbreviation},
        )
        return None

    # Try progressively wider windows: 30 days, 90 days, full season.
    # During the offseason the 30-day window will be empty, so we widen
    # until we find data.
    for lookback_days in (30, 90, 365):
        cutoff = datetime.now(tz=UTC) - timedelta(days=lookback_days)

        recent_games_sq = (
            select(SportsGame.id)
            .where(
                SportsGame.status == "final",
                SportsGame.game_date >= cutoff,
            )
            .scalar_subquery()
        )

        # --- Batters from MLBPlayerAdvancedStats ---
        batter_stmt = (
            select(
                MLBPlayerAdvancedStats.player_external_ref,
                MLBPlayerAdvancedStats.player_name,
                func.count().label("games_played"),
            )
            .where(
                MLBPlayerAdvancedStats.team_id == team.id,
                MLBPlayerAdvancedStats.game_id.in_(recent_games_sq),
            )
            .group_by(
                MLBPlayerAdvancedStats.player_external_ref,
                MLBPlayerAdvancedStats.player_name,
            )
            .order_by(func.count().desc())
        )
        batter_result = await db.execute(batter_stmt)
        batters = [
            {
                "external_ref": row.player_external_ref,
                "name": row.player_name,
                "games_played": row.games_played,
            }
            for row in batter_result.all()
        ]

        # --- Pitchers from SportsPlayerBoxscore ---
        pitcher_stmt = (
            select(
                SportsPlayerBoxscore.player_external_ref,
                SportsPlayerBoxscore.player_name,
                func.count().label("games"),
                func.avg(
                    cast(
                        SportsPlayerBoxscore.stats["inningsPitched"].as_float(),
                        Float,
                    )
                ).label("avg_ip"),
            )
            .where(
                SportsPlayerBoxscore.team_id == team.id,
                SportsPlayerBoxscore.game_id.in_(recent_games_sq),
                SportsPlayerBoxscore.stats["inningsPitched"].as_float() > 0,
            )
            .group_by(
                SportsPlayerBoxscore.player_external_ref,
                SportsPlayerBoxscore.player_name,
            )
        )
        pitcher_result = await db.execute(pitcher_stmt)
        pitchers = [
            {
                "external_ref": row.player_external_ref,
                "name": row.player_name,
                "games": row.games,
                "avg_ip": round(float(row.avg_ip), 2) if row.avg_ip else 0.0,
            }
            for row in pitcher_result.all()
        ]

        if batters or pitchers:
            break

    # If DB has no data at all, fall back to the MLB Stats API active roster.
    # Look up via profile_service module so mock.patch targets work.
    if not batters and not pitchers and team.external_ref:
        import app.analytics.services.profile_service as _ps

        fallback = await _ps._fetch_mlb_api_roster(team.external_ref)
        if fallback:
            return fallback

    return {"batters": batters, "pitchers": pitchers}


async def _fetch_mlb_api_roster(mlb_team_id: str) -> dict[str, Any] | None:
    """Fetch the active roster from the MLB Stats API.

    Uses ``/api/v1/teams/{id}/roster?rosterType=active`` which is
    public and requires no authentication.  Returns batters and pitchers
    in the same shape as the DB-backed ``get_team_roster``.
    """
    import httpx

    url = f"https://statsapi.mlb.com/api/v1/teams/{mlb_team_id}/roster?rosterType=active&hydrate=person"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("mlb_api_roster_fetch_failed", extra={"team_id": mlb_team_id})
        return None

    roster = data.get("roster", [])
    if not roster:
        return None

    batters: list[dict[str, Any]] = []
    pitchers: list[dict[str, Any]] = []

    for entry in roster:
        person = entry.get("person", {})
        player_id = str(person.get("id", ""))
        name = person.get("fullName", "")
        position_type = entry.get("position", {}).get("type", "")

        if not player_id or not name:
            continue

        if position_type == "Pitcher":
            pitchers.append({
                "external_ref": player_id,
                "name": name,
                "games": 0,
                "avg_ip": 0.0,
            })
        else:
            batters.append({
                "external_ref": player_id,
                "name": name,
                "games_played": 0,
            })

    return {"batters": batters, "pitchers": pitchers}
