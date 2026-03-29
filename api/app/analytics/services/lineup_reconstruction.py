"""Reconstruct starting lineups from play-by-play data.

For completed MLB games, the batting order can be inferred from PBP:
the first 9 unique batters in play-index order form the starting lineup.
The starting pitcher comes from ``MLBPitcherGameStats.is_starter``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def reconstruct_lineup_from_pbp(
    db: AsyncSession,
    game_id: int,
    team_id: int,
) -> dict[str, Any] | None:
    """Extract starting batting order from play-by-play data.

    Walks through plays in chronological order, collecting unique batters
    by their first appearance.  The first 9 unique batters form the
    starting lineup in batting order.

    Args:
        db: Async database session.
        game_id: ID of the completed game.
        team_id: ID of the batting team.

    Returns:
        ``{"batters": [{"external_ref": str, "name": str}, ...], ...}``
        with up to 9 batters in order, or ``None`` if insufficient data.
    """
    from app.db.sports import SportsGamePlay

    stmt = (
        select(SportsGamePlay)
        .where(
            SportsGamePlay.game_id == game_id,
            SportsGamePlay.team_id == team_id,
        )
        .order_by(SportsGamePlay.play_index.asc())
    )
    result = await db.execute(stmt)
    plays = result.scalars().all()

    if not plays:
        # Fallback: derive batters from boxscore data
        return await _lineup_from_boxscores(db, game_id, team_id)

    # Walk plays in order, collecting unique batters by first appearance
    seen: set[str] = set()
    batters: list[dict[str, str]] = []

    for play in plays:
        raw = play.raw_data or {}
        matchup = raw.get("matchup", {})

        # Prefer structured matchup.batter from Stats API PBP
        batter_info = matchup.get("batter", {})
        batter_id = str(batter_info.get("id", "")) if batter_info else ""
        batter_name = batter_info.get("fullName", "") if batter_info else ""

        # Fallback to top-level play fields
        if not batter_id:
            batter_id = play.player_id or ""
        if not batter_name:
            batter_name = play.player_name or ""

        if not batter_id:
            continue

        # Only count completed plate appearances (has an event result)
        event = raw.get("event") or raw.get("result", {}).get("event", "")
        if not event:
            continue

        if batter_id not in seen:
            seen.add(batter_id)
            batters.append({
                "external_ref": batter_id,
                "name": batter_name,
            })
            if len(batters) >= 9:
                break

    if len(batters) < 3:
        logger.info(
            "lineup_reconstruction_incomplete_pbp",
            extra={
                "game_id": game_id,
                "team_id": team_id,
                "batters_found": len(batters),
            },
        )
        # Try boxscore fallback
        return await _lineup_from_boxscores(db, game_id, team_id)

    if len(batters) < 9:
        logger.info(
            "lineup_reconstruction_partial",
            extra={
                "game_id": game_id,
                "team_id": team_id,
                "batters_found": len(batters),
            },
        )

    return {"batters": batters}


async def _lineup_from_boxscores(
    db: AsyncSession,
    game_id: int,
    team_id: int,
) -> dict[str, Any] | None:
    """Derive a batting lineup from player boxscore records.

    Fallback for when play-by-play data is unavailable. Returns batters
    sorted by ``battingOrder`` from the boxscore JSONB (if present) or
    by at-bats descending.
    """
    from app.db.sports import SportsPlayerBoxscore

    stmt = (
        select(SportsPlayerBoxscore)
        .where(
            SportsPlayerBoxscore.game_id == game_id,
            SportsPlayerBoxscore.team_id == team_id,
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        logger.info(
            "lineup_boxscore_fallback_no_data",
            extra={"game_id": game_id, "team_id": team_id},
        )
        return None

    # Filter to batters (have at-bats or plate appearances in stats)
    batter_rows = []
    for row in rows:
        stats = row.stats or {}
        ab = stats.get("atBats", stats.get("at_bats", 0)) or 0
        pa = stats.get("plateAppearances", stats.get("plate_appearances", 0)) or 0
        if ab > 0 or pa > 0:
            batter_rows.append(row)

    if len(batter_rows) < 3:
        logger.info(
            "lineup_boxscore_fallback_insufficient",
            extra={
                "game_id": game_id,
                "team_id": team_id,
                "batters_found": len(batter_rows),
            },
        )
        return None

    # Sort by battingOrder if available, otherwise by at-bats descending
    def _sort_key(r):
        s = r.stats or {}
        order = s.get("battingOrder", s.get("batting_order", 999))
        if isinstance(order, (int, float)) and order < 900:
            return (0, order)
        ab = s.get("atBats", s.get("at_bats", 0)) or 0
        return (1, -ab)

    batter_rows.sort(key=_sort_key)

    batters = [
        {
            "external_ref": row.player_external_ref,
            "name": row.player_name,
        }
        for row in batter_rows[:9]
    ]

    logger.info(
        "lineup_boxscore_fallback_success",
        extra={
            "game_id": game_id,
            "team_id": team_id,
            "batters_found": len(batters),
        },
    )
    return {"batters": batters}


async def get_starting_pitcher(
    db: AsyncSession,
    game_id: int,
    team_id: int,
) -> dict[str, str] | None:
    """Get the starting pitcher for a team in a game.

    Uses ``MLBPitcherGameStats.is_starter`` when available, otherwise
    falls back to the pitcher with the most innings.

    Args:
        db: Async database session.
        game_id: ID of the game.
        team_id: ID of the pitching team.

    Returns:
        ``{"external_ref": str, "name": str, "avg_ip": float}``
        or ``None`` if no pitcher data found.
    """
    from app.db.mlb_advanced import MLBPitcherGameStats

    # Try is_starter flag first
    stmt = select(MLBPitcherGameStats).where(
        MLBPitcherGameStats.game_id == game_id,
        MLBPitcherGameStats.team_id == team_id,
        MLBPitcherGameStats.is_starter == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    starter = result.scalar_one_or_none()

    if starter:
        return {
            "external_ref": starter.player_external_ref,
            "name": starter.player_name,
            "avg_ip": float(starter.innings_pitched or 0),
        }

    # Fallback: pitcher with most innings in this game
    stmt = (
        select(MLBPitcherGameStats)
        .where(
            MLBPitcherGameStats.game_id == game_id,
            MLBPitcherGameStats.team_id == team_id,
        )
        .order_by(MLBPitcherGameStats.innings_pitched.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    pitcher = result.scalar_one_or_none()

    if pitcher:
        return {
            "external_ref": pitcher.player_external_ref,
            "name": pitcher.player_name,
            "avg_ip": float(pitcher.innings_pitched or 0),
        }

    # Final fallback: find pitcher from boxscore data
    from app.db.sports import SportsPlayerBoxscore

    box_stmt = (
        select(SportsPlayerBoxscore)
        .where(
            SportsPlayerBoxscore.game_id == game_id,
            SportsPlayerBoxscore.team_id == team_id,
        )
    )
    box_result = await db.execute(box_stmt)
    box_rows = box_result.scalars().all()

    # Look for player with most innings pitched in boxscore stats
    best_pitcher = None
    best_ip = 0.0
    for row in box_rows:
        stats = row.stats or {}
        ip = stats.get("inningsPitched", stats.get("innings_pitched", 0))
        try:
            ip = float(ip or 0)
        except (ValueError, TypeError):
            continue
        if ip > best_ip:
            best_ip = ip
            best_pitcher = row

    if best_pitcher and best_ip > 0:
        logger.info(
            "starting_pitcher_boxscore_fallback",
            extra={
                "game_id": game_id,
                "team_id": team_id,
                "pitcher": best_pitcher.player_name,
                "ip": best_ip,
            },
        )
        return {
            "external_ref": best_pitcher.player_external_ref,
            "name": best_pitcher.player_name,
            "avg_ip": best_ip,
        }

    return None
