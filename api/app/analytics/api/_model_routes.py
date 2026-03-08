"""Model registry, inference, and ensemble configuration endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.inference.model_inference_engine import ModelInferenceEngine
from app.analytics.models.core.model_registry import ModelRegistry
from app.analytics.services.model_service import ModelService
from app.db import get_db

router = APIRouter()

_model_registry = ModelRegistry()
_model_service = ModelService(registry=_model_registry)
_inference_engine = ModelInferenceEngine(registry=_model_registry)


# ---------------------------------------------------------------------------
# Model Inference
# ---------------------------------------------------------------------------


class ModelPredictRequest(BaseModel):
    """Request body for POST /api/analytics/model-predict."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance, game)")
    profiles: dict[str, Any] = Field(
        default_factory=dict, description="Entity profiles for prediction",
    )
    config_name: str | None = Field(None, description="Feature config name for filtering")


@router.post("/model-predict")
async def post_model_predict(req: ModelPredictRequest) -> dict[str, Any]:
    """Run a model prediction with provided profiles."""
    probs = _inference_engine.predict_proba(
        sport=req.sport,
        model_type=req.model_type,
        profiles=req.profiles,
        config_name=req.config_name,
    )
    return {
        "sport": req.sport,
        "model_type": req.model_type,
        "probabilities": probs,
    }


@router.get("/model-predict")
async def get_model_predict(
    sport: str = Query("mlb", description="Sport code"),
    model_type: str = Query("plate_appearance", description="Model type"),
) -> dict[str, Any]:
    """Sample prediction with empty profiles (uses model defaults)."""
    probs = _inference_engine.predict_proba(
        sport=sport, model_type=model_type, profiles={},
    )
    return {
        "sport": sport,
        "model_type": model_type,
        "probabilities": probs,
    }


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------


class ModelActivateRequest(BaseModel):
    """Request body for POST /api/analytics/models/activate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance)")
    model_id: str = Field(..., description="Model ID to activate")


@router.get("/models")
async def get_models(
    sport: str = Query(None, description="Filter by sport code"),
    model_type: str = Query(None, description="Filter by model type"),
    sort_by: str = Query(
        None, description="Sort key (created_at, accuracy, log_loss, brier_score, version)",
    ),
    sort_desc: bool = Query(True, description="Sort descending"),
    active_only: bool = Query(False, description="Only show active models"),
) -> dict[str, Any]:
    """List registered models with active status, filtering, and sorting."""
    return _model_service.list_models(
        sport=sport,
        model_type=model_type,
        sort_by=sort_by,
        sort_desc=sort_desc,
        active_only=active_only,
    )


@router.get("/models/details")
async def get_model_details(
    model_id: str = Query(..., description="Model ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get full details for a single registered model.

    Enriches registry data with feature importance from the training job.
    """
    details = _model_service.get_model_details(model_id)
    if details is None:
        return {"status": "not_found", "model_id": model_id}

    from app.db.analytics import AnalyticsTrainingJob

    stmt = (
        select(AnalyticsTrainingJob)
        .where(AnalyticsTrainingJob.model_id == model_id)
        .order_by(AnalyticsTrainingJob.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    training_job = result.scalar_one_or_none()
    if training_job:
        fi = getattr(training_job, "feature_importance", None)
        if fi:
            details["feature_importance"] = fi

    return details


@router.get("/models/compare")
async def get_model_compare(
    sport: str = Query(..., description="Sport code"),
    model_type: str = Query(..., description="Model type"),
    model_ids: str = Query(..., description="Comma-separated model IDs"),
) -> dict[str, Any]:
    """Compare evaluation metrics across model versions."""
    ids = [mid.strip() for mid in model_ids.split(",") if mid.strip()]
    return _model_service.compare_models(sport, model_type, ids)


@router.post("/models/activate")
async def post_activate_model(req: ModelActivateRequest) -> dict[str, Any]:
    """Activate a registered model and clear the inference cache."""
    result = _model_service.activate_model(
        sport=req.sport,
        model_type=req.model_type,
        model_id=req.model_id,
    )
    if result["status"] == "success":
        _inference_engine._cache.clear()
    return result


@router.get("/models/active")
async def get_active_models(
    sport: str = Query(..., description="Sport code"),
    model_type: str = Query(..., description="Model type"),
) -> dict[str, Any]:
    """Get the currently active model for a sport + model type."""
    active = _model_registry.get_active_model(sport, model_type)
    if active is None:
        return {
            "sport": sport,
            "model_type": model_type,
            "active_model": None,
        }
    return {
        "sport": sport,
        "model_type": model_type,
        "active_model": active["model_id"],
        "version": active.get("version"),
        "metrics": active.get("metrics", {}),
    }


@router.get("/model-metrics")
async def get_model_metrics(
    model_id: str = Query(None, description="Filter by model ID"),
    sport: str = Query(None, description="Filter by sport code"),
    model_type: str = Query(None, description="Filter by model type"),
) -> dict[str, Any]:
    """Get evaluation metrics for registered models."""
    models = _model_registry.list_models(sport=sport, model_type=model_type)

    if model_id:
        models = [m for m in models if m["model_id"] == model_id]

    if not models:
        return {"models": [], "count": 0}

    results = []
    for m in models:
        results.append({
            "model_id": m["model_id"],
            "sport": m.get("sport", ""),
            "model_type": m.get("model_type", ""),
            "version": m.get("version"),
            "active": m.get("active", False),
            "metrics": m.get("metrics", {}),
        })

    return {"models": results, "count": len(results)}


# ---------------------------------------------------------------------------
# Ensemble Configuration
# ---------------------------------------------------------------------------


class EnsembleConfigRequest(BaseModel):
    """Request body for POST /api/analytics/ensemble-config."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    model_type: str = Field(..., description="Model type (e.g., plate_appearance)")
    providers: list[dict[str, Any]] = Field(
        ..., description="List of {name, weight} dicts",
    )


@router.get("/ensemble-config")
async def get_ensemble_config_endpoint(
    sport: str = Query(..., description="Sport code"),
    model_type: str = Query(..., description="Model type"),
) -> dict[str, Any]:
    """Get the ensemble configuration for a sport + model type."""
    from app.analytics.ensemble.ensemble_config import get_ensemble_config
    config = get_ensemble_config(sport, model_type)
    return config.to_dict()


@router.get("/ensemble-configs")
async def list_ensemble_configs_endpoint() -> dict[str, Any]:
    """List all ensemble configurations."""
    from app.analytics.ensemble.ensemble_config import list_ensemble_configs
    configs = list_ensemble_configs()
    return {"configs": [c.to_dict() for c in configs], "count": len(configs)}


@router.post("/ensemble-config")
async def post_ensemble_config(req: EnsembleConfigRequest) -> dict[str, Any]:
    """Update ensemble configuration for a sport + model type."""
    from app.analytics.ensemble.ensemble_config import (
        EnsembleConfig,
        ProviderWeight,
        set_ensemble_config,
    )

    providers = [
        ProviderWeight(name=p["name"], weight=float(p["weight"]))
        for p in req.providers
    ]
    config = EnsembleConfig(
        sport=req.sport,
        model_type=req.model_type,
        providers=providers,
    )
    set_ensemble_config(config)
    return {"status": "updated", **config.to_dict()}
