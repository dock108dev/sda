"""Bulk generation endpoints for pipeline management."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ....db import AsyncSession, get_db
from ....db.pipeline import BulkFlowGenerationJob
from .models import (
    BulkGenerateAsyncResponse,
    BulkGenerateRequest,
    BulkGenerateStatusResponse,
)

router = APIRouter()

_MAX_DATE_RANGE_DAYS = 180
_MAX_GAMES_PER_BULK = 500


@router.post(
    "/pipeline/bulk-generate-async",
    response_model=BulkGenerateAsyncResponse,
    summary="Start bulk game flow generation",
    description="Start an async job to generate game flows for multiple games.",
)
async def bulk_generate_async(
    request: BulkGenerateRequest,
    session: AsyncSession = Depends(get_db),
) -> BulkGenerateAsyncResponse:
    """Start bulk game flow generation as a Celery background job.

    Job state is persisted in the database for consistency across workers.
    The job runs in the api-worker container and survives restarts.
    """
    from ....celery_app import celery_app

    # Parse and validate date range
    try:
        start_dt = datetime.strptime(request.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(request.end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {e}",
        )

    if end_dt < start_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date must be on or after start_date",
        )
    if (end_dt - start_dt) > timedelta(days=_MAX_DATE_RANGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range cannot exceed {_MAX_DATE_RANGE_DAYS} days",
        )

    max_games = request.max_games if request.max_games is not None else _MAX_GAMES_PER_BULK
    if max_games > _MAX_GAMES_PER_BULK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"max_games cannot exceed {_MAX_GAMES_PER_BULK}",
        )

    # Create job record in database
    job = BulkFlowGenerationJob(
        status="pending",
        start_date=start_dt,
        end_date=end_dt,
        leagues=request.leagues,
        force_regenerate=request.force,
        max_games=max_games,
        triggered_by="admin",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    job_uuid = str(job.job_uuid)

    # Send task to Celery worker
    celery_app.send_task("run_bulk_flow_generation", args=[job.id])

    return BulkGenerateAsyncResponse(
        job_id=job_uuid,
        message="Bulk game flow generation job started",
        status_url=f"/api/admin/sports/pipeline/bulk-generate-status/{job_uuid}",
    )


@router.get(
    "/pipeline/bulk-generate-status/{job_id}",
    response_model=BulkGenerateStatusResponse,
    summary="Get bulk generation status",
    description="Get the status of a bulk generation job.",
)
async def get_bulk_generate_status(
    job_id: str,
    session: AsyncSession = Depends(get_db),
) -> BulkGenerateStatusResponse:
    """Get the status of a bulk generation job from the database."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid job ID format: {job_id}",
        )

    result = await session.execute(
        select(BulkFlowGenerationJob).where(
            BulkFlowGenerationJob.job_uuid == job_uuid
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Map DB status to state for API response
    state_map = {
        "pending": "PENDING",
        "running": "PROGRESS",
        "completed": "SUCCESS",
        "failed": "FAILURE",
    }

    # Build result dict if job is complete
    result_dict = None
    if job.status in ("completed", "failed"):
        result_dict = {
            "total": job.total_games,
            "successful": job.successful,
            "failed": job.failed,
            "skipped": job.skipped,
            "errors": job.errors_json or [],
        }

    return BulkGenerateStatusResponse(
        job_id=str(job.job_uuid),
        state=state_map.get(job.status, "PENDING"),
        current=job.current_game,
        total=job.total_games,
        successful=job.successful,
        failed=job.failed,
        skipped=job.skipped,
        result=result_dict,
    )
