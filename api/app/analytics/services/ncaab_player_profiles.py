"""NCAAB per-player rolling profiles and unit-level probability derivation.

Builds rolling averages from ``NCAABPlayerAdvancedStats`` and aggregates
into unit-level possession probability distributions for the
rotation-aware simulator.  Includes NCAAB-specific ORB% and FT% per unit.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sports.ncaab.constants import (
    BASELINE_DEF_RATING,
    BASELINE_FT_PCT,
    BASELINE_OFF_EFG_PCT,
    BASELINE_OFF_ORB_PCT,
    BASELINE_OFF_RATING,
    BASELINE_OFF_TOV_PCT,
    DEFAULT_EVENT_PROBS,
    ORB_CHANCE,
)

logger = logging.getLogger(__name__)

_MIN_GAMES = 3


async def get_ncaab_player_rolling_profile(
    db: AsyncSession,
    player_external_ref: str,
    team_id: int,
    rolling_window: int = 15,
) -> dict[str, float] | None:
    """Build a rolling average profile for an NCAAB player.

    Returns dict of metric averages or ``None`` if insufficient data.
    """
    from app.db.ncaab_advanced import NCAABPlayerAdvancedStats
    from app.db.sports import SportsGame

    stmt = (
        select(NCAABPlayerAdvancedStats)
        .join(SportsGame, SportsGame.id == NCAABPlayerAdvancedStats.game_id)
        .where(
            NCAABPlayerAdvancedStats.player_external_ref == player_external_ref,
            NCAABPlayerAdvancedStats.team_id == team_id,
            SportsGame.status.in_(["final", "archived"]),
            NCAABPlayerAdvancedStats.minutes > 0,
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if len(rows) < _MIN_GAMES:
        return None

    profile: dict[str, float] = {}

    # Average numeric fields
    float_fields = ["off_rating", "usg_pct", "ts_pct", "efg_pct", "minutes"]
    for field in float_fields:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        if vals:
            profile[field] = round(sum(vals) / len(vals), 4)

    # Per-game volume stats → per-minute rates
    total_minutes = sum(r.minutes for r in rows if r.minutes)
    if total_minutes > 0:
        total_pts = sum(r.points or 0 for r in rows)
        total_reb = sum(r.rebounds or 0 for r in rows)
        total_ast = sum(r.assists or 0 for r in rows)
        total_tov = sum(r.turnovers or 0 for r in rows)
        total_stl = sum(r.steals or 0 for r in rows)
        total_blk = sum(r.blocks or 0 for r in rows)

        profile["pts_per_min"] = round(total_pts / total_minutes, 4)
        profile["reb_per_min"] = round(total_reb / total_minutes, 4)
        profile["ast_per_min"] = round(total_ast / total_minutes, 4)
        profile["tov_per_min"] = round(total_tov / total_minutes, 4)
        profile["stl_per_min"] = round(total_stl / total_minutes, 4)
        profile["blk_per_min"] = round(total_blk / total_minutes, 4)

        # Approximate turnover rate from volume
        possessions_approx = total_pts / 1.0 + total_tov  # rough proxy
        if possessions_approx > 0:
            profile["tov_rate"] = round(total_tov / possessions_approx, 4)

    profile["games_found"] = len(rows)
    return profile


async def build_unit_probabilities(
    db: AsyncSession,
    players: list[dict[str, str]],
    team_id: int,
    opposing_def_rating: float | None = None,
    rolling_window: int = 15,
) -> dict[str, float]:
    """Aggregate player profiles into unit-level possession probabilities.

    Returns dict with ``*_probability`` keys plus ``ft_pct`` and ``orb_pct``.
    """
    profiles: list[dict[str, float]] = []

    for p in players:
        ext_ref = p.get("external_ref", "")
        if ext_ref:
            prof = await get_ncaab_player_rolling_profile(
                db, ext_ref, team_id, rolling_window,
            )
            if prof:
                profiles.append(prof)
                continue
        # Fallback: league-average
        profiles.append({
            "off_rating": BASELINE_OFF_RATING,
            "ts_pct": 0.54,
            "efg_pct": BASELINE_OFF_EFG_PCT,
            "usg_pct": 0.20,
            "tov_rate": BASELINE_OFF_TOV_PCT,
        })

    if not profiles:
        return (
            dict(DEFAULT_EVENT_PROBS)
            | {"ft_pct": BASELINE_FT_PCT, "orb_pct": ORB_CHANCE}
        )

    return _aggregate_to_possession_probs(profiles, opposing_def_rating)


def _aggregate_to_possession_probs(
    profiles: list[dict[str, float]],
    opposing_def_rating: float | None,
) -> dict[str, float]:
    """Convert player profiles into NCAAB possession event probabilities."""
    total_usg = sum(p.get("usg_pct", 0.20) for p in profiles)
    if total_usg <= 0:
        total_usg = len(profiles) * 0.20

    def _wavg(key: str, default: float) -> float:
        num = sum(
            p.get(key, default) * p.get("usg_pct", 0.20) for p in profiles
        )
        return num / total_usg

    unit_ts = _wavg("ts_pct", 0.54)
    unit_efg = _wavg("efg_pct", BASELINE_OFF_EFG_PCT)
    unit_off_rating = _wavg("off_rating", BASELINE_OFF_RATING)
    unit_tov = _wavg("tov_rate", BASELINE_OFF_TOV_PCT)

    # Defense adjustment
    def_adj = 1.0
    if opposing_def_rating is not None:
        def_adj = 1.0 + (opposing_def_rating - BASELINE_DEF_RATING) / BASELINE_DEF_RATING * 0.5
        def_adj = max(0.85, min(1.15, def_adj))

    off_adj = 1.0 + (unit_off_rating - BASELINE_OFF_RATING) / BASELINE_OFF_RATING * 0.3
    off_adj = max(0.85, min(1.15, off_adj))

    combined_adj = off_adj * def_adj

    # NCAAB shooting splits: ~36% of attempts are 3PT, ~64% 2PT
    fg3_rate = 0.36
    fg2_rate = 1.0 - fg3_rate

    # Derive make rates from EFG%:
    # EFG% = (FGM + 0.5 * FG3M) / FGA
    # Approximate: fg2_pct ≈ efg / (1 - 0.5*fg3_rate*fg3_pct_bonus)
    fg2_pct = max(0.35, min(0.60, unit_efg * 0.95))
    fg3_pct = max(0.25, min(0.45, unit_efg * 0.68))

    ft_trip = 0.072  # ~7.2% of NCAAB possessions
    turnover = max(0.08, min(0.25, unit_tov))
    fga_share = 1.0 - ft_trip - turnover

    three_make = fg3_rate * fg3_pct * fga_share * combined_adj
    three_miss = fg3_rate * (1.0 - fg3_pct) * fga_share
    two_make = fg2_rate * fg2_pct * fga_share * combined_adj
    two_miss = fg2_rate * (1.0 - fg2_pct) * fga_share

    total = two_make + two_miss + three_make + three_miss + ft_trip + turnover
    if total <= 0:
        return (
            dict(DEFAULT_EVENT_PROBS)
            | {"ft_pct": BASELINE_FT_PCT, "orb_pct": ORB_CHANCE}
        )

    # FT% from TS% relationship
    ft_pct = max(0.55, min(0.85, 0.70 + (unit_ts - unit_efg - 0.04) * 2.0))

    # ORB% — rebounding correlates loosely with player size/effort
    # Use baseline with minor adjustment from off_rating
    orb_adj = 1.0 + (unit_off_rating - BASELINE_OFF_RATING) / BASELINE_OFF_RATING * 0.15
    orb_pct = max(0.18, min(0.38, ORB_CHANCE * orb_adj))

    return {
        "two_pt_make_probability": round(two_make / total, 4),
        "three_pt_make_probability": round(three_make / total, 4),
        "three_pt_miss_probability": round(three_miss / total, 4),
        "free_throw_trip_probability": round(ft_trip / total, 4),
        "turnover_probability": round(turnover / total, 4),
        "ft_pct": round(ft_pct, 4),
        "orb_pct": round(orb_pct, 4),
    }
