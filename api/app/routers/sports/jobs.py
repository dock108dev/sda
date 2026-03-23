"""Job run monitoring endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select

from ...celery_client import get_celery_app
from ...db import AsyncSession, get_db
from ...db.scraper import SportsJobRun
from ...utils.datetime_utils import now_utc
from .schemas import JobRunResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/jobs", response_model=list[JobRunResponse])
async def list_job_runs(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    phase: str | None = Query(None),
    status: str | None = Query(None),
) -> list[JobRunResponse]:
    stmt = select(SportsJobRun)
    if phase:
        stmt = stmt.where(SportsJobRun.phase == phase)
    if status:
        stmt = stmt.where(SportsJobRun.status == status)
    stmt = stmt.order_by(desc(SportsJobRun.created_at)).limit(limit)
    results = await session.execute(stmt)
    runs = results.scalars().all()
    return [_serialize_run(run) for run in runs]


def _serialize_run(run: SportsJobRun) -> JobRunResponse:
    return JobRunResponse(
        id=run.id,
        phase=run.phase,
        leagues=list(run.leagues or []),
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=run.duration_seconds,
        error_summary=run.error_summary,
        summary_data=run.summary_data,
        celery_task_id=run.celery_task_id,
        created_at=run.created_at,
    )


@router.post("/jobs/{run_id}/cancel", response_model=JobRunResponse)
async def cancel_job_run(
    run_id: int, session: AsyncSession = Depends(get_db)
) -> JobRunResponse:
    result = await session.execute(
        select(SportsJobRun).where(SportsJobRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
        )

    if run.status not in ("running", "queued"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only running or queued jobs can be canceled",
        )

    original_status = run.status

    if run.celery_task_id:
        celery_app = get_celery_app()
        try:
            celery_app.control.revoke(
                run.celery_task_id,
                terminate=True,
                signal="SIGKILL",
            )
        except Exception as exc:
            logger.warning(
                "failed_to_revoke_job_run",
                extra={
                    "run_id": run.id,
                    "celery_task_id": run.celery_task_id,
                    "error": str(exc),
                },
            )

    now = now_utc()
    run.status = "canceled"
    run.finished_at = now
    run.duration_seconds = (
        0.0 if original_status == "queued" else (now - run.started_at).total_seconds()
    )
    run.error_summary = "Canceled by user via admin UI"

    # Release ingestion locks for canceled backfill jobs so subsequent
    # runs aren't blocked by an orphaned lock from the killed task.
    if run.phase == "data_backfill" and run.leagues:
        try:
            import redis.asyncio as aioredis
            from ...config import settings

            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            for league in run.leagues:
                lock_key = f"lock:ingest:{league}"
                await r.delete(lock_key)
                logger.info("Released ingestion lock on cancel", extra={"lock_key": lock_key})
            await r.aclose()
        except Exception as exc:
            logger.warning("Failed to release ingestion lock", extra={"error": str(exc)})

    await session.commit()
    return _serialize_run(run)
