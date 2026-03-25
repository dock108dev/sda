"""NHL feature builder for ML models.

Converts NHL analytics profiles (home team, away team) into feature
vectors for shot and game-level ML models.

Feature names are prefixed by side (``home_``, ``away_``) to avoid
collisions.

Usage::

    builder = NHLFeatureBuilder()
    vec = builder.build_features(profiles, "shot")
"""

from __future__ import annotations

from typing import Any

from app.analytics.features.core.feature_vector import FeatureVector
from app.analytics.sports.nhl.constants import FEATURE_BASELINES as _BASELINES

# Shot model features: (feature_name, source_entity, source_key)
_SHOT_FEATURES: list[tuple[str, str, str]] = [
    ("home_xgoals_for", "home_profile", "xgoals_for"),
    ("home_xgoals_against", "home_profile", "xgoals_against"),
    ("home_corsi_pct", "home_profile", "corsi_pct"),
    ("home_fenwick_pct", "home_profile", "fenwick_pct"),
    ("home_shooting_pct", "home_profile", "shooting_pct"),
    ("home_save_pct", "home_profile", "save_pct"),
    ("home_pdo", "home_profile", "pdo"),
    ("away_xgoals_for", "away_profile", "xgoals_for"),
    ("away_xgoals_against", "away_profile", "xgoals_against"),
    ("away_corsi_pct", "away_profile", "corsi_pct"),
    ("away_fenwick_pct", "away_profile", "fenwick_pct"),
    ("away_shooting_pct", "away_profile", "shooting_pct"),
    ("away_save_pct", "away_profile", "save_pct"),
    ("away_pdo", "away_profile", "pdo"),
]

_GAME_FEATURES: list[tuple[str, str, str]] = _SHOT_FEATURES


class NHLFeatureBuilder:
    """Build NHL feature vectors from analytics profiles."""

    def build_features(
        self,
        entity_profiles: dict[str, Any],
        model_type: str,
    ) -> FeatureVector:
        """Route to the appropriate feature builder by model type.

        Args:
            entity_profiles: Dict of profile data keyed by entity
                role (``home_profile``, ``away_profile``).
            model_type: ``"shot"`` or ``"game"``.

        Returns:
            ``FeatureVector`` with ordered features.
        """
        if model_type in ("shot", "game"):
            return self._build_from_spec(_SHOT_FEATURES, entity_profiles)
        return FeatureVector({})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_from_spec(
        self,
        spec: list[tuple[str, str, str]],
        profiles: dict[str, Any],
    ) -> FeatureVector:
        """Build features dict from a feature spec and entity profiles."""
        features: dict[str, float] = {}
        order: list[str] = []

        for feat_name, entity_key, source_key in spec:
            profile = profiles.get(entity_key, {})
            if isinstance(profile, dict):
                metrics = profile.get("metrics", profile)
            elif hasattr(profile, "metrics"):
                metrics = profile.metrics
            else:
                metrics = {}

            val = metrics.get(source_key)
            if val is not None:
                baseline = _BASELINES.get(source_key, 1.0)
                features[feat_name] = round(
                    float(val) / baseline if baseline else float(val), 4,
                )
            else:
                features[feat_name] = 0.0

            order.append(feat_name)

        return FeatureVector(features, feature_order=order)
