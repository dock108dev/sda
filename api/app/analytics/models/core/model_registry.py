"""Model registry for tracking and loading available ML models.

Maintains a catalog of registered models with version tracking and
active-model selection. Supports JSON persistence to disk and
in-memory operation.

The registry is organized by sport and model type, each supporting
multiple versioned models with one active at a time.

Usage::

    registry = ModelRegistry()
    registry.register_model(
        sport="mlb",
        model_type="plate_appearance",
        model_id="mlb_pa_model_v1",
        artifact_path="models/mlb/artifacts/mlb_pa_model_v1.pkl",
        metadata={"accuracy": 0.61},
    )
    registry.activate_model("mlb", "plate_appearance", "mlb_pa_model_v1")
    info = registry.get_active_model("mlb", "plate_appearance")
"""

from __future__ import annotations

import importlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / ".." / "models" / "registry" / "registry.json"
)

# Built-in model classes: (sport, model_type) -> (module_path, class_name)
_BUILTIN_MODELS: dict[tuple[str, str], tuple[str, str]] = {
    ("mlb", "plate_appearance"): (
        "app.analytics.models.sports.mlb.pa_model",
        "MLBPlateAppearanceModel",
    ),
    ("mlb", "game"): (
        "app.analytics.models.sports.mlb.game_model",
        "MLBGameModel",
    ),
    ("mlb", "pitch"): (
        "app.analytics.models.sports.mlb.pitch_model",
        "MLBPitchOutcomeModel",
    ),
    ("mlb", "batted_ball"): (
        "app.analytics.models.sports.mlb.batted_ball_model",
        "MLBBattedBallModel",
    ),
    ("mlb", "run_expectancy"): (
        "app.analytics.models.sports.mlb.run_expectancy_model",
        "MLBRunExpectancyModel",
    ),
    # NBA models
    ("nba", "possession"): (
        "app.analytics.models.sports.nba.possession_model",
        "NBAPossessionModel",
    ),
    ("nba", "game"): (
        "app.analytics.models.sports.nba.game_model",
        "NBAGameModel",
    ),
    # NHL models
    ("nhl", "shot"): (
        "app.analytics.models.sports.nhl.shot_model",
        "NHLShotModel",
    ),
    ("nhl", "game"): (
        "app.analytics.models.sports.nhl.game_model",
        "NHLGameModel",
    ),
    # NCAAB models
    ("ncaab", "possession"): (
        "app.analytics.models.sports.ncaab.possession_model",
        "NCAABPossessionModel",
    ),
    ("ncaab", "game"): (
        "app.analytics.models.sports.ncaab.game_model",
        "NCAABGameModel",
    ),
}


