"""Model registry, inference, and ensemble configuration endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

logger = logging.getLogger(__name__)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.inference.model_inference_engine import ModelInferenceEngine
from app.dependencies.roles import require_admin
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
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List registered models from completed training jobs.

    Combines DB-backed training jobs (authoritative) with the file-based
    registry for active-model status.
    """
    from app.db.analytics import AnalyticsTrainingJob

    # Query completed training jobs that produced a model
    stmt = (
        select(AnalyticsTrainingJob)
        .where(
            AnalyticsTrainingJob.status == "completed",
            AnalyticsTrainingJob.model_id.isnot(None),
        )
        .order_by(AnalyticsTrainingJob.created_at.desc())
    )
    if sport:
        stmt = stmt.where(AnalyticsTrainingJob.sport == sport)
    if model_type:
        stmt = stmt.where(AnalyticsTrainingJob.model_type == model_type)

    result = await db.execute(stmt)
    jobs = result.scalars().all()

    # Get active model IDs from file registry (if available)
    active_ids: set[str] = set()
    try:
        file_models = _model_registry.list_models(sport=sport, model_type=model_type)
        active_ids = {m["model_id"] for m in file_models if m.get("active")}
    except Exception:
        logger.debug("model_registry_lookup_failed", exc_info=True)

    models: list[dict[str, Any]] = []
    for job in jobs:
        is_active = job.model_id in active_ids
        if active_only and not is_active:
            continue
        # Check artifact existence on disk
        artifact_path = job.artifact_path
        if artifact_path and Path(artifact_path).is_file():
            artifact_status = "valid"
        elif artifact_path:
            artifact_status = "missing"
        else:
            artifact_status = "no_path"

        models.append({
            "model_id": job.model_id,
            "artifact_path": artifact_path,
            "version": job.id,  # use job ID as version
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "metrics": job.metrics or {},
            "sport": job.sport,
            "model_type": job.model_type,
            "active": is_active,
            "artifact_status": artifact_status,
            "feature_config_id": job.feature_config_id,
            "algorithm": job.algorithm,
            "train_count": job.train_count,
            "test_count": job.test_count,
            "feature_importance": getattr(job, "feature_importance", None),
        })

    # Sort
    if sort_by:
        key_fn: Any
        if sort_by == "created_at":
            key_fn = lambda m: m.get("created_at") or ""
        elif sort_by == "version":
            key_fn = lambda m: m.get("version") or 0
        else:
            key_fn = lambda m: m.get("metrics", {}).get(sort_by, 0) or 0
        models.sort(key=key_fn, reverse=sort_desc)

    return {"models": models, "count": len(models)}


