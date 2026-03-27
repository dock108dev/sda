"""Build rotation weight structures for NHL rotation-aware simulation.

Combines rotation data with individual player profiles to produce
top-line/depth unit shot probability arrays.  Incorporates opposing
goalie save% into goal probability.
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
    opposing_goalie_save_pct: float | None = None,
    rolling_window: int = 15,
) -> dict[str, Any]:
    """Build top-line/depth unit weight arrays for NHL rotation sim.

    Returns dict with ``starter_weights``, ``bench_weights``,
    ``starter_share``, and ``players_resolved`` count.
    """
    from app.analytics.services.nhl_player_profiles import build_unit_probabilities
    from app.analytics.sports.nhl.game_simulator import _build_weights

    starters = rotation["starters"]
    bench = rotation["bench"]
    starter_share = rotation.get("starter_minutes_share", 0.65)

    starter_probs = await build_unit_probabilities(
        db, starters, team_id,
        opposing_goalie_save_pct=opposing_goalie_save_pct,
        rolling_window=rolling_window,
    )
    bench_probs = await build_unit_probabilities(
        db, bench or starters, team_id,
        opposing_goalie_save_pct=opposing_goalie_save_pct,
        rolling_window=rolling_window,
    )

    starter_weights = _build_weights(starter_probs)
    bench_weights = _build_weights(bench_probs)

    return {
        "starter_weights": starter_weights,
        "bench_weights": bench_weights,
        "starter_share": round(starter_share, 3),
        "players_resolved": len(starters) + len(bench),
    }
