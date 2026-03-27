"""Build rotation weight structures for NBA rotation-aware simulation.

Combines rotation data (who starts, who's bench) with individual player
profiles to produce starter/bench unit probability arrays that the
``NBAGameSimulator.simulate_game_with_lineups()`` method consumes.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sports.nba.constants import (
    BASELINE_DEF_RATING,
    DEFAULT_EVENT_PROBS_SUFFIXED,
)

logger = logging.getLogger(__name__)


async def build_rotation_weights(
    db: AsyncSession,
    rotation: dict[str, Any],
    team_id: int,
    opposing_def_rating: float | None = None,
    rolling_window: int = 15,
) -> dict[str, Any]:
    """Build starter/bench unit weight arrays for rotation-aware sim.

    Args:
        db: Async database session.
        rotation: Output from ``reconstruct_rotation_from_stats`` or
            ``get_recent_rotation`` — must have ``starters``, ``bench``,
            and ``starter_minutes_share`` keys.
        team_id: Team ID.
        opposing_def_rating: Opponent's defensive rating.
        rolling_window: Games for rolling profile lookback.

    Returns:
        Dict with ``starter_weights``, ``bench_weights``,
        ``starter_share``, ``ft_pct_starter``, ``ft_pct_bench``,
        and ``players_resolved`` count.
    """
    from app.analytics.services.nba_player_profiles import build_unit_probabilities
    from app.analytics.sports.nba.game_simulator import _build_weights

    starters = rotation["starters"]
    bench = rotation["bench"]
    starter_share = rotation.get("starter_minutes_share", 0.70)

    # Build unit-level probabilities
    starter_probs = await build_unit_probabilities(
        db, starters, team_id,
        opposing_def_rating=opposing_def_rating,
        rolling_window=rolling_window,
    )
    bench_probs = await build_unit_probabilities(
        db, bench or starters, team_id,  # fall back to starters if no bench
        opposing_def_rating=opposing_def_rating,
        rolling_window=rolling_window,
    )

    starter_weights = _build_weights(starter_probs)
    bench_weights = _build_weights(bench_probs)

    players_resolved = len(starters) + len(bench)

    return {
        "starter_weights": starter_weights,
        "bench_weights": bench_weights,
        "starter_share": round(starter_share, 3),
        "ft_pct_starter": starter_probs.get("ft_pct", 0.78),
        "ft_pct_bench": bench_probs.get("ft_pct", 0.78),
        "players_resolved": players_resolved,
    }
