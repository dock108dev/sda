"""Training and batch simulation endpoints."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies.roles import require_admin

router = APIRouter()


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


class TrainModelRequest(BaseModel):
    """Request body for POST /api/analytics/train."""
    feature_config_id: int | None = Field(None, description="Feature loadout ID from DB")
    sport: str = Field("mlb", description="Sport code")
    model_type: str = Field("game", description="Model type")
    date_start: str | None = Field(None, description="Training data start date (YYYY-MM-DD)")
    date_end: str | None = Field(None, description="Training data end date (YYYY-MM-DD)")
    test_split: float = Field(0.2, ge=0.05, le=0.5, description="Test set fraction")
    algorithm: str = Field("gradient_boosting", description="Algorithm: gradient_boosting, random_forest, xgboost")
    random_state: int = Field(42, description="Random seed for reproducibility")
    rolling_window: int = Field(30, ge=5, le=162, description="Rolling window size (prior games for profile aggregation)")


def _serialize_training_job(job) -> dict[str, Any]:
    """Serialize a training job row to API response."""
    return {
        "id": job.id,
        "feature_config_id": job.feature_config_id,
        "sport": job.sport,
        "model_type": job.model_type,
        "algorithm": job.algorithm,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "test_split": job.test_split,
        "random_state": job.random_state,
        "rolling_window": getattr(job, "rolling_window", 30),
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "model_id": job.model_id,
        "artifact_path": job.artifact_path,
        "metrics": job.metrics,
        "train_count": job.train_count,
        "test_count": job.test_count,
        "feature_names": job.feature_names,
        "feature_importance": getattr(job, "feature_importance", None),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/train", dependencies=[Depends(require_admin)])
async def start_training(
    req: TrainModelRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a model training job.

    Creates a training job record and dispatches a Celery task.
    """
    from app.db.analytics import AnalyticsTrainingJob

    try:
        job = AnalyticsTrainingJob(
            feature_config_id=req.feature_config_id,
            sport=req.sport.lower(),
            model_type=req.model_type,
            algorithm=req.algorithm,
            date_start=req.date_start,
            date_end=req.date_end,
            test_split=req.test_split,
            random_state=req.random_state,
            rolling_window=req.rolling_window,
            status="pending",
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)
    except Exception:
        logger.exception("Failed to create training job")
        raise HTTPException(
            status_code=500,
            detail="Failed to create training job",
        )

    try:
        from app.tasks.training_tasks import train_analytics_model
        task = train_analytics_model.delay(job.id)
        job.celery_task_id = task.id
        job.status = "queued"
        await db.flush()
    except Exception:
        logger.exception("Failed to dispatch training task job_id=%s", job.id)
        job.status = "failed"
        job.error_message = "Failed to dispatch task"
        await db.flush()

    # Refresh after second flush so server-side onupdate columns
    # (updated_at) are loaded — avoids MissingGreenlet on serialize.
    await db.refresh(job)

    return {"status": "submitted", "job": _serialize_training_job(job)}


