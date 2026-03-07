"""Model inference engine.

Provides a high-level interface for generating predictions from
trained ML models. Handles model loading, feature building, and
structured output formatting.

Usage::

    engine = ModelInferenceEngine()
    probs = engine.predict_proba("mlb", "plate_appearance", profiles)
    # -> {"strikeout": 0.21, "walk": 0.08, ...}
"""

from __future__ import annotations

import logging
from typing import Any

from app.analytics.features.config.feature_config_loader import FeatureConfigLoader
from app.analytics.features.core.feature_builder import FeatureBuilder
from app.analytics.models.core.model_registry import ModelRegistry

from .inference_cache import InferenceCache

logger = logging.getLogger(__name__)


class ModelInferenceEngine:
    """Runtime inference engine for ML model predictions.

    Integrates the FeatureBuilder, FeatureConfigLoader, ModelRegistry,
    and InferenceCache to produce predictions from entity profiles.

    Args:
        registry: Optional ``ModelRegistry`` instance. Creates one
            if not provided.
        cache: Optional ``InferenceCache`` instance.
    """

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        cache: InferenceCache | None = None,
    ) -> None:
        self._registry = registry or ModelRegistry()
        self._cache = cache or InferenceCache()
        self._feature_builder = FeatureBuilder()
        self._config_loader = FeatureConfigLoader()
        # Track loaded model IDs for auto-reload detection
        self._loaded_model_ids: dict[str, str] = {}  # "sport:model_type" -> model_id

    def predict(
        self,
        sport: str,
        model_type: str,
        profiles: dict[str, Any],
        *,
        config_name: str | None = None,
    ) -> dict[str, Any]:
        """Generate a prediction from entity profiles.

        Args:
            sport: Sport code (e.g., ``"mlb"``).
            model_type: Model type (e.g., ``"plate_appearance"``,
                ``"game"``).
            profiles: Entity profiles dict (sport/model-specific keys
                like ``batter_profile``, ``pitcher_profile``).
            config_name: Optional feature config name for filtering.

        Returns:
            Prediction dict (sport/model-specific structure).
        """
        model = self._get_model(sport, model_type)
        if model is None:
            return {"error": "model_not_found", "sport": sport, "model_type": model_type}

        features = self._build_features(sport, model_type, profiles, config_name)
        return model.predict(features)

    def predict_proba(
        self,
        sport: str,
        model_type: str,
        profiles: dict[str, Any],
        *,
        config_name: str | None = None,
    ) -> dict[str, float]:
        """Generate probability distribution from entity profiles.

        Args:
            sport: Sport code.
            model_type: Model type.
            profiles: Entity profiles dict.
            config_name: Optional feature config name.

        Returns:
            Dict mapping outcome labels to probabilities.
        """
        model = self._get_model(sport, model_type)
        if model is None:
            return {}

        features = self._build_features(sport, model_type, profiles, config_name)
        return model.predict_proba(features)

    def predict_for_simulation(
        self,
        sport: str,
        model_type: str,
        profiles: dict[str, Any],
        *,
        config_name: str | None = None,
    ) -> dict[str, float]:
        """Generate simulation-ready probabilities.

        For plate-appearance models, converts to ``*_probability``
        keys. For game models, returns win probabilities directly.

        Args:
            sport: Sport code.
            model_type: Model type.
            profiles: Entity profiles dict.
            config_name: Optional feature config name.

        Returns:
            Dict of simulation probability keys.
        """
        model = self._get_model(sport, model_type)
        if model is None:
            return {}

        features = self._build_features(sport, model_type, profiles, config_name)
        probs = model.predict_proba(features)

        if hasattr(model, "to_simulation_probs"):
            return model.to_simulation_probs(probs)
        return probs

    def _get_model(self, sport: str, model_type: str) -> Any:
        """Get the active model instance, using cache for artifacts.

        Automatically detects when the active model has changed in the
        registry and invalidates the cached artifact so the new model
        is loaded on the next call.
        """
        sport = sport.lower()
        cache_key = f"{sport}:{model_type}"

        # Check if there's an active registered model with a path
        info = self._registry.get_active_model_info(sport, model_type)
        if info and info.get("path"):
            current_id = info["model_id"]
            path = info["path"]

            # Auto-reload: if the active model changed, invalidate old cache
            prev_id = self._loaded_model_ids.get(cache_key)
            if prev_id and prev_id != current_id:
                logger.info(
                    "model_switch_detected",
                    extra={"previous": prev_id, "current": current_id},
                )
                self._cache.clear()

            try:
                sklearn_model = self._cache.get_model(path)
                # Wrap in the appropriate model class
                wrapper = self._registry.get_active_model_instance(sport, model_type)
                if wrapper is not None:
                    wrapper._model = sklearn_model
                    wrapper._loaded = True
                    self._loaded_model_ids[cache_key] = current_id
                    return wrapper
            except (FileNotFoundError, RuntimeError, ModuleNotFoundError) as exc:
                logger.warning(
                    "artifact_load_failed",
                    extra={"path": path, "error": str(exc)},
                )

        # Fall back to built-in model (rule-based or with its own artifact)
        return self._registry.get_active_model_instance(sport, model_type)

    def _build_features(
        self,
        sport: str,
        model_type: str,
        profiles: dict[str, Any],
        config_name: str | None,
    ) -> dict[str, Any]:
        """Build feature dict from profiles.

        Returns feature values as a flat dict suitable for model
        wrapper ``predict()`` / ``predict_proba()`` methods.
        """
        config = None
        if config_name:
            try:
                cfg = self._config_loader.load_config(config_name)
                config = cfg.to_builder_config()
            except FileNotFoundError:
                pass

        vec = self._feature_builder.build_features(
            sport, profiles, model_type, config=config,
        )

        return vec.to_dict()
