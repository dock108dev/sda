"""Build per-batter weight arrays for lineup-aware MLB simulation.

Shared by both the interactive API endpoint and the batch simulation task.
Each batter gets two weight arrays: one for the matchup vs the opposing
starter, and one vs the opposing bullpen.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Pitchers with avg IP below this threshold get regressed toward league avg.
_STARTER_IP_THRESHOLD = 5.0

_LEAGUE_AVG_PITCHER: dict[str, float] = {
    "strikeout_rate": 0.22,
    "walk_rate": 0.08,
    "contact_suppression": 0.0,
    "power_suppression": 0.0,
}


def regress_pitcher_profile(
    profile: dict[str, float],
    avg_ip: float | None,
) -> dict[str, float]:
    """Regress a pitcher's profile toward league average based on avg IP.

    Relievers pitch short stints at max effort — their per-inning rates
    can't be sustained over a full start.  This blends their profile with
    league average proportionally to how many innings they typically throw.
    """
    if avg_ip is None or avg_ip >= _STARTER_IP_THRESHOLD:
        return profile

    blend = max(avg_ip / _STARTER_IP_THRESHOLD, 0.1)
    regressed: dict[str, float] = {}
    for key in profile:
        league_val = _LEAGUE_AVG_PITCHER.get(key, 0.0)
        regressed[key] = round(league_val + blend * (profile[key] - league_val), 4)
    return regressed


def pitching_metrics_from_profile(
    team_profile: dict[str, float] | None,
) -> dict[str, float] | None:
    """Derive mild bullpen adjustments from a team's batting profile.

    Uses league-average pitcher baselines with small nudges based on
    the team's own offensive tendencies as a proxy for pitching staff
    quality.  Adjustments are deliberately small (clamped to ±0.05).
    """
    if not team_profile:
        return None
    whiff = team_profile.get("whiff_rate")
    contact = team_profile.get("contact_rate")
    if whiff is None and contact is None:
        return None

    k_offset = min(max((whiff or 0.23) - 0.23, -0.05), 0.05)
    bb_offset = min(max(
        0.08 - (team_profile.get("plate_discipline_index", 0.52) - 0.52) * 0.1,
        -0.03,
    ), 0.03)
    contact_offset = min(max(0.77 - (contact or 0.77), -0.05), 0.05) * 0.3
    barrel = team_profile.get("barrel_rate", 0.07)
    power_offset = min(max((0.07 - barrel) / 0.07, -0.15), 0.15) * 0.3

    return {
        "strikeout_rate": round(0.22 + k_offset, 4),
        "walk_rate": round(max(0.04, min(0.12, 0.08 + bb_offset)), 4),
        "contact_suppression": round(max(-0.05, min(0.05, contact_offset)), 4),
        "power_suppression": round(max(-0.05, min(0.05, power_offset)), 4),
    }


async def build_lineup_weights(
    db: AsyncSession,
    lineup: list[dict[str, str]],
    team_id: int,
    opposing_starter_profile: dict[str, float],
    opposing_bullpen_profile: dict[str, float],
    team_profile: dict[str, float] | None,
    *,
    rolling_window: int = 30,
) -> dict[str, Any]:
    """Build per-batter weight arrays for lineup-aware simulation.

    For each batter in the lineup, computes matchup probabilities against
    the opposing starter and bullpen, then converts to weight arrays
    suitable for ``MLBGameSimulator.simulate_game_with_lineups()``.

    Args:
        db: Async database session.
        lineup: List of ``{"external_ref": str, "name": str}`` dicts
            in batting order.
        team_id: ID of the batting team (for profile lookups).
        opposing_starter_profile: Pitcher profile dict for the starter.
        opposing_bullpen_profile: Pitcher profile dict for the bullpen.
        team_profile: Fallback team-level profile if a batter has no
            individual data.
        rolling_window: Number of recent games for rolling profiles.

    Returns:
        Dict with ``starter_weights``, ``bullpen_weights``,
        ``batters_resolved`` count.
    """
    from app.analytics.core.types import PlayerProfile
    from app.analytics.services.profile_service import get_player_rolling_profile
    from app.analytics.sports.mlb.game_simulator import _build_weights
    from app.analytics.sports.mlb.matchup import MLBMatchup

    matchup = MLBMatchup()
    starter_weights: list[list[float]] = []
    bullpen_weights: list[list[float]] = []
    batters_resolved = 0

    sp_pp = PlayerProfile(player_id="starter", sport="mlb", metrics=opposing_starter_profile)
    bp_pp = PlayerProfile(player_id="bullpen", sport="mlb", metrics=opposing_bullpen_profile)

    for slot in lineup:
        ext_ref = slot.get("external_ref", "")
        name = slot.get("name", "")

        batter_metrics: dict[str, float] | None = None
        if ext_ref:
            batter_metrics = await get_player_rolling_profile(
                ext_ref, team_id,
                rolling_window=rolling_window,
                db=db,
            )
            if batter_metrics:
                batters_resolved += 1

        # Fall back to team profile
        metrics = batter_metrics or (team_profile or {})
        batter_pp = PlayerProfile(
            player_id=ext_ref, sport="mlb", name=name, metrics=metrics,
        )

        probs_vs_starter = matchup.batter_vs_pitcher(batter_pp, sp_pp)
        starter_weights.append(_build_weights(probs_vs_starter))

        probs_vs_bp = matchup.batter_vs_pitcher(batter_pp, bp_pp)
        bullpen_weights.append(_build_weights(probs_vs_bp))

    return {
        "starter_weights": starter_weights,
        "bullpen_weights": bullpen_weights,
        "batters_resolved": batters_resolved,
    }