@router.get("/models/details")
async def get_model_details(
    model_id: str = Query(..., description="Model ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get full details for a single registered model.

    Pulls from the training job DB record (authoritative), falling back
    to the file-based registry.
    """
    from app.db.analytics import AnalyticsTrainingJob

    stmt = (
        select(AnalyticsTrainingJob)
        .where(AnalyticsTrainingJob.model_id == model_id)
        .order_by(AnalyticsTrainingJob.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()

    if job:
        active_ids: set[str] = set()
        try:
            file_models = _model_registry.list_models(
                sport=job.sport, model_type=job.model_type,
            )
            active_ids = {m["model_id"] for m in file_models if m.get("active")}
        except Exception:
            logger.debug("model_registry_lookup_failed", exc_info=True)

        return {
            "model_id": job.model_id,
            "artifact_path": job.artifact_path,
            "version": job.id,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "metrics": job.metrics or {},
            "sport": job.sport,
            "model_type": job.model_type,
            "active": job.model_id in active_ids,
            "algorithm": job.algorithm,
            "train_count": job.train_count,
            "test_count": job.test_count,
            "feature_names": job.feature_names,
            "feature_importance": getattr(job, "feature_importance", None),
            "date_start": job.date_start,
            "date_end": job.date_end,
            "rolling_window": getattr(job, "rolling_window", None),
        }

    # Fall back to file registry
    details = _model_service.get_model_details(model_id)
    if details is None:
        return {"status": "not_found", "model_id": model_id}
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


@router.post("/models/activate", dependencies=[Depends(require_admin)])
async def post_activate_model(
    req: ModelActivateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Activate a registered model and clear the inference cache.

    If the model exists in the DB (training jobs) but not in the
    file registry, it is auto-registered first so activation succeeds.
    """
    from app.db.analytics import AnalyticsTrainingJob

    # Ensure model is in the file registry (it may only be in DB if
    # training ran in a different container)
    bucket = _model_registry._get_bucket(req.sport.lower(), req.model_type)
    model_in_registry = False
    if bucket:
        model_in_registry = any(
            m["model_id"] == req.model_id for m in bucket.get("models", [])
        )

    if not model_in_registry:
        # Look up the model in DB training jobs
        stmt = (
            select(AnalyticsTrainingJob)
            .where(
                AnalyticsTrainingJob.model_id == req.model_id,
                AnalyticsTrainingJob.status == "completed",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return {"status": "error", "message": "Model not found"}

        # Register in file registry so activate_model can find it
        _model_registry.register_model(
            sport=job.sport,
            model_type=job.model_type,
            model_id=job.model_id,
            artifact_path=job.artifact_path or "",
            metadata=job.metrics or {},
        )

    result = _model_registry.activate_model(
        sport=req.sport,
        model_type=req.model_type,
        model_id=req.model_id,
    )
    if result["status"] == "success":
        _inference_engine._cache.clear()
    return result


class ModelDeleteRequest(BaseModel):
    """Request body for DELETE /api/analytics/models."""
    model_id: str = Field(..., description="Model ID to delete")
    delete_artifact: bool = Field(
        False, description="Also delete the .pkl artifact file from disk",
    )


@router.delete("/models", dependencies=[Depends(require_admin)])
async def delete_model(
    req: ModelDeleteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a model from the DB and file registry.

    Deactivates the model if it is currently active, removes it from
    the file registry, deletes the training job DB row, and optionally
    removes the artifact file from disk.
    """
    from app.db.analytics import AnalyticsTrainingJob

    # Look up the training job to get sport/model_type
    stmt = (
        select(AnalyticsTrainingJob)
        .where(AnalyticsTrainingJob.model_id == req.model_id)
        .limit(1)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()

    if job is None:
        return {"status": "not_found", "model_id": req.model_id}

    sport = job.sport
    model_type = job.model_type
    artifact_path = job.artifact_path

    # Remove from file registry (also deactivates if active)
    _model_registry.remove_model(sport, model_type, req.model_id)

    # Clear inference cache in case this was the active model
    _inference_engine._cache.clear()

    # Delete training job from DB
    await db.delete(job)
    await db.commit()

    # Optionally delete artifact file
    artifact_deleted = False
    if req.delete_artifact and artifact_path:
        artifact = Path(artifact_path)
        if artifact.is_file():
            artifact.unlink()
            artifact_deleted = True

    return {
        "status": "deleted",
        "model_id": req.model_id,
        "artifact_deleted": artifact_deleted,
    }


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
        ..., description="List of {name, weight} dicts", min_length=1,
    )

    @field_validator("providers")
    @classmethod
    def validate_providers(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for i, p in enumerate(v):
            if "name" not in p or "weight" not in p:
                raise ValueError(f"Provider {i} must have 'name' and 'weight' keys")
            w = float(p["weight"])
            if w < 0:
                raise ValueError(
                    f"Provider '{p['name']}' has negative weight {w}; weights must be >= 0"
                )
        total = sum(float(p["weight"]) for p in v)
        if total <= 0:
            raise ValueError("Total weight must be > 0 (at least one provider needs a positive weight)")
        return v


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


@router.post("/ensemble-config", dependencies=[Depends(require_admin)])
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
