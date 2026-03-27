"""NFL team drive profiles from advanced stats and boxscore data.

Builds rolling team profiles that capture offensive efficiency,
defensive pressure, and special teams quality. These profiles get
converted into drive outcome probabilities by ``nfl_drive_weights``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sports.nfl.constants import (
    BASELINE_CPOE,
    BASELINE_EPA_PER_PLAY,
    BASELINE_EXPLOSIVE_RATE,
    BASELINE_PASS_RATE,
    BASELINE_SACK_RATE,
    BASELINE_SUCCESS_RATE,
    BASELINE_TURNOVER_RATE,
)

logger = logging.getLogger(__name__)

_MIN_GAMES = 3


async def build_nfl_team_profile(
    db: AsyncSession,
    team_id: int,
    rolling_window: int = 8,
) -> dict[str, float] | None:
    """Build a rolling drive profile from team advanced stats.

    Combines ``NFLGameAdvancedStats`` (EPA, success rate, pass/rush
    splits) with ESPN boxscore JSONB data (defensive stats, kicking,
    turnovers) over the last ``rolling_window`` games.

    Returns:
        Dict of team metrics or ``None`` if insufficient data.
    """
    from app.db.nfl_advanced import NFLGameAdvancedStats
    from app.db.sports import SportsGame

    # Get recent team-level advanced stats
    stmt = (
        select(NFLGameAdvancedStats)
        .join(SportsGame, SportsGame.id == NFLGameAdvancedStats.game_id)
        .where(
            NFLGameAdvancedStats.team_id == team_id,
            SportsGame.status.in_(["final", "archived"]),
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if len(rows) < _MIN_GAMES:
        return None

    # Average the team-level EPA metrics
    profile: dict[str, float] = {}

    float_fields = [
        "epa_per_play", "pass_epa", "rush_epa",
        "success_rate", "pass_success_rate", "rush_success_rate",
        "explosive_play_rate", "avg_cpoe", "avg_air_yards", "avg_yac",
    ]
    for field in float_fields:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        if vals:
            profile[field] = round(sum(vals) / len(vals), 4)

    # Pass rate from play counts
    total_pass = sum(r.pass_plays or 0 for r in rows)
    total_rush = sum(r.rush_plays or 0 for r in rows)
    total_plays = total_pass + total_rush
    if total_plays > 0:
        profile["pass_rate"] = round(total_pass / total_plays, 4)

    # Enrich with defensive stats from boxscore JSONB
    def_profile = await _get_defensive_profile(db, team_id, rows)
    if def_profile:
        profile.update(def_profile)

    # Enrich with kicking/special teams from boxscore
    st_profile = await _get_special_teams_profile(db, team_id, rows)
    if st_profile:
        profile.update(st_profile)

    profile["games_found"] = len(rows)
    return profile


async def _get_defensive_profile(
    db: AsyncSession,
    team_id: int,
    adv_rows: list,
) -> dict[str, float] | None:
    """Aggregate defensive stats from ESPN boxscore JSONB.

    Looks at the OPPOSING team's boxscore for games where this team
    played, extracting sacks, TFL, QB hits per game.
    """
    from app.db.sports import SportsGame, SportsPlayerBoxscore

    game_ids = [r.game_id for r in adv_rows]
    if not game_ids:
        return None

    # Get opposing team IDs for each game
    games_stmt = select(SportsGame).where(SportsGame.id.in_(game_ids))
    games_result = await db.execute(games_stmt)
    games = {g.id: g for g in games_result.scalars().all()}

    total_sacks = 0.0
    total_tfl = 0.0
    total_qb_hits = 0.0
    total_turnovers_forced = 0.0
    game_count = 0

    for r in adv_rows:
        game = games.get(r.game_id)
        if not game:
            continue

        # This team's defense faces the opposing offense
        # Defensive stats are stored under THIS team's players
        box_stmt = (
            select(SportsPlayerBoxscore)
            .where(
                SportsPlayerBoxscore.game_id == r.game_id,
                SportsPlayerBoxscore.team_id == team_id,
            )
        )
        box_result = await db.execute(box_stmt)
        boxes = box_result.scalars().all()

        game_sacks = 0.0
        game_tfl = 0.0
        game_qb_hits = 0.0
        game_ints = 0.0

        for box in boxes:
            stats = box.stats or {}
            cat = stats.get("category", "")
            if cat == "defensive":
                game_sacks += float(stats.get("SACKS", 0) or 0)
                game_tfl += float(stats.get("TFL", 0) or 0)
                game_qb_hits += float(stats.get("QB HTS", 0) or 0)
            elif cat == "interceptions":
                game_ints += float(stats.get("INT", 0) or 0)

        total_sacks += game_sacks
        total_tfl += game_tfl
        total_qb_hits += game_qb_hits
        total_turnovers_forced += game_ints
        game_count += 1

    if game_count == 0:
        return None

    return {
        "def_sacks_per_game": round(total_sacks / game_count, 2),
        "def_tfl_per_game": round(total_tfl / game_count, 2),
        "def_qb_hits_per_game": round(total_qb_hits / game_count, 2),
        "def_turnovers_forced_per_game": round(total_turnovers_forced / game_count, 2),
    }


async def _get_special_teams_profile(
    db: AsyncSession,
    team_id: int,
    adv_rows: list,
) -> dict[str, float] | None:
    """Aggregate kicking stats from ESPN boxscore JSONB."""
    from app.db.sports import SportsPlayerBoxscore

    game_ids = [r.game_id for r in adv_rows]
    if not game_ids:
        return None

    total_fg_made = 0
    total_fg_att = 0

    for gid in game_ids:
        box_stmt = (
            select(SportsPlayerBoxscore)
            .where(
                SportsPlayerBoxscore.game_id == gid,
                SportsPlayerBoxscore.team_id == team_id,
            )
        )
        box_result = await db.execute(box_stmt)
        boxes = box_result.scalars().all()

        for box in boxes:
            stats = box.stats or {}
            if stats.get("category") == "kicking":
                fg_str = stats.get("FG", "0/0")
                if "/" in str(fg_str):
                    parts = str(fg_str).split("/")
                    try:
                        total_fg_made += int(parts[0])
                        total_fg_att += int(parts[1])
                    except (ValueError, IndexError):
                        pass

    fg_pct = total_fg_made / total_fg_att if total_fg_att > 0 else 0.85

    return {
        "fg_pct": round(fg_pct, 4),
    }
