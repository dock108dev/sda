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

# League-average baselines for normalization (2024 MLB approximations).
_BASELINES: dict[str, float] = {
    "contact_rate": 0.77,
    "power_index": 1.0,
    "barrel_rate": 0.07,
    "hard_hit_rate": 0.35,
    "swing_rate": 0.50,
    "whiff_rate": 0.23,
    "avg_exit_velocity": 88.0,
    "expected_slug": 0.77,
}

# Ordered feature definitions by model type.
# Each entry: (feature_name, source_entity, source_key)
_PA_FEATURES: list[tuple[str, str, str]] = [
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
]

_GAME_FEATURES: list[tuple[str, str, str]] = [
    ("home_contact_rate", "home", "contact_rate"),
    ("home_power_index", "home", "power_index"),
    ("home_expected_slug", "home", "expected_slug"),
    ("home_barrel_rate", "home", "barrel_rate"),
    ("home_hard_hit_rate", "home", "hard_hit_rate"),
    ("away_contact_rate", "away", "contact_rate"),
    ("away_power_index", "away", "power_index"),
    ("away_expected_slug", "away", "expected_slug"),
    ("away_barrel_rate", "away", "barrel_rate"),
    ("away_hard_hit_rate", "away", "hard_hit_rate"),
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


def _extract_metrics(
    profiles: dict[str, Any],
    profile_key: str,
    fallback_key: str,
) -> dict[str, Any]:
    """Extract metrics from a profile, handling both profile objects and dicts."""
    profile = profiles.get(profile_key) or profiles.get(fallback_key, {})

    if hasattr(profile, "metrics"):
        return profile.metrics

    if isinstance(profile, dict):
        return profile.get("metrics", profile)

    return {}
