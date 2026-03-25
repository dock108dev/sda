"""NCAAB feature builder for ML models.

Converts NCAAB analytics profiles (home team, away team) into feature
vectors for possession and game-level ML models.  Uses the four-factors
framework: eFG%, TOV%, ORB%, FT rate on both offensive and defensive
sides.

Feature names are prefixed by side (``home_``, ``away_``) to avoid
collisions.

Usage::

    builder = NCAABFeatureBuilder()
    vec = builder.build_features(profiles, "possession")
"""

from __future__ import annotations

from typing import Any

from app.analytics.features.core.feature_vector import FeatureVector
from app.analytics.sports.ncaab.constants import FEATURE_BASELINES as _BASELINES

# Possession model features: (feature_name, source_entity, source_key)
_POSSESSION_FEATURES: list[tuple[str, str, str]] = [
    ("home_off_rating", "home_profile", "off_rating"),
    ("home_def_rating", "home_profile", "def_rating"),
    ("home_pace", "home_profile", "pace"),
    ("home_off_efg_pct", "home_profile", "off_efg_pct"),
    ("home_off_tov_pct", "home_profile", "off_tov_pct"),
    ("home_off_orb_pct", "home_profile", "off_orb_pct"),
    ("home_off_ft_rate", "home_profile", "off_ft_rate"),
    ("home_def_efg_pct", "home_profile", "def_efg_pct"),
    ("home_def_tov_pct", "home_profile", "def_tov_pct"),
    ("home_def_orb_pct", "home_profile", "def_orb_pct"),
    ("home_def_ft_rate", "home_profile", "def_ft_rate"),
    ("away_off_rating", "away_profile", "off_rating"),
    ("away_def_rating", "away_profile", "def_rating"),
    ("away_pace", "away_profile", "pace"),
    ("away_off_efg_pct", "away_profile", "off_efg_pct"),
    ("away_off_tov_pct", "away_profile", "off_tov_pct"),
    ("away_off_orb_pct", "away_profile", "off_orb_pct"),
    ("away_off_ft_rate", "away_profile", "off_ft_rate"),
    ("away_def_efg_pct", "away_profile", "def_efg_pct"),
    ("away_def_tov_pct", "away_profile", "def_tov_pct"),
    ("away_def_orb_pct", "away_profile", "def_orb_pct"),
    ("away_def_ft_rate", "away_profile", "def_ft_rate"),
]

_GAME_FEATURES: list[tuple[str, str, str]] = _POSSESSION_FEATURES


class NCAABFeatureBuilder:
    """Build NCAAB feature vectors from analytics profiles."""

    def build_features(
        self,
        entity_profiles: dict[str, Any],
        model_type: str,
    ) -> FeatureVector:
        """Route to the appropriate feature builder by model type.

        Args:
            entity_profiles: Dict of profile data keyed by entity
                role (``home_profile``, ``away_profile``).
            model_type: ``"possession"`` or ``"game"``.

        Returns:
            ``FeatureVector`` with ordered features.
        """
        if model_type in ("possession", "game"):
            return self._build_from_spec(_POSSESSION_FEATURES, entity_profiles)
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
