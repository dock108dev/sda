"""MLB-specific matchup probability calculations.

Computes event probability distributions for batter-vs-pitcher and
team-vs-team matchups using pre-built analytical profiles. All
calculations are stateless and deterministic for simulation use.

League-average baselines match those in ``metrics.py``.
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.types import PlayerProfile, TeamProfile
from app.analytics.sports.mlb.constants import (
    BARREL_HR_CONVERSION as _BARREL_HR_CONVERSION,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_BABIP as _BASELINE_BABIP,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_BARREL_RATE as _BASELINE_BARREL_RATE,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_CONTACT_RATE as _BASELINE_CONTACT_RATE,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_CONTACT_SUPPRESSION as _BASELINE_CONTACT_SUPPRESSION,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_POWER_INDEX as _BASELINE_POWER_INDEX,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_POWER_SUPPRESSION as _BASELINE_POWER_SUPPRESSION,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_STRIKEOUT_RATE as _BASELINE_STRIKEOUT_RATE,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_SWING_RATE as _BASELINE_SWING_RATE,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_WALK_RATE as _BASELINE_WALK_RATE,
)
from app.analytics.sports.mlb.constants import (
    BASELINE_WHIFF_RATE as _BASELINE_WHIFF_RATE,
)
from app.analytics.sports.mlb.constants import (
    DOUBLE_FRACTION as _DOUBLE_FRACTION,
)
from app.analytics.sports.mlb.constants import (
    SINGLE_FRACTION as _SINGLE_FRACTION,
)
from app.analytics.sports.mlb.constants import (
    TRIPLE_FRACTION as _TRIPLE_FRACTION,
)


class MLBMatchup:
    """Compute MLB matchup probability distributions."""

    def batter_vs_pitcher(
        self,
        batter: PlayerProfile,
        pitcher: PlayerProfile,
    ) -> dict[str, float]:
        """Generate event probabilities for a batter-vs-pitcher matchup.

        Args:
            batter: Batter profile with metrics like contact_rate,
                power_index, barrel_rate, etc.
            pitcher: Pitcher profile with metrics like contact_suppression,
                strikeout_rate, walk_rate, etc.

        Returns:
            Dict of event name -> probability (0-1), normalized.
        """
        b = batter.metrics
        p = pitcher.metrics

        # Extract batter metrics with baseline fallbacks
        b_contact = b.get("contact_rate", _BASELINE_CONTACT_RATE)
        b_whiff = b.get("whiff_rate", _BASELINE_WHIFF_RATE)
        b_swing = b.get("swing_rate", _BASELINE_SWING_RATE)
        b_power = b.get("power_index", _BASELINE_POWER_INDEX)
        b_barrel = b.get("barrel_rate", _BASELINE_BARREL_RATE)

        # Extract pitcher metrics with baseline fallbacks
        # Support both dedicated pitcher keys and team-prefixed keys
        p_contact_supp = _get_pitcher_metric(
            p, "contact_suppression", _BASELINE_CONTACT_SUPPRESSION,
        )
        p_k_rate = _get_pitcher_metric(p, "strikeout_rate", _BASELINE_STRIKEOUT_RATE)
        p_bb_rate = _get_pitcher_metric(p, "walk_rate", _BASELINE_WALK_RATE)
        p_power_supp = _get_pitcher_metric(p, "power_suppression", _BASELINE_POWER_SUPPRESSION)

        # Core probabilities
        contact_prob = _clamp(b_contact * (1.0 - p_contact_supp))
        strikeout_prob = _clamp(b_whiff * p_k_rate / _BASELINE_WHIFF_RATE)
        # Walk rate: pitcher BB% is the baseline; adjust by how selective
        # the batter is relative to average.  A patient batter (low swing%)
        # walks more; a free-swinger walks less.
        discipline_factor = (1.0 - b_swing) / (1.0 - _BASELINE_SWING_RATE)
        walk_prob = _clamp(p_bb_rate * discipline_factor)

        # Power adjustment for home runs
        adjusted_power = b_power * (1.0 - p_power_supp)
        hr_prob = _clamp(b_barrel * adjusted_power * _BARREL_HR_CONVERSION)

        # Hit-type distribution: apply BABIP to convert contact into
        # realistic hit rates.  Only ~30% of balls in play become hits;
        # the rest are fielded outs (absorbed by _build_weights residual).
        in_play_contact = max(contact_prob - hr_prob, 0.0)
        hits_in_play = in_play_contact * _BASELINE_BABIP
        single_prob = hits_in_play * _SINGLE_FRACTION
        double_prob = hits_in_play * _DOUBLE_FRACTION
        triple_prob = hits_in_play * _TRIPLE_FRACTION

        raw = {
            "strikeout_probability": strikeout_prob,
            "walk_or_hbp_probability": walk_prob,
            "single_probability": single_prob,
            "double_probability": double_prob,
            "triple_probability": triple_prob,
            "home_run_probability": hr_prob,
        }

        return normalize_probabilities(raw)

    def team_offense_vs_pitching(
        self,
        team_offense: TeamProfile,
        team_pitching: TeamProfile,
    ) -> dict[str, float]:
        """Generate aggregate probabilities for team offense vs pitching staff.

        Uses team-level metrics (prefixed with ``team_``) with the same
        probability model as batter-vs-pitcher.

        Args:
            team_offense: Offensive team profile.
            team_pitching: Pitching team profile.

        Returns:
            Dict of event name -> probability (0-1), normalized.
        """
        off = team_offense.metrics
        pitch = team_pitching.metrics

        # Extract offensive metrics (try team_ prefix then raw key)
        o_contact = _get_team_metric(off, "contact_rate", _BASELINE_CONTACT_RATE)
        o_whiff = _get_team_metric(off, "whiff_rate", _BASELINE_WHIFF_RATE)
        o_swing = _get_team_metric(off, "swing_rate", _BASELINE_SWING_RATE)
        o_power = _get_team_metric(off, "power_index", _BASELINE_POWER_INDEX)
        o_barrel = _get_team_metric(off, "barrel_rate", _BASELINE_BARREL_RATE)

        # Extract pitching metrics
        p_contact_supp = _get_team_metric(
            pitch, "contact_suppression", _BASELINE_CONTACT_SUPPRESSION,
        )
        p_k_rate = _get_team_metric(pitch, "strikeout_rate", _BASELINE_STRIKEOUT_RATE)
        p_bb_rate = _get_team_metric(pitch, "walk_rate", _BASELINE_WALK_RATE)
        p_power_supp = _get_team_metric(pitch, "power_suppression", _BASELINE_POWER_SUPPRESSION)

        contact_prob = _clamp(o_contact * (1.0 - p_contact_supp))
        strikeout_prob = _clamp(o_whiff * p_k_rate / _BASELINE_WHIFF_RATE)
        discipline_factor = (1.0 - o_swing) / (1.0 - _BASELINE_SWING_RATE)
        walk_prob = _clamp(p_bb_rate * discipline_factor)

        adjusted_power = o_power * (1.0 - p_power_supp)
        hr_prob = _clamp(o_barrel * adjusted_power * _BARREL_HR_CONVERSION)

        in_play_contact = max(contact_prob - hr_prob, 0.0)
        hits_in_play = in_play_contact * _BASELINE_BABIP
        single_prob = hits_in_play * _SINGLE_FRACTION
        double_prob = hits_in_play * _DOUBLE_FRACTION
        triple_prob = hits_in_play * _TRIPLE_FRACTION

        raw = {
            "strikeout_probability": strikeout_prob,
            "walk_or_hbp_probability": walk_prob,
            "single_probability": single_prob,
            "double_probability": double_prob,
            "triple_probability": triple_prob,
            "home_run_probability": hr_prob,
        }

        return normalize_probabilities(raw)

    def compare_metrics(
        self,
        player_a: PlayerProfile,
        player_b: PlayerProfile,
    ) -> dict[str, Any]:
        """Side-by-side metric comparison between two players.

        Returns:
            Dict mapping metric names to ``{"a": val, "b": val, "diff": val}``.
        """
        a_m = player_a.metrics
        b_m = player_b.metrics
        all_keys = sorted(set(a_m) | set(b_m))

        comparison: dict[str, Any] = {}
        for key in all_keys:
            a_val = a_m.get(key)
            b_val = b_m.get(key)
            diff = None
            if a_val is not None and b_val is not None:
                try:
                    diff = round(float(a_val) - float(b_val), 4)
                except (ValueError, TypeError):
                    pass
            comparison[key] = {"a": a_val, "b": b_val, "diff": diff}

        return comparison

    def determine_advantages(
        self,
        comparison: dict[str, Any],
    ) -> dict[str, str]:
        """Determine which entity has the advantage per metric.

        Args:
            comparison: Output from ``compare_metrics()``.

        Returns:
            Dict mapping metric name to "a", "b", or "even".
        """
        advantages: dict[str, str] = {}
        for key, vals in comparison.items():
            diff = vals.get("diff")
            if diff is None:
                continue
            if diff > 0:
                advantages[key] = "a"
            elif diff < 0:
                advantages[key] = "b"
            else:
                advantages[key] = "even"
        return advantages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_probabilities(prob_dict: dict[str, float]) -> dict[str, float]:
    """Ensure event probabilities leave room for the implicit "out" residual.

    The dict should contain only named non-out events (strikeout, walk,
    single, double, triple, home_run).  ``_build_weights()`` computes
    ``out = 1 - sum(named)`` as the fielded-out probability.

    If the total exceeds 1.0 (extreme matchups), we scale down
    proportionally so the out residual is at least 0.  Values are
    clamped to [0, 1] before the check.
    """
    clamped = {k: max(0.0, min(v, 1.0)) for k, v in prob_dict.items()}
    total = sum(clamped.values())
    if total <= 1.0:
        return clamped
    # Scale down so total == 1.0 (out residual will be 0)
    return {k: round(v / total, 4) for k, v in clamped.items()}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(value, hi))


def _get_pitcher_metric(
    metrics: dict[str, Any],
    key: str,
    default: float,
) -> float:
    """Extract a pitcher metric, trying the raw key first then team-prefixed."""
    val = metrics.get(key)
    if val is None:
        val = metrics.get(f"team_{key}")
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _get_team_metric(
    metrics: dict[str, Any],
    key: str,
    default: float,
) -> float:
    """Extract a team metric, trying team_ prefix first then raw key."""
    val = metrics.get(f"team_{key}")
    if val is None:
        val = metrics.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
