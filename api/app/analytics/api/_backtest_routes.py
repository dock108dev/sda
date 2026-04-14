"""Backtest endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies.roles import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()


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


@router.post("/backtest", dependencies=[Depends(require_admin)])
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
    except Exception:
        logger.exception("Failed to dispatch backtest task job_id=%s", job.id)
        job.status = "failed"
        job.error_message = "Failed to dispatch task"
        await db.flush()

    await db.refresh(job)

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
