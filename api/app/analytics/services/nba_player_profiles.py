"""NBA per-player rolling profiles and unit-level probability derivation.

Builds rolling averages of individual player stats from
``NBAPlayerAdvancedStats`` and aggregates them into unit-level
possession probability distributions for the rotation-aware simulator.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sports.nba.constants import (
    BASELINE_DEF_RATING,
    BASELINE_EFG_PCT,
    BASELINE_FT_PCT,
    BASELINE_OFF_RATING,
    BASELINE_TS_PCT,
    DEFAULT_EVENT_PROBS,
)

logger = logging.getLogger(__name__)

# Minimum games required for a player profile; below this we blend with team avg
_MIN_GAMES = 3


async def get_nba_player_rolling_profile(
    db: AsyncSession,
    player_external_ref: str,
    team_id: int,
    rolling_window: int = 15,
) -> dict[str, float] | None:
    """Build a rolling average profile for an NBA player.

    Queries the most recent ``rolling_window`` games from
    ``NBAPlayerAdvancedStats`` and averages the key metrics.

    Returns:
        Dict of metric averages or ``None`` if insufficient data.
    """
    from app.db.nba_advanced import NBAPlayerAdvancedStats
    from app.db.sports import SportsGame

    stmt = (
        select(NBAPlayerAdvancedStats)
        .join(SportsGame, SportsGame.id == NBAPlayerAdvancedStats.game_id)
        .where(
            NBAPlayerAdvancedStats.player_external_ref == player_external_ref,
            NBAPlayerAdvancedStats.team_id == team_id,
            SportsGame.status.in_(["final", "archived"]),
            NBAPlayerAdvancedStats.minutes > 0,
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if len(rows) < _MIN_GAMES:
        return None

    # Average the key fields
    fields = [
        "off_rating", "def_rating", "usg_pct", "ts_pct", "efg_pct",
        "minutes",
    ]

    profile: dict[str, float] = {}
    for field in fields:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        if vals:
            profile[field] = round(sum(vals) / len(vals), 4)

    # Derive shooting splits from raw FGA/FGM
    total_2pt_fga = sum(
        (r.contested_2pt_fga or 0) + (r.uncontested_2pt_fga or 0) for r in rows
    )
    total_2pt_fgm = sum(
        (r.contested_2pt_fgm or 0) + (r.uncontested_2pt_fgm or 0) for r in rows
    )
    total_3pt_fga = sum(
        (r.contested_3pt_fga or 0) + (r.uncontested_3pt_fga or 0) for r in rows
    )
    total_3pt_fgm = sum(
        (r.contested_3pt_fgm or 0) + (r.uncontested_3pt_fgm or 0) for r in rows
    )

    total_fga = total_2pt_fga + total_3pt_fga
    if total_fga > 0:
        profile["fg3_rate"] = round(total_3pt_fga / total_fga, 4)
        profile["fg2_rate"] = round(total_2pt_fga / total_fga, 4)
    if total_2pt_fga > 0:
        profile["fg2_pct"] = round(total_2pt_fgm / total_2pt_fga, 4)
    if total_3pt_fga > 0:
        profile["fg3_pct"] = round(total_3pt_fgm / total_3pt_fga, 4)

    # Turnover rate from usage + off_rating proxy
    # (NBAPlayerAdvancedStats doesn't have tov_pct directly)
    # Approximate from usage: higher usage → more turnovers
    usg = profile.get("usg_pct", 0.20)
    profile["tov_rate"] = round(min(0.25, max(0.05, 0.08 + (usg - 0.20) * 0.3)), 4)

    profile["games_found"] = len(rows)
    return profile


async def build_unit_probabilities(
    db: AsyncSession,
    players: list[dict[str, str]],
    team_id: int,
    opposing_def_rating: float | None = None,
    rolling_window: int = 15,
) -> dict[str, float]:
    """Aggregate individual player profiles into unit-level possession probs.

    Weights each player's contribution by their usage rate.  Players
    without individual profiles use league-average baselines.

    Args:
        db: Async database session.
        players: List of ``{"external_ref": str, "name": str}`` dicts.
        team_id: Team ID for DB lookups.
        opposing_def_rating: Opponent's defensive rating (higher = worse D).
        rolling_window: Games to look back for rolling profiles.

    Returns:
        Dict with ``*_probability`` keys matching ``POSSESSION_EVENTS``,
        plus ``ft_pct``.
    """
    profiles: list[dict[str, float]] = []

    for p in players:
        ext_ref = p.get("external_ref", "")
        if ext_ref:
            prof = await get_nba_player_rolling_profile(
                db, ext_ref, team_id, rolling_window,
            )
            if prof:
                profiles.append(prof)
                continue
        # Fallback: league-average proxy
        profiles.append({
            "off_rating": BASELINE_OFF_RATING,
            "ts_pct": BASELINE_TS_PCT,
            "efg_pct": BASELINE_EFG_PCT,
            "usg_pct": 0.20,
            "fg3_rate": 0.35,
            "fg2_pct": 0.52,
            "fg3_pct": 0.36,
            "tov_rate": 0.13,
        })

    if not profiles:
        return dict(DEFAULT_EVENT_PROBS) | {"ft_pct": BASELINE_FT_PCT}

    return _aggregate_to_possession_probs(profiles, opposing_def_rating)


def _aggregate_to_possession_probs(
    profiles: list[dict[str, float]],
    opposing_def_rating: float | None,
) -> dict[str, float]:
    """Convert player profiles into possession event probabilities.

    Each player's contribution is weighted by usage rate.  Shot type
    splits (2pt vs 3pt) and make rates determine the probability
    of each possession outcome.
    """
    # Usage-weighted averages
    total_usg = sum(p.get("usg_pct", 0.20) for p in profiles)
    if total_usg <= 0:
        total_usg = len(profiles) * 0.20

    def _wavg(key: str, default: float) -> float:
        num = sum(
            p.get(key, default) * p.get("usg_pct", 0.20)
            for p in profiles
        )
        return num / total_usg

    unit_ts = _wavg("ts_pct", BASELINE_TS_PCT)
    unit_efg = _wavg("efg_pct", BASELINE_EFG_PCT)
    unit_fg3_rate = _wavg("fg3_rate", 0.35)
    unit_fg2_pct = _wavg("fg2_pct", 0.52)
    unit_fg3_pct = _wavg("fg3_pct", 0.36)
    unit_tov = _wavg("tov_rate", 0.13)
    unit_off_rating = _wavg("off_rating", BASELINE_OFF_RATING)

    # Adjust for opposing defense
    def_adj = 1.0
    if opposing_def_rating is not None:
        # Better defense (lower rating) reduces scoring
        # Average def_rating ~ 114.  A 110 defense is elite, 118 is bad.
        def_adj = 1.0 + (opposing_def_rating - BASELINE_DEF_RATING) / BASELINE_DEF_RATING * 0.5
        def_adj = max(0.85, min(1.15, def_adj))

    # Off-rating adjustment (how much better/worse than average)
    off_adj = 1.0 + (unit_off_rating - BASELINE_OFF_RATING) / BASELINE_OFF_RATING * 0.3
    off_adj = max(0.85, min(1.15, off_adj))

    combined_adj = off_adj * def_adj

    # Derive possession event probabilities from shooting splits
    # ~35% of FGA are 3pt, rest 2pt (typical NBA)
    fg2_rate = 1.0 - unit_fg3_rate

    # FT trip rate stays roughly constant (~10% of possessions)
    ft_trip = 0.10

    # Turnover rate
    turnover = max(0.05, min(0.22, unit_tov))

    # Remaining possessions are field goal attempts
    fga_share = 1.0 - ft_trip - turnover

    # Apply adjustments to make rates
    three_make = unit_fg3_rate * unit_fg3_pct * fga_share * combined_adj
    three_miss = unit_fg3_rate * (1.0 - unit_fg3_pct) * fga_share
    two_make = fg2_rate * unit_fg2_pct * fga_share * combined_adj
    two_miss = fg2_rate * (1.0 - unit_fg2_pct) * fga_share

    # Normalize to sum to 1
    total = two_make + two_miss + three_make + three_miss + ft_trip + turnover
    if total <= 0:
        return dict(DEFAULT_EVENT_PROBS) | {"ft_pct": BASELINE_FT_PCT}

    # FT% from TS% - EFG% relationship (TS accounts for FT, EFG doesn't)
    ft_pct = max(0.60, min(0.90, 0.78 + (unit_ts - unit_efg - 0.04) * 2.0))

    return {
        "two_pt_make_probability": round(two_make / total, 4),
        "three_pt_make_probability": round(three_make / total, 4),
        "three_pt_miss_probability": round(three_miss / total, 4),
        "free_throw_trip_probability": round(ft_trip / total, 4),
        "turnover_probability": round(turnover / total, 4),
        "ft_pct": round(ft_pct, 4),
    }