class ModelRegistry:
    """Tracks registered ML models and resolves active models.

    Models can be registered explicitly or loaded from built-in
    defaults. The registry supports JSON persistence for durability
    across restarts.

    Args:
        registry_path: Path to the JSON registry file. Set to
            ``None`` to operate in memory-only mode.
    """

    def __init__(self, registry_path: str | Path | None = _DEFAULT_REGISTRY_PATH) -> None:
        self._registry_path: Path | None = Path(registry_path) if registry_path else None
        self._data: dict[str, Any] = {}
        if self._registry_path is not None:
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_model(
        self,
        sport: str,
        model_type: str,
        model_id: str,
        artifact_path: str,
        metadata: dict[str, Any] | None = None,
        *,
        metadata_path: str | None = None,
        version: int | None = None,
    ) -> str:
        """Register a newly trained model in the registry.

        The model is NOT automatically activated. Call
        ``activate_model`` separately to make it the active model.

        Args:
            sport: Sport code (e.g., ``"mlb"``).
            model_type: Model type (e.g., ``"plate_appearance"``).
            model_id: Unique identifier for this model version.
            artifact_path: Path to the serialized model artifact.
            metadata: Optional dict of training metrics / info.
            metadata_path: Optional path to the metadata JSON file.
            version: Optional explicit version number. Auto-increments
                if not provided.

        Returns:
            The model_id.
        """
        sport = sport.lower()
        bucket = self._ensure_bucket(sport, model_type)
        models_list: list[dict[str, Any]] = bucket["models"]

        # Auto-version if not specified
        if version is None:
            existing_versions = [m.get("version", 0) for m in models_list]
            version = max(existing_versions, default=0) + 1

        # Check for duplicate model_id
        for existing in models_list:
            if existing["model_id"] == model_id:
                existing["artifact_path"] = artifact_path
                existing["metadata_path"] = metadata_path or existing.get("metadata_path")
                existing["metrics"] = metadata or existing.get("metrics", {})
                existing["version"] = version
                existing["updated_at"] = datetime.now(UTC).isoformat()
                self._save()
                logger.info("model_updated", extra={"model_id": model_id})
                return model_id

        record: dict[str, Any] = {
            "model_id": model_id,
            "artifact_path": artifact_path,
            "metadata_path": metadata_path,
            "version": version,
            "created_at": datetime.now(UTC).isoformat(),
            "metrics": metadata or {},
        }
        models_list.append(record)
        self._save()
        logger.info(
            "model_registered",
            extra={"model_id": model_id, "sport": sport, "model_type": model_type},
        )
        return model_id

    def get_active_model(self, sport: str, model_type: str) -> dict[str, Any] | None:
        """Return the currently active model metadata.

        Returns ``None`` if no model is active for the given
        sport + model_type combination.
        """
        sport = sport.lower()
        bucket = self._get_bucket(sport, model_type)
        if bucket is None:
            return None

        active_id = bucket.get("active_model")
        if not active_id:
            return None

        for model in bucket.get("models", []):
            if model["model_id"] == active_id:
                return model
        return None

    def list_models(
        self,
        sport: str | None = None,
        model_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all registered models, optionally filtered.

        Each returned dict includes an ``active`` boolean field
        indicating whether it is the currently active model.
        """
        results: list[dict[str, Any]] = []

        sports = [sport.lower()] if sport else list(self._data.keys())
        for s in sports:
            sport_data = self._data.get(s, {})
            types = [model_type] if model_type else list(sport_data.keys())
            for mt in types:
                bucket = sport_data.get(mt)
                if bucket is None:
                    continue
                active_id = bucket.get("active_model")
                for model in bucket.get("models", []):
                    entry = {
                        **model,
                        "sport": s,
                        "model_type": mt,
                        "active": model["model_id"] == active_id,
                    }
                    results.append(entry)
        return results

    def activate_model(
        self,
        sport: str,
        model_type: str,
        model_id: str,
        *,
        validate_paths: bool = False,
    ) -> dict[str, Any]:
        """Set a model as the active model for its sport + model_type.

        Args:
            sport: Sport code.
            model_type: Model type.
            model_id: Model ID to activate.
            validate_paths: If ``True``, verify that the artifact (and
                optionally metadata) file exists on disk before activating.

        Returns:
            Dict with ``status`` (``"success"`` or ``"error"``),
            ``active_model``, and optional ``message``.
        """
        sport = sport.lower()
        bucket = self._get_bucket(sport, model_type)
        if bucket is None:
            return {"status": "error", "message": "Model not found"}

        target = None
        for model in bucket.get("models", []):
            if model["model_id"] == model_id:
                target = model
                break

        if target is None:
            return {"status": "error", "message": "Model not found"}

        if validate_paths:
            artifact = target.get("artifact_path")
            if artifact and not Path(artifact).exists():
                return {"status": "error", "message": "Model artifact not found"}
            metadata = target.get("metadata_path")
            if metadata and not Path(metadata).exists():
                return {"status": "error", "message": "Model metadata not found"}

        previous = bucket.get("active_model")
        bucket["active_model"] = model_id
        self._save()
        logger.info(
            "model_activated",
            extra={
                "model_id": model_id,
                "previous": previous,
                "sport": sport,
                "model_type": model_type,
            },
        )
        return {"status": "success", "active_model": model_id}

    def deactivate_model(self, sport: str, model_type: str, model_id: str) -> bool:
        """Clear the active model if it matches model_id.

        Returns ``True`` if the model was the active one and was
        deactivated.
        """
        sport = sport.lower()
        bucket = self._get_bucket(sport, model_type)
        if bucket is None:
            return False

        if bucket.get("active_model") == model_id:
            bucket["active_model"] = None
            self._save()
            return True
        return False

    def remove_model(self, sport: str, model_type: str, model_id: str) -> bool:
        """Remove a model from the file registry.

        Deactivates it first if it's the active model. Returns ``True``
        if the model was found and removed.
        """
        sport = sport.lower()
        self.deactivate_model(sport, model_type, model_id)
        bucket = self._get_bucket(sport, model_type)
        if bucket is None:
            return False

        models_list: list[dict[str, Any]] = bucket.get("models", [])
        before = len(models_list)
        bucket["models"] = [m for m in models_list if m["model_id"] != model_id]
        if len(bucket["models"]) < before:
            self._save()
            logger.info("model_removed", extra={"model_id": model_id})
            return True
        return False

    # ------------------------------------------------------------------
    # Inference engine integration helpers
    # ------------------------------------------------------------------

    def get_active_model_info(
        self,
        sport: str,
        model_type: str,
    ) -> dict[str, Any] | None:
        """Get metadata for the active model (for inference engine).

        Returns a dict with at least ``model_id`` and ``path`` keys,
        or ``None`` if no active model is registered.
        """
        active = self.get_active_model(sport, model_type)
        if active is None:
            return None
        return {
            "model_id": active["model_id"],
            "path": active.get("artifact_path"),
            "sport": sport.lower(),
            "model_type": model_type,
            "version": active.get("version"),
            "metrics": active.get("metrics", {}),
        }

    def get_model_info_by_id(
        self,
        sport: str,
        model_type: str,
        model_id: str,
    ) -> dict[str, Any] | None:
        """Get metadata for a specific model by ID.

        Like ``get_active_model_info`` but looks up by ``model_id``
        instead of using the active model. Returns ``None`` if the
        model is not found.
        """
        sport = sport.lower()
        bucket = self._get_bucket(sport, model_type)
        if bucket is None:
            return None

        for model in bucket.get("models", []):
            if model["model_id"] == model_id:
                return {
                    "model_id": model["model_id"],
                    "path": model.get("artifact_path"),
                    "sport": sport,
                    "model_type": model_type,
                    "version": model.get("version"),
                    "metrics": model.get("metrics", {}),
                }
        return None

    def get_active_model_instance(self, sport: str, model_type: str) -> Any | None:
        """Get an instantiated model object for the active model.

        If a registered active model has an artifact path, returns
        a built-in model wrapper instance. Otherwise falls back to
        the default built-in model.
        """
        return self._load_builtin(sport.lower(), model_type)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_bucket(self, sport: str, model_type: str) -> dict[str, Any]:
        """Get or create the bucket for a sport + model_type."""
        if sport not in self._data:
            self._data[sport] = {}
        if model_type not in self._data[sport]:
            self._data[sport][model_type] = {"active_model": None, "models": []}
        return self._data[sport][model_type]

    def _get_bucket(self, sport: str, model_type: str) -> dict[str, Any] | None:
        sport_data = self._data.get(sport)
        if sport_data is None:
            return None
        return sport_data.get(model_type)

    def _load(self) -> None:
        """Load registry from JSON file if it exists."""
        if self._registry_path is None or not self._registry_path.exists():
            self._data = {}
            return
        try:
            with open(self._registry_path) as f:
                self._data = json.load(f)
            logger.debug("registry_loaded", extra={"path": str(self._registry_path)})
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("registry_load_failed", extra={"error": str(exc)})
            self._data = {}

    def _save(self) -> None:
        """Persist registry to JSON file."""
        if self._registry_path is None:
            return
        try:
            self._registry_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._registry_path, "w") as f:
                json.dump(self._data, f, indent=2)
        except OSError as exc:
            logger.error("registry_save_failed", extra={"error": str(exc)})

    def _load_builtin(self, sport: str, model_type: str) -> Any | None:
        """Load a built-in model class from the registry."""
        entry = _BUILTIN_MODELS.get((sport, model_type))
        if entry is None:
            return None
        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls()
