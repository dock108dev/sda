"""Historical replay analytics endpoints."""

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
# Historical Replay
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    """Request body for POST /api/analytics/replay."""
    sport: str = Field("mlb")
    model_id: str = Field(..., description="Model ID to evaluate")
    model_type: str = Field("plate_appearance")
    date_start: str | None = Field(None, description="Replay start date")
    date_end: str | None = Field(None, description="Replay end date")
    game_count: int | None = Field(None, ge=1, le=500, description="Max games to replay")
    rolling_window: int = Field(30, ge=5, le=162)
    probability_mode: str = Field("ml")
    iterations: int = Field(5000, ge=100, le=50000)
    suite_id: int | None = Field(None, description="Optional link to experiment suite")


def _serialize_replay_job(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "sport": job.sport,
        "model_id": job.model_id,
        "model_type": job.model_type,
        "date_start": job.date_start,
        "date_end": job.date_end,
        "game_count_requested": job.game_count_requested,
        "rolling_window": job.rolling_window,
        "probability_mode": job.probability_mode,
        "iterations": job.iterations,
        "suite_id": job.suite_id,
        "status": job.status,
        "celery_task_id": job.celery_task_id,
        "game_count": job.game_count,
        "results": job.results,
        "metrics": job.metrics,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/replay", dependencies=[Depends(require_admin)])
async def start_replay(
    req: ReplayRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a historical replay job."""
    from app.db.analytics import AnalyticsReplayJob

    job = AnalyticsReplayJob(
        sport=req.sport.lower(),
        model_id=req.model_id,
        model_type=req.model_type,
        date_start=req.date_start,
        date_end=req.date_end,
        game_count_requested=req.game_count,
        rolling_window=req.rolling_window,
        probability_mode=req.probability_mode,
        iterations=req.iterations,
        suite_id=req.suite_id,
        status="pending",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    try:
        from app.tasks.replay_tasks import replay_historical_games
        task = replay_historical_games.delay(job.id)
        job.celery_task_id = task.id
        job.status = "queued"
        await db.flush()
    except Exception:
        # Replay follows the training-job contract: persist the failed job
        # record and return it to the caller so admin clients can render the
        # job status from the normal response shape.
        logger.exception("Failed to dispatch replay job job_id=%s", job.id)
        job.status = "failed"
        job.error_message = "Failed to dispatch task"
        await db.flush()
        await db.refresh(job)
        return {"status": "submitted", "job": _serialize_replay_job(job)}

    await db.refresh(job)
    return {"status": "submitted", "job": _serialize_replay_job(job)}


@router.get("/replay-jobs")
async def list_replay_jobs(
    sport: str | None = None,
    suite_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List replay jobs."""
    from app.db.analytics import AnalyticsReplayJob

    stmt = select(AnalyticsReplayJob).order_by(
        AnalyticsReplayJob.created_at.desc()
    ).limit(limit)
    if sport:
        stmt = stmt.where(AnalyticsReplayJob.sport == sport)
    if suite_id is not None:
        stmt = stmt.where(AnalyticsReplayJob.suite_id == suite_id)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {
        "jobs": [_serialize_replay_job(j) for j in jobs],
        "count": len(jobs),
    }


@router.get("/replay-job/{job_id}")
async def get_replay_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get details for a specific replay job."""
    from app.db.analytics import AnalyticsReplayJob

    job = await db.get(AnalyticsReplayJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Replay job not found")
    return _serialize_replay_job(job)
