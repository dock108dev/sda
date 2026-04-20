"""Model service layer for the admin dashboard.

Combines ModelRegistry data, training metadata, and ModelMetrics
to provide structured responses for the model performance dashboard.

Usage::

    service = ModelService(registry)
    models = service.list_models(sport="mlb", model_type="plate_appearance")
    details = service.get_model_details("mlb_pa_model_v1")
    comparison = service.compare_models("mlb", "plate_appearance", ["v1", "v2"])
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.analytics.models.core.model_metrics import ModelMetrics
from app.analytics.models.core.model_registry import ModelRegistry

logger = logging.getLogger(__name__)


class ModelService:
    """Service layer aggregating model registry, metadata, and metrics.

    All responses are pre-computed from stored data — no expensive
    calculations are performed.

    Args:
        registry: ModelRegistry instance to read from.
    """

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self._registry = registry or ModelRegistry()
        self._metrics = ModelMetrics()

    def list_models(
        self,
        sport: str | None = None,
        model_type: str | None = None,
        *,
        sort_by: str | None = None,
        sort_desc: bool = True,
        active_only: bool = False,
    ) -> dict[str, Any]:
        """List registered models with optional filtering and sorting.

        Args:
            sport: Filter by sport code.
            model_type: Filter by model type.
            sort_by: Sort key (``created_at``, ``accuracy``,
                ``log_loss``, ``brier_score``, ``version``).
            sort_desc: Sort descending if True.
            active_only: Only return active models.

        Returns:
            Dict with ``models`` list and ``count``.
        """
        models = self._registry.list_models(sport=sport, model_type=model_type)

        if active_only:
            models = [m for m in models if m.get("active")]

        if sort_by:
            models = _sort_models(models, sort_by, sort_desc)

        return {
            "models": models,
            "count": len(models),
        }

    def get_model_details(self, model_id: str) -> dict[str, Any] | None:
        """Get full details for a single model.

        Enriches registry data with training metadata if the
        metadata file exists on disk.
        """
        models = self._registry.list_models()
        target = None
        for m in models:
            if m["model_id"] == model_id:
                target = m
                break

        if target is None:
            return None

        result: dict[str, Any] = {
            "model_id": target["model_id"],
            "sport": target.get("sport", ""),
            "model_type": target.get("model_type", ""),
            "version": target.get("version"),
            "active": target.get("active", False),
            "artifact_path": target.get("artifact_path"),
            "metadata_path": target.get("metadata_path"),
            "created_at": target.get("created_at"),
            "metrics": target.get("metrics", {}),
        }

        # Enrich from training metadata file if available
        metadata_path = target.get("metadata_path")
        if metadata_path:
            extra = _load_training_metadata(metadata_path)
            if extra:
                result["feature_config"] = extra.get("feature_config", "")
                result["training_row_count"] = extra.get(
                    "training_row_count", 0,
                )
                result["random_state"] = extra.get("random_state")

        return result

    def compare_models(
        self,
        sport: str,
        model_type: str,
        model_ids: list[str],
    ) -> dict[str, Any]:
        """Compare evaluation metrics across model versions.

        Args:
            sport: Sport code.
            model_type: Model type.
            model_ids: List of model IDs to compare.

        Returns:
            Dict with ``sport``, ``model_type``, ``models`` list,
            and optional ``comparison`` (if exactly 2 models).
        """
        all_models = self._registry.list_models(sport=sport, model_type=model_type)
        selected = [m for m in all_models if m["model_id"] in model_ids]

        entries = []
        for m in selected:
            entries.append({
                "model_id": m["model_id"],
                "version": m.get("version"),
                "active": m.get("active", False),
                "metrics": m.get("metrics", {}),
            })

        result: dict[str, Any] = {
            "sport": sport,
            "model_type": model_type,
            "models": entries,
        }

        # If exactly 2 models, provide automated comparison
        if len(entries) == 2:
            m_a = entries[0].get("metrics", {})
            m_b = entries[1].get("metrics", {})
            result["comparison"] = self._metrics.compare_models(
                m_a, m_b,
                model_a_id=entries[0]["model_id"],
                model_b_id=entries[1]["model_id"],
            )

        return result

    def activate_model(
        self,
        sport: str,
        model_type: str,
        model_id: str,
    ) -> dict[str, Any]:
        """Activate a model with validation.

        Verifies the model exists and that artifact/metadata paths
        are valid before delegating to the registry.

        Returns:
            Dict with ``status`` and ``active_model`` on success,
            or ``status`` and ``message`` on failure.
        """
        return self._registry.activate_model(
            sport, model_type, model_id, validate_paths=True,
        )


def _sort_models(
    models: list[dict[str, Any]],
    sort_by: str,
    descending: bool,
) -> list[dict[str, Any]]:
    """Sort model list by a key. Metrics keys are looked up inside metrics dict."""

    def key_fn(m: dict[str, Any]) -> Any:
        if sort_by in ("created_at", "version", "model_id"):
            return m.get(sort_by, "")
        # Metric key
        val = m.get("metrics", {}).get(sort_by)
        if val is None:
            return float("inf") if not descending else float("-inf")
        return val

    return sorted(models, key=key_fn, reverse=descending)


def _load_training_metadata(path: str) -> dict[str, Any] | None:
    """Attempt to load training metadata from a JSON file."""
    try:
        p = Path(path)
        if p.exists():
            with open(p) as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("training_metadata_load_failed", extra={"path": path}, exc_info=True)
    return None
