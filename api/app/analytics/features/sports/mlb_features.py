"""MLB-specific feature builder.

Converts MLB analytics profiles (batter, pitcher, team) into
feature vectors for plate-appearance and game-level ML models.

Feature names are prefixed by entity (``batter_``, ``pitcher_``,
``home_``, ``away_``) to avoid collisions.

Usage::

    builder = MLBFeatureBuilder()
    vec = builder.build_plate_appearance_features(batter, pitcher)
"""

from __future__ import annotations

from typing import Any

from app.analytics.features.core.feature_vector import FeatureVector
from app.analytics.sports.mlb.constants import FEATURE_BASELINES as _BASELINES

# Ordered feature definitions by model type.
# Each entry: (feature_name, source_entity, source_key)
_PA_FEATURES: list[tuple[str, str, str]] = [
    # Derived composites
    ("batter_contact_rate", "batter", "contact_rate"),
    ("batter_power_index", "batter", "power_index"),
    ("batter_barrel_rate", "batter", "barrel_rate"),
    ("batter_hard_hit_rate", "batter", "hard_hit_rate"),
    ("batter_swing_rate", "batter", "swing_rate"),
    ("batter_whiff_rate", "batter", "whiff_rate"),
    ("batter_avg_exit_velocity", "batter", "avg_exit_velocity"),
    ("batter_expected_slug", "batter", "expected_slug"),
    ("pitcher_contact_rate", "pitcher", "contact_rate"),
    ("pitcher_power_index", "pitcher", "power_index"),
    ("pitcher_barrel_rate", "pitcher", "barrel_rate"),
    ("pitcher_hard_hit_rate", "pitcher", "hard_hit_rate"),
    ("pitcher_swing_rate", "pitcher", "swing_rate"),
    ("pitcher_whiff_rate", "pitcher", "whiff_rate"),
    # Raw split percentages
    ("batter_z_swing_pct", "batter", "z_swing_pct"),
    ("batter_o_swing_pct", "batter", "o_swing_pct"),
    ("batter_z_contact_pct", "batter", "z_contact_pct"),
    ("batter_o_contact_pct", "batter", "o_contact_pct"),
    ("pitcher_z_swing_pct", "pitcher", "z_swing_pct"),
    ("pitcher_o_swing_pct", "pitcher", "o_swing_pct"),
    ("pitcher_z_contact_pct", "pitcher", "z_contact_pct"),
    ("pitcher_o_contact_pct", "pitcher", "o_contact_pct"),
    # Additional derived ratios
    ("batter_zone_swing_rate", "batter", "zone_swing_rate"),
    ("batter_chase_rate", "batter", "chase_rate"),
    ("batter_plate_discipline_index", "batter", "plate_discipline_index"),
    ("pitcher_zone_swing_rate", "pitcher", "zone_swing_rate"),
    ("pitcher_chase_rate", "pitcher", "chase_rate"),
    ("pitcher_plate_discipline_index", "pitcher", "plate_discipline_index"),
]

# Player-level PA features — extends _PA_FEATURES with true pitcher metrics
# and optional fielding/matchup context.
_PLAYER_PA_FEATURES: list[tuple[str, str, str]] = [
    # Batter profile (same as _PA_FEATURES batter block)
    ("batter_contact_rate", "batter", "contact_rate"),
    ("batter_power_index", "batter", "power_index"),
    ("batter_barrel_rate", "batter", "barrel_rate"),
    ("batter_hard_hit_rate", "batter", "hard_hit_rate"),
    ("batter_swing_rate", "batter", "swing_rate"),
    ("batter_whiff_rate", "batter", "whiff_rate"),
    ("batter_avg_exit_velocity", "batter", "avg_exit_velocity"),
    ("batter_expected_slug", "batter", "expected_slug"),
    ("batter_z_swing_pct", "batter", "z_swing_pct"),
    ("batter_o_swing_pct", "batter", "o_swing_pct"),
    ("batter_z_contact_pct", "batter", "z_contact_pct"),
    ("batter_o_contact_pct", "batter", "o_contact_pct"),
    ("batter_chase_rate", "batter", "chase_rate"),
    ("batter_plate_discipline_index", "batter", "plate_discipline_index"),
    # True pitcher profile (from MLBPitcherGameStats rolling)
    ("pitcher_k_rate", "pitcher", "k_rate"),
    ("pitcher_bb_rate", "pitcher", "bb_rate"),
    ("pitcher_hr_rate", "pitcher", "hr_rate"),
    ("pitcher_whiff_rate", "pitcher", "whiff_rate"),
    ("pitcher_z_contact_pct", "pitcher", "z_contact_pct"),
    ("pitcher_chase_rate", "pitcher", "chase_rate"),
    ("pitcher_avg_exit_velo_against", "pitcher", "avg_exit_velo_against"),
    ("pitcher_hard_hit_pct_against", "pitcher", "hard_hit_pct_against"),
    ("pitcher_barrel_pct_against", "pitcher", "barrel_pct_against"),
    ("pitcher_contact_suppression", "pitcher", "contact_suppression"),
    ("pitcher_power_suppression", "pitcher", "power_suppression"),
    ("pitcher_strikeout_rate", "pitcher", "strikeout_rate"),
    ("pitcher_walk_rate", "pitcher", "walk_rate"),
    # Standard batting (from boxscore raw_stats, averaged over rolling window)
    ("batter_box_avg", "batter", "box_avg"),
    ("batter_box_obp", "batter", "box_obp"),
    ("batter_box_slg", "batter", "box_slg"),
    ("batter_box_iso", "batter", "box_iso"),
    # Traditional pitcher rates (from existing stored IP/ER/H/BB/HR)
    ("pitcher_era", "pitcher", "era"),
    ("pitcher_whip", "pitcher", "whip"),
    ("pitcher_k_per_9", "pitcher", "k_per_9"),
    ("pitcher_bb_per_9", "pitcher", "bb_per_9"),
    ("pitcher_hr_per_9", "pitcher", "hr_per_9"),
    # Matchup context
    ("matchup_batter_hand", "matchup", "batter_hand_code"),
    ("matchup_pitcher_hand", "matchup", "pitcher_hand_code"),
    # Game-state context (from PBP play context)
    ("context_inning", "matchup", "inning"),
    ("context_outs", "matchup", "outs"),
    ("context_score_diff", "matchup", "score_diff"),
]

