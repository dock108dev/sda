"""Sport-agnostic feature builder.

Routes to sport-specific feature builders via a registry pattern.
Accepts analytics profiles and model type, returning a ``FeatureVector``
ready for ML model consumption. Supports configuration-driven feature
selection and weighting via ``FeatureConfig``.

Usage::

    builder = FeatureBuilder()
    vec = builder.build_features("mlb", profiles, "plate_appearance")
    arr = vec.to_array()

With configuration (from DB-backed AnalyticsFeatureConfig)::

    config = {"feat_a": {"enabled": True, "weight": 0.9}}
    vec = builder.build_features("mlb", profiles, "plate_appearance",
                                 config=config)
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from .feature_vector import FeatureVector

logger = logging.getLogger(__name__)

# Registry: sport -> (module_path, class_name)
_SPORT_FEATURE_BUILDERS: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.features.sports.mlb_features", "MLBFeatureBuilder"),
    "nba": ("app.analytics.features.sports.nba_features", "NBAFeatureBuilder"),
    "nhl": ("app.analytics.features.sports.nhl_features", "NHLFeatureBuilder"),
    "ncaab": ("app.analytics.features.sports.ncaab_features", "NCAABFeatureBuilder"),
}


class FeatureBuilder:
    """Build feature vectors from analytics profiles.

    Delegates to sport-specific builders while providing a uniform
    interface for the ML pipeline.
    """

    def __init__(self) -> None:
        self._builders: dict[str, Any] = {}

    def build_features(
        self,
        sport: str,
        entity_profiles: dict[str, Any],
        model_type: str,
        config: dict[str, Any] | None = None,
    ) -> FeatureVector:
        """Build a feature vector from entity profiles.

        Args:
            sport: Sport code (e.g., ``"mlb"``).
            entity_profiles: Dict of profile data. Keys depend on
                sport and model type (e.g., ``batter_profile``,
                ``pitcher_profile``).
            model_type: Target model type (e.g.,
                ``"plate_appearance"``, ``"game"``).
            config: Optional feature configuration dict. Keys are
                feature names; each value is a dict with ``enabled``
                (bool) and optional ``weight`` (float).

        Returns:
            ``FeatureVector`` with features in deterministic order.
        """
        sport = sport.lower()
        builder = self._get_sport_builder(sport)
        if builder is None:
            logger.warning("no_feature_builder", extra={"sport": sport})
            return FeatureVector({})

        vec = builder.build_features(entity_profiles, model_type)

        if config:
            vec = _apply_config(vec, config)

        return vec

    def build_dataset(
        self,
        sport: str,
        records: list[dict[str, Any]],
        model_type: str,
        config: dict[str, Any] | None = None,
    ) -> tuple[list[list[float]], list[str]]:
        """Build a feature matrix from multiple records.

        Args:
            sport: Sport code.
            records: List of entity profile dicts.
            model_type: Target model type.
            config: Optional feature config.

        Returns:
            Tuple of ``(X, feature_names)`` where X is a list of
            float arrays, one per record.
        """
        vectors = [
            self.build_features(sport, rec, model_type, config)
            for rec in records
        ]
        if not vectors:
            return [], []

        names = vectors[0].feature_names
        X = [v.to_array() for v in vectors]
        return X, names

    def _get_sport_builder(self, sport: str) -> Any:
        """Lazily load and cache the sport-specific feature builder."""
        if sport in self._builders:
            return self._builders[sport]

        entry = _SPORT_FEATURE_BUILDERS.get(sport)
        if entry is None:
            return None

        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        self._builders[sport] = cls()
        return self._builders[sport]


def _apply_config(vec: FeatureVector, config: dict[str, Any]) -> FeatureVector:
    """Filter disabled features and apply weights from config."""
    raw = vec.to_dict()
    order = vec.feature_names

    filtered: dict[str, float] = {}
    new_order: list[str] = []

    for name in order:
        cfg = config.get(name, {})
        if cfg.get("enabled", True) is False:
            continue
        weight = float(cfg.get("weight", 1.0))
        filtered[name] = raw.get(name, 0.0) * weight
        new_order.append(name)

    return FeatureVector(filtered, feature_order=new_order)
