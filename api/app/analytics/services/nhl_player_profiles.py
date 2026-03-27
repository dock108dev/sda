"""NHL per-player rolling profiles and unit-level probability derivation.

Builds rolling averages from ``NHLSkaterAdvancedStats`` and aggregates
into unit-level shot event probability distributions for the
rotation-aware simulator.  Incorporates opposing goalie save% to
adjust goal probability.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sports.nhl.constants import (
    BASELINE_SAVE_PCT,
    BASELINE_SHOOTING_PCT,
    DEFAULT_EVENT_PROBS,
)

logger = logging.getLogger(__name__)

_MIN_GAMES = 3


async def get_nhl_player_rolling_profile(
    db: AsyncSession,
    player_external_ref: str,
    team_id: int,
    rolling_window: int = 15,
) -> dict[str, float] | None:
    """Build a rolling average profile for an NHL skater.

    Returns dict of metric averages or ``None`` if insufficient data.
    """
    from app.db.nhl_advanced import NHLSkaterAdvancedStats
    from app.db.sports import SportsGame

    stmt = (
        select(NHLSkaterAdvancedStats)
        .join(SportsGame, SportsGame.id == NHLSkaterAdvancedStats.game_id)
        .where(
            NHLSkaterAdvancedStats.player_external_ref == player_external_ref,
            NHLSkaterAdvancedStats.team_id == team_id,
            SportsGame.status.in_(["final", "archived"]),
            NHLSkaterAdvancedStats.toi_minutes > 0,
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if len(rows) < _MIN_GAMES:
        return None

    profile: dict[str, float] = {}

    float_fields = [
        "toi_minutes", "xgoals_for", "xgoals_against",
        "shooting_pct", "goals_per_60", "shots_per_60",
        "game_score",
    ]
    for field in float_fields:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        if vals:
            profile[field] = round(sum(vals) / len(vals), 4)

    int_fields = ["shots", "goals"]
    for field in int_fields:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        if vals:
            profile[field] = round(sum(vals) / len(vals), 4)

    profile["games_found"] = len(rows)
    return profile


async def build_unit_probabilities(
    db: AsyncSession,
    players: list[dict[str, str]],
    team_id: int,
    opposing_goalie_save_pct: float | None = None,
    rolling_window: int = 15,
) -> dict[str, float]:
    """Aggregate skater profiles into unit-level shot event probabilities.

    Weights each player by their average TOI. Better shooters with
    more ice time contribute more to the unit's goal probability.

    Returns dict with ``goal_probability``, ``blocked_shot_probability``,
    ``missed_shot_probability``.
    """
    profiles: list[dict[str, float]] = []

    for p in players:
        ext_ref = p.get("external_ref", "")
        if ext_ref:
            prof = await get_nhl_player_rolling_profile(
                db, ext_ref, team_id, rolling_window,
            )
            if prof:
                profiles.append(prof)
                continue
        # Fallback: league-average
        profiles.append({
            "shooting_pct": BASELINE_SHOOTING_PCT * 100,  # stored as pct (9.0)
            "shots_per_60": 8.0,
            "toi_minutes": 15.0,
            "xgoals_for": 0.5,
        })

    if not profiles:
        return dict(DEFAULT_EVENT_PROBS)

    return _aggregate_to_shot_probs(profiles, opposing_goalie_save_pct)


def _aggregate_to_shot_probs(
    profiles: list[dict[str, float]],
    opposing_goalie_save_pct: float | None,
) -> dict[str, float]:
    """Convert skater profiles into shot event probabilities."""
    # Weight by TOI — players with more ice time contribute more
    total_toi = sum(p.get("toi_minutes", 15.0) for p in profiles)
    if total_toi <= 0:
        total_toi = len(profiles) * 15.0

    def _wavg(key: str, default: float) -> float:
        num = sum(
            p.get(key, default) * p.get("toi_minutes", 15.0) for p in profiles
        )
        return num / total_toi

    unit_shooting_pct = _wavg("shooting_pct", BASELINE_SHOOTING_PCT * 100)
    unit_xgoals = _wavg("xgoals_for", 0.5)

    # Normalize shooting_pct (may be stored as 0-100 or 0-1)
    if unit_shooting_pct > 1.0:
        unit_shooting_pct = unit_shooting_pct / 100.0

    # Adjust for opposing goalie
    # Better goalie (higher save%) → lower goal probability
    goalie_adj = 1.0
    if opposing_goalie_save_pct is not None:
        save_pct = opposing_goalie_save_pct
        if save_pct > 1.0:
            save_pct = save_pct / 100.0
        # Elite goalie (~0.925) reduces scoring; bad goalie (~0.890) increases it
        goalie_adj = (1.0 - save_pct) / (1.0 - BASELINE_SAVE_PCT)
        goalie_adj = max(0.70, min(1.30, goalie_adj))

    # xGoals adjustment — higher xGoals = better shot quality
    xg_adj = unit_xgoals / 0.5  # 0.5 xGF per skater per game is ~average
    xg_adj = max(0.85, min(1.15, xg_adj))

    goal_prob = unit_shooting_pct * goalie_adj * xg_adj
    goal_prob = max(0.03, min(0.18, goal_prob))

    # Blocked and missed rates stay relatively stable across units
    blocked = DEFAULT_EVENT_PROBS["blocked_shot"]
    missed = DEFAULT_EVENT_PROBS["missed_shot"]

    # Save absorbs remainder
    save_prob = max(0.0, 1.0 - goal_prob - blocked - missed)

    return {
        "goal_probability": round(goal_prob, 4),
        "blocked_shot_probability": round(blocked, 4),
        "missed_shot_probability": round(missed, 4),
    }