# Fielding features — appended when fielding data is available
_FIELDING_FEATURES: list[tuple[str, str, str]] = [
    ("fielding_team_oaa", "fielding", "team_oaa"),
    ("fielding_team_drs", "fielding", "team_drs"),
    ("fielding_team_defensive_value", "fielding", "team_defensive_value"),
]

# All metrics exposed as both home_ and away_ for game-level models.
_GAME_METRIC_KEYS: list[str] = [
    # Derived composites
    "contact_rate",
    "power_index",
    "barrel_rate",
    "hard_hit_rate",
    "swing_rate",
    "whiff_rate",
    "avg_exit_velocity",
    "expected_slug",
    # Raw plate discipline percentages
    "z_swing_pct",
    "o_swing_pct",
    "z_contact_pct",
    "o_contact_pct",
    # Raw quality of contact
    "avg_exit_velo",
    "hard_hit_pct",
    "barrel_pct",
    # Raw counts
    "total_pitches",
    "balls_in_play",
    "hard_hit_count",
    "barrel_count",
    "zone_pitches",
    "zone_swings",
    "zone_contact",
    "outside_pitches",
    "outside_swings",
    "outside_contact",
    # Additional derived ratios
    "zone_swing_rate",
    "chase_rate",
    "zone_contact_rate",
    "outside_contact_rate",
    "plate_discipline_index",
]

_GAME_FEATURES: list[tuple[str, str, str]] = [
    (f"{side}_{key}", side, key)
    for side in ("home", "away")
    for key in _GAME_METRIC_KEYS
]


