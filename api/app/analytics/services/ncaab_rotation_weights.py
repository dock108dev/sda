"""Build rotation weight structures for NCAAB rotation-aware simulation.

Combines rotation data with individual player profiles to produce
starter/bench unit probability arrays including NCAAB-specific
ORB% and FT% per unit.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def build_rotation_weights(
    db: AsyncSession,
    rotation: dict[str, Any],
    team_id: int,
    opposing_def_rating: float | None = None,
    rolling_window: int = 15,
) -> dict[str, Any]:
    """Build starter/bench unit weight arrays for NCAAB rotation sim.

    Returns dict with ``starter_weights``, ``bench_weights``,
    ``starter_share``, per-unit ``ft_pct`` and ``orb_pct``,
    and ``players_resolved`` count.
    """
    from app.analytics.services.ncaab_player_profiles import build_unit_probabilities
    from app.analytics.sports.ncaab.game_simulator import _build_weights

    starters = rotation["starters"]
    bench = rotation["bench"]
    starter_share = rotation.get("starter_minutes_share", 0.70)

    starter_probs = await build_unit_probabilities(
        db, starters, team_id,
        opposing_def_rating=opposing_def_rating,
        rolling_window=rolling_window,
    )
    bench_probs = await build_unit_probabilities(
        db, bench or starters, team_id,
        opposing_def_rating=opposing_def_rating,
        rolling_window=rolling_window,
    )

    starter_weights = _build_weights(starter_probs)
    bench_weights = _build_weights(bench_probs)

    return {
        "starter_weights": starter_weights,
        "bench_weights": bench_weights,
        "starter_share": round(starter_share, 3),
        "ft_pct_starter": starter_probs.get("ft_pct", 0.70),
        "ft_pct_bench": bench_probs.get("ft_pct", 0.70),
        "orb_pct_starter": starter_probs.get("orb_pct", 0.28),
        "orb_pct_bench": bench_probs.get("orb_pct", 0.28),
        "players_resolved": len(starters) + len(bench),
    }