@router.get("/training-jobs")
async def list_training_jobs(
    sport: str = Query(None, description="Filter by sport"),
    status: str = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List training jobs with optional filtering."""
    from app.db.analytics import AnalyticsTrainingJob

    stmt = select(AnalyticsTrainingJob).order_by(
        AnalyticsTrainingJob.created_at.desc()
    ).limit(limit)

    if sport:
        stmt = stmt.where(AnalyticsTrainingJob.sport == sport)
    if status:
        stmt = stmt.where(AnalyticsTrainingJob.status == status)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {
        "jobs": [_serialize_training_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/training-job/{job_id}")
async def get_training_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific training job."""
    from app.db.analytics import AnalyticsTrainingJob

    job = await db.get(AnalyticsTrainingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Training job not found")
    return _serialize_training_job(job)


@router.post("/training-job/{job_id}/cancel", dependencies=[Depends(require_admin)])
async def cancel_training_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cancel a queued or running training job."""
    from app.db.analytics import AnalyticsTrainingJob

    job = await db.get(AnalyticsTrainingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Training job not found")

    if job.status not in ("pending", "queued", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{job.status}'",
        )

    # Revoke the Celery task if we have a task ID
    if job.celery_task_id:
        try:
            from app.celery_app import celery_app
            celery_app.control.revoke(job.celery_task_id, terminate=True)
        except Exception:
            logger.warning("training_task_revocation_failed", exc_info=True)

    job.status = "failed"
    job.error_message = "Canceled by user"
    await db.flush()
    await db.refresh(job)
    return {"status": "canceled", **_serialize_training_job(job)}


# ---------------------------------------------------------------------------
# Batch Simulation
# ---------------------------------------------------------------------------


class BatchSimulateRequest(BaseModel):
    """Request body for POST /api/analytics/batch-simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    probability_mode: str = Field("ml", description="Probability source: ml, rule_based, ensemble")
    iterations: int = Field(5000, ge=100, le=50000, description="Monte Carlo iterations per game")
    rolling_window: int = Field(30, ge=5, le=162, description="Rolling window for profile building")
    date_start: str | None = Field(None, description="Start date (YYYY-MM-DD)")
    date_end: str | None = Field(None, description="End date (YYYY-MM-DD)")
    model_id: str | None = Field(None, description="Specific model ID to test (uses active model if omitted)")


@router.post("/batch-simulate", dependencies=[Depends(require_admin)])
async def post_batch_simulate(
    req: BatchSimulateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Kick off a batch simulation of upcoming games."""
    from app.db.analytics import AnalyticsBatchSimJob
    from app.tasks.batch_sim_tasks import batch_simulate_games

    job = AnalyticsBatchSimJob(
        sport=req.sport,
        probability_mode=req.probability_mode,
        iterations=req.iterations,
        rolling_window=req.rolling_window,
        date_start=req.date_start,
        date_end=req.date_end,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    task = batch_simulate_games.delay(job.id, model_id=req.model_id)
    job.celery_task_id = task.id
    job.status = "queued"
    await db.commit()
    await db.refresh(job)

    return {"job": _serialize_batch_sim_job(job)}


@router.get("/batch-simulate-jobs")
async def list_batch_simulate_jobs(
    sport: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List batch simulation jobs.

    Surfaces transient DB errors as 503 with Retry-After so callers know to
    retry, and isolates per-row serialization failures so one bad job row
    doesn't 500 the whole list.
    """
    from app.db.analytics import AnalyticsBatchSimJob

    stmt = select(AnalyticsBatchSimJob).order_by(AnalyticsBatchSimJob.id.desc())
    if sport:
        stmt = stmt.where(AnalyticsBatchSimJob.sport == sport)
    try:
        result = await db.execute(stmt)
        jobs = list(result.scalars().all())
    except Exception as exc:
        logger.exception("batch_sim_jobs_list_db_error", extra={"sport": sport})
        raise HTTPException(
            status_code=503,
            detail="Batch sim job listing temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from exc

    serialized: list[dict[str, Any]] = []
    for job in jobs:
        try:
            serialized.append(_serialize_batch_sim_job(job))
        except Exception:
            # Don't 500 the whole list because of one corrupted row. Surface
            # the row id and a marker so the caller can decide what to do.
            job_id = getattr(job, "id", None)
            logger.exception(
                "batch_sim_job_serialization_failed",
                extra={"job_id": job_id},
            )
            serialized.append({"id": job_id, "error": "serialization_failed"})

    return {"jobs": serialized, "count": len(serialized)}


@router.get("/batch-simulate-job/{job_id}")
async def get_batch_simulate_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific batch simulation job."""
    from app.db.analytics import AnalyticsBatchSimJob

    try:
        job = await db.get(AnalyticsBatchSimJob, job_id)
    except Exception as exc:
        logger.exception("batch_sim_job_get_db_error", extra={"job_id": job_id})
        raise HTTPException(
            status_code=503,
            detail="Batch sim job lookup temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Batch sim job not found")
    try:
        return _serialize_batch_sim_job(job, include_diagnostics=True)
    except Exception as exc:
        logger.exception(
            "batch_sim_job_serialization_failed", extra={"job_id": job_id}
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to serialize batch sim job",
        ) from exc


@router.delete("/batch-simulate-job/{job_id}", dependencies=[Depends(require_admin)])
async def delete_batch_simulate_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a batch simulation job."""
    from app.db.analytics import AnalyticsBatchSimJob

    job = await db.get(AnalyticsBatchSimJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Batch sim job not found")

    # Revoke Celery task if still running
    if job.celery_task_id and job.status in ("pending", "queued", "running"):
        try:
            from app.celery_app import celery_app
            celery_app.control.revoke(job.celery_task_id, terminate=True)
        except Exception:
            logger.warning("batch_sim_task_revocation_failed", exc_info=True)

    await db.delete(job)
    await db.flush()
    return {"status": "deleted", "id": job_id}


def _serialize_batch_sim_job(
    job: Any,
    *,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Serialize a batch sim job to a dict.

    Args:
        job: ``AnalyticsBatchSimJob`` ORM instance.
        include_diagnostics: When True, compute ``batch_summary`` and
            ``warnings`` from stored results. Skipped for list endpoints
            to avoid O(num_jobs x num_games) cost.
    """
    data: dict[str, Any] = {
        "id": job.id,
        "sport": job.sport,
        "probability_mode": job.probability_mode,
        "iterations": job.iterations,
        "rolling_window": job.rolling_window,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "game_count": job.game_count,
        "results": job.results,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }

    if include_diagnostics and job.results and job.status == "completed":
        from app.tasks.batch_sim_tasks import _build_batch_summary
        batch_summary, warnings = _build_batch_summary(job.results)
        if batch_summary:
            data["batch_summary"] = batch_summary
        if warnings:
            data["warnings"] = warnings

    return data
