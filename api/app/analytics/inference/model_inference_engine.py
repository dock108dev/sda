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

from app.analytics.features.core.feature_builder import FeatureBuilder
from app.analytics.models.core.model_registry import ModelRegistry

from .inference_cache import InferenceCache

logger = logging.getLogger(__name__)


class ModelInferenceEngine:
    """Runtime inference engine for ML model predictions.

    Integrates the FeatureBuilder, ModelRegistry, and InferenceCache
    to produce predictions from entity profiles.

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
        model_id: str | None = None,
    ) -> dict[str, float]:
        """Generate probability distribution from entity profiles.

        Args:
            sport: Sport code.
            model_type: Model type.
            profiles: Entity profiles dict.
            config_name: Optional feature config name.
            model_id: Optional specific model ID to use instead
                of the active model.

        Returns:
            Dict mapping outcome labels to probabilities.
        """
        model = self._get_model(sport, model_type, model_id=model_id)
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

    def get_model_status(self, sport: str, model_type: str) -> dict[str, Any]:
        """Return structured status for the active model.

        Returns a dict with ``available``, ``model_id``, ``version``,
        ``trained_at``, ``metrics``, and ``reason`` (when unavailable).
        """
        sport = sport.lower()
        info = self._registry.get_active_model_info(sport, model_type)
        if not info:
            return {
                "available": False,
                "model_id": None,
                "version": None,
                "trained_at": None,
                "metrics": {},
                "reason": "no_active_model",
            }

        path = info.get("path")
        if not path:
            return {
                "available": False,
                "model_id": info.get("model_id"),
                "version": info.get("version"),
                "trained_at": info.get("trained_at"),
                "metrics": info.get("metrics", {}),
                "reason": "no_artifact_path",
            }

        # Check whether the artifact file actually exists on disk
        from pathlib import Path
        artifact_exists = Path(path).is_file()

        return {
            "available": artifact_exists,
            "model_id": info.get("model_id"),
            "version": info.get("version"),
            "trained_at": info.get("trained_at"),
            "metrics": info.get("metrics", {}),
            "reason": None if artifact_exists else "artifact_not_found",
        }

    def _get_model(
        self,
        sport: str,
        model_type: str,
        *,
        model_id: str | None = None,
    ) -> Any:
        """Get a model instance, using cache for artifacts.

        When ``model_id`` is provided, loads that specific model
        instead of the active one. Otherwise automatically detects
        when the active model has changed in the registry and
        invalidates the cached artifact.
        """
        sport = sport.lower()
        cache_key = f"{sport}:{model_type}"

        # Resolve model info — specific model_id or active model
        if model_id:
            info = self._registry.get_model_info_by_id(sport, model_type, model_id)
            cache_key = f"{sport}:{model_type}:{model_id}"
        else:
            info = self._registry.get_active_model_info(sport, model_type)

        if info and info.get("path"):
            current_id = info["model_id"]
            path = info["path"]

            # Auto-reload: if the active model changed, invalidate old cache
            if not model_id:
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
                return None

        # No registered model with a path — fall back to built-in model
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
        vec = self._feature_builder.build_features(
            sport, profiles, model_type,
        )

        return vec.to_dict()
