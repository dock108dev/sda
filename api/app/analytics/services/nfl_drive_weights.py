"""Convert NFL team profiles into drive outcome weight arrays.

Maps team offensive efficiency + opposing defensive quality into
drive outcome probabilities suitable for ``NFLGameSimulator``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sports.nfl.constants import (
    BASELINE_EPA_PER_PLAY,
    BASELINE_SUCCESS_RATE,
    BASELINE_TURNOVER_RATE,
    DEFAULT_DRIVE_PROBS,
    EXTRA_POINT_SUCCESS_RATE,
    FIELD_GOAL_SUCCESS_RATE,
)

logger = logging.getLogger(__name__)


async def build_drive_weights(
    db: AsyncSession,
    game,
    home_profile: dict[str, float] | None,
    away_profile: dict[str, float] | None,
    rolling_window: int = 8,
) -> dict[str, Any] | None:
    """Build drive outcome weights for both teams in a game.

    Each team's offensive profile is adjusted against the opposing
    team's defensive profile to produce matchup-specific drive
    outcome probabilities.

    Returns:
        Dict with ``home_drive_weights``, ``away_drive_weights``,
        ``home_xp_pct``, ``away_xp_pct``, ``home_fg_pct``,
        ``away_fg_pct``, or ``None`` if insufficient data.
    """
    from app.analytics.services.nfl_drive_profiles import build_nfl_team_profile

    if home_profile is None or away_profile is None:
        home_profile = home_profile or await build_nfl_team_profile(
            db, game.home_team_id, rolling_window,
        )
        away_profile = away_profile or await build_nfl_team_profile(
            db, game.away_team_id, rolling_window,
        )

    if not home_profile or not away_profile:
        return None

    # Home offense vs away defense
    home_weights = _derive_drive_weights(home_profile, away_profile)
    # Away offense vs home defense
    away_weights = _derive_drive_weights(away_profile, home_profile)

    return {
        "home_drive_weights": home_weights,
        "away_drive_weights": away_weights,
        "home_xp_pct": EXTRA_POINT_SUCCESS_RATE,
        "away_xp_pct": EXTRA_POINT_SUCCESS_RATE,
        "home_fg_pct": home_profile.get("fg_pct", FIELD_GOAL_SUCCESS_RATE),
        "away_fg_pct": away_profile.get("fg_pct", FIELD_GOAL_SUCCESS_RATE),
    }


def _derive_drive_weights(
    offense: dict[str, float],
    opposing: dict[str, float],
) -> list[float]:
    """Convert offense profile + opposing defense into drive outcome weights.

    Higher offensive EPA → more TDs, fewer punts.
    Higher opposing defensive pressure → more turnovers, fewer TDs.
    """
    # Offensive quality adjustment
    epa = offense.get("epa_per_play", BASELINE_EPA_PER_PLAY)
    success = offense.get("success_rate", BASELINE_SUCCESS_RATE)
    cpoe = offense.get("avg_cpoe", 0.0)

    # Offensive adjustment: EPA and success rate above/below baseline
    off_factor = 1.0
    off_factor += (epa - BASELINE_EPA_PER_PLAY) * 2.0  # EPA has high leverage
    off_factor += (success - BASELINE_SUCCESS_RATE) * 0.5
    off_factor += (cpoe or 0.0) * 0.02  # CPOE is on a different scale (~-5 to +5)
    off_factor = max(0.70, min(1.30, off_factor))

    # Defensive pressure adjustment from opposing team
    def_sacks = opposing.get("def_sacks_per_game", 2.5)
    def_tfl = opposing.get("def_tfl_per_game", 5.0)
    def_turnovers = opposing.get("def_turnovers_forced_per_game", 1.0)

    # Better opposing defense → lower offensive production
    def_pressure = (def_sacks / 2.5 + def_tfl / 5.0) / 2.0  # normalized to ~1.0
    def_factor = 1.0 / max(0.70, min(1.30, def_pressure))

    combined = off_factor * def_factor

    # Base probabilities adjusted by combined factor
    base_td = DEFAULT_DRIVE_PROBS["touchdown"]
    base_fg = DEFAULT_DRIVE_PROBS["field_goal"]
    base_tov = DEFAULT_DRIVE_PROBS["turnover"]
    base_downs = DEFAULT_DRIVE_PROBS["turnover_on_downs"]

    # Scoring drives scale with offensive quality
    td_prob = base_td * combined
    fg_prob = base_fg * (1.0 + (combined - 1.0) * 0.3)  # FG less sensitive

    # Turnovers inversely correlated with offense quality + forcing from defense
    tov_adj = 1.0 + (def_turnovers - 1.0) * 0.3  # better defense → more forced turnovers
    tov_prob = base_tov * (1.0 / combined) * max(0.8, min(1.3, tov_adj))
    downs_prob = base_downs

    # Clamp all probabilities
    td_prob = max(0.10, min(0.35, td_prob))
    fg_prob = max(0.06, min(0.20, fg_prob))
    tov_prob = max(0.05, min(0.22, tov_prob))
    downs_prob = max(0.02, min(0.08, downs_prob))

    # Punt absorbs remainder
    named = td_prob + fg_prob + tov_prob + downs_prob
    punt_prob = max(0.20, 1.0 - named)

    # Normalize
    total = td_prob + fg_prob + punt_prob + tov_prob + downs_prob
    if total <= 0:
        from app.analytics.sports.nfl.game_simulator import _build_weights
        return _build_weights({})

    # Order: touchdown, field_goal, punt, turnover, turnover_on_downs
    return [
        round(td_prob / total, 4),
        round(fg_prob / total, 4),
        round(punt_prob / total, 4),
        round(tov_prob / total, 4),
        round(downs_prob / total, 4),
    ]