class MLBFeatureBuilder:
    """Build MLB feature vectors from analytics profiles."""

    def build_features(
        self,
        entity_profiles: dict[str, Any],
        model_type: str,
    ) -> FeatureVector:
        """Route to the appropriate feature builder by model type.

        Args:
            entity_profiles: Dict of profile data keyed by entity
                role (``batter_profile``, ``pitcher_profile``,
                ``home_profile``, ``away_profile``).
            model_type: ``"plate_appearance"`` or ``"game"``.

        Returns:
            ``FeatureVector`` with ordered features.
        """
        if model_type == "plate_appearance":
            batter = _extract_metrics(entity_profiles, "batter_profile", "batter")
            pitcher = _extract_metrics(entity_profiles, "pitcher_profile", "pitcher")
            return self.build_plate_appearance_features(batter, pitcher)

        if model_type == "player_plate_appearance":
            batter = _extract_metrics(entity_profiles, "batter_profile", "batter")
            pitcher = _extract_metrics(entity_profiles, "pitcher_profile", "pitcher")
            matchup = entity_profiles.get("matchup", {})
            fielding = entity_profiles.get("team_fielding", {})
            return self.build_player_pa_features(
                batter, pitcher, matchup=matchup, fielding=fielding,
            )

        if model_type == "game":
            home = _extract_metrics(entity_profiles, "home_profile", "home")
            away = _extract_metrics(entity_profiles, "away_profile", "away")
            return self.build_game_features(home, away)

        return FeatureVector({})

    def build_plate_appearance_features(
        self,
        batter_metrics: dict[str, Any],
        pitcher_metrics: dict[str, Any],
    ) -> FeatureVector:
        """Build feature vector for plate-appearance modeling.

        Args:
            batter_metrics: Batter profile metrics dict.
            pitcher_metrics: Pitcher profile metrics dict.

        Returns:
            ``FeatureVector`` with batter_ and pitcher_ prefixed features.
        """
        sources = {"batter": batter_metrics, "pitcher": pitcher_metrics}
        features, order = _build_from_spec(_PA_FEATURES, sources)
        return FeatureVector(features, feature_order=order)

    def build_player_pa_features(
        self,
        batter_metrics: dict[str, Any],
        pitcher_metrics: dict[str, Any],
        *,
        matchup: dict[str, Any] | None = None,
        fielding: dict[str, Any] | None = None,
    ) -> FeatureVector:
        """Build feature vector for player-level PA modeling.

        Uses true pitcher metrics (from MLBPitcherGameStats) instead of
        team-level proxy. Optionally includes matchup handedness and
        team fielding context.
        """
        matchup = matchup or {}
        fielding = fielding or {}

        # Encode handedness as numeric (R=1, L=0, S=0.5, unknown=0.5)
        matchup_metrics = {
            "batter_hand_code": _encode_hand(matchup.get("batter_hand", "")),
            "pitcher_hand_code": _encode_hand(matchup.get("pitcher_hand", "")),
        }

        sources = {
            "batter": batter_metrics,
            "pitcher": pitcher_metrics,
            "matchup": matchup_metrics,
        }

        spec = list(_PLAYER_PA_FEATURES)
        if fielding:
            sources["fielding"] = fielding
            spec.extend(_FIELDING_FEATURES)

        features, order = _build_from_spec(spec, sources)
        return FeatureVector(features, feature_order=order)

    def build_game_features(
        self,
        home_metrics: dict[str, Any],
        away_metrics: dict[str, Any],
    ) -> FeatureVector:
        """Build feature vector for game-level modeling.

        Args:
            home_metrics: Home team profile metrics dict.
            away_metrics: Away team profile metrics dict.

        Returns:
            ``FeatureVector`` with home_ and away_ prefixed features.
        """
        sources = {"home": home_metrics, "away": away_metrics}
        features, order = _build_from_spec(_GAME_FEATURES, sources)
        return FeatureVector(features, feature_order=order)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_from_spec(
    spec: list[tuple[str, str, str]],
    sources: dict[str, dict[str, Any]],
) -> tuple[dict[str, float], list[str]]:
    """Build features dict and order from a feature spec.

    Each spec entry is ``(feature_name, source_entity, source_key)``.
    Values are normalized against league baselines.
    """
    features: dict[str, float] = {}
    order: list[str] = []

    for feat_name, entity, key in spec:
        metrics = sources.get(entity, {})
        raw_val = metrics.get(key)
        baseline = _BASELINES.get(key)

        if raw_val is not None:
            val = _normalize(float(raw_val), baseline)
        else:
            val = _normalize_default(baseline)

        features[feat_name] = round(val, 4)
        order.append(feat_name)

    return features, order


def _normalize(value: float, baseline: float | None) -> float:
    """Normalize a value relative to its league-average baseline.

    Rate stats (0-1 range) are clamped. Absolute stats are divided
    by baseline.
    """
    if baseline is None:
        return value

    if 0 < baseline <= 1.0:
        # Rate stat: clamp to [0, 1]
        return max(0.0, min(1.0, value))

    # Absolute stat: ratio to baseline
    if baseline != 0:
        return value / baseline

    return value


def _normalize_default(baseline: float | None) -> float:
    """Return the normalized default (1.0 for ratio, baseline for rate)."""
    if baseline is None:
        return 0.0
    if 0 < baseline <= 1.0:
        return baseline
    return 1.0  # ratio to baseline = baseline/baseline


def _encode_hand(hand: str) -> float:
    """Encode batting/pitching handedness as a numeric feature."""
    h = hand.upper().strip()
    if h == "R":
        return 1.0
    if h == "L":
        return 0.0
    if h == "S":  # Switch hitter
        return 0.5
    return 0.5  # Unknown


def _extract_metrics(
    profiles: dict[str, Any],
    profile_key: str,
    fallback_key: str,
) -> dict[str, Any]:
    """Extract metrics dict from the profiles container.

    Handles two input shapes:
    - Dict with ``"metrics"`` key: ``{"metrics": {...}}`` → returns inner dict
    - Object with ``.metrics`` attribute (e.g., ``PlayerProfile``) → returns ``.metrics``
    - Flat dict: ``{key: value, ...}`` → returned as-is
    """
    profile = profiles.get(profile_key) or profiles.get(fallback_key, {})

    if hasattr(profile, "metrics") and not isinstance(profile, dict):
        return profile.metrics

    if isinstance(profile, dict):
        return profile.get("metrics", profile)

    return {}
