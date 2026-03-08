"""Training, backtest, and batch simulation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

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


@router.post("/train")
async def start_training(
    req: TrainModelRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a model training job.

    Creates a training job record and dispatches a Celery task.
    """
    from app.db.analytics import AnalyticsTrainingJob

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

    try:
        from app.tasks.training_tasks import train_analytics_model
        task = train_analytics_model.delay(job.id)
        job.celery_task_id = task.id
        job.status = "queued"
        await db.flush()
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"Failed to dispatch task: {exc}"
        await db.flush()

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


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    """Request body for POST /api/analytics/backtest."""
    model_id: str = Field(..., description="Model ID to backtest")
    artifact_path: str = Field(..., description="Path to model .pkl artifact")
    sport: str = Field("mlb", description="Sport code")
    model_type: str = Field("game", description="Model type")
    date_start: str | None = Field(None, description="Backtest start date (YYYY-MM-DD)")
    date_end: str | None = Field(None, description="Backtest end date (YYYY-MM-DD)")
    rolling_window: int = Field(30, ge=5, le=162, description="Rolling window for profile aggregation")


def _serialize_backtest_job(job) -> dict[str, Any]:
    """Serialize a backtest job row to API response."""
    return {
        "id": job.id,
        "model_id": job.model_id,
        "artifact_path": job.artifact_path,
        "sport": job.sport,
        "model_type": job.model_type,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "rolling_window": getattr(job, "rolling_window", 30),
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "game_count": job.game_count,
        "correct_count": job.correct_count,
        "metrics": job.metrics,
        "predictions": job.predictions,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/backtest")
async def start_backtest(
    req: BacktestRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a model backtest job."""
    from app.db.analytics import AnalyticsBacktestJob

    job = AnalyticsBacktestJob(
        model_id=req.model_id,
        artifact_path=req.artifact_path,
        sport=req.sport.lower(),
        model_type=req.model_type,
        date_start=req.date_start,
        date_end=req.date_end,
        rolling_window=req.rolling_window,
        status="pending",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    try:
        from app.tasks.training_tasks import backtest_analytics_model
        task = backtest_analytics_model.delay(job.id)
        job.celery_task_id = task.id
        job.status = "queued"
        await db.flush()
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"Failed to dispatch task: {exc}"
        await db.flush()

    return {"status": "submitted", "job": _serialize_backtest_job(job)}


@router.get("/backtest-jobs")
async def list_backtest_jobs(
    model_id: str = Query(None, description="Filter by model ID"),
    sport: str = Query(None, description="Filter by sport"),
    status: str = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List backtest jobs with optional filtering."""
    from app.db.analytics import AnalyticsBacktestJob

    stmt = select(AnalyticsBacktestJob).order_by(
        AnalyticsBacktestJob.created_at.desc()
    ).limit(limit)

    if model_id:
        stmt = stmt.where(AnalyticsBacktestJob.model_id == model_id)
    if sport:
        stmt = stmt.where(AnalyticsBacktestJob.sport == sport)
    if status:
        stmt = stmt.where(AnalyticsBacktestJob.status == status)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {
        "jobs": [_serialize_backtest_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/backtest-job/{job_id}")
async def get_backtest_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific backtest job."""
    from app.db.analytics import AnalyticsBacktestJob

    job = await db.get(AnalyticsBacktestJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Backtest job not found")
    return _serialize_backtest_job(job)


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


@router.post("/batch-simulate")
async def post_batch_simulate(
    req: BatchSimulateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Kick off a batch simulation of upcoming games."""
    from app.db.analytics import AnalyticsBatchSimJob
    from app.tasks.training_tasks import batch_simulate_games

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

    task = batch_simulate_games.delay(job.id)
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
    """List batch simulation jobs."""
    from app.db.analytics import AnalyticsBatchSimJob

    stmt = select(AnalyticsBatchSimJob).order_by(AnalyticsBatchSimJob.id.desc())
    if sport:
        stmt = stmt.where(AnalyticsBatchSimJob.sport == sport)
    result = await db.execute(stmt)
    jobs = list(result.scalars().all())

    return {
        "jobs": [_serialize_batch_sim_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/batch-simulate-job/{job_id}")
async def get_batch_simulate_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific batch simulation job."""
    from app.db.analytics import AnalyticsBatchSimJob

    job = await db.get(AnalyticsBatchSimJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Batch sim job not found")
    return _serialize_batch_sim_job(job)


def _serialize_batch_sim_job(job: Any) -> dict[str, Any]:
    return {
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
