"""Scraper run management endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, desc, select
from sqlalchemy.orm import selectinload

from ...celery_client import get_celery_app
from ...db import AsyncSession, get_db
from ...db.scraper import SportsJobRun, SportsScrapeRun
from ...db.sports import SportsLeague
from ...utils.datetime_utils import date_to_utc_datetime, now_utc
from .common import get_league, serialize_run
from .schemas import ScrapeRunCreateRequest, ScrapeRunResponse

router = APIRouter()


def _coerce_date_to_datetime(value: date | None) -> datetime | None:
    if not value:
        return None
    return date_to_utc_datetime(value)


def _serialize_config_payload(payload: ScrapeRunCreateRequest) -> dict[str, Any]:
    config_dict = payload.config.model_dump(by_alias=False)
    start_date = config_dict.get("start_date")
    if isinstance(start_date, date):
        config_dict["start_date"] = start_date.isoformat()
    end_date = config_dict.get("end_date")
    if isinstance(end_date, date):
        config_dict["end_date"] = end_date.isoformat()
    return config_dict


@router.post("/scraper/runs", response_model=ScrapeRunResponse)
async def create_scrape_run(
    payload: ScrapeRunCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> ScrapeRunResponse:
    league = await get_league(session, payload.config.league_code)

    # Boxscore end_date is auto-capped to yesterday by the Pydantic model
    # (ScrapeRunConfig.cap_end_date_for_boxscores) — no hard error needed.

    run = SportsScrapeRun(
        scraper_type="scrape",
        league_id=league.id,
        season=payload.config.season,
        season_type=payload.config.season_type,
        start_date=_coerce_date_to_datetime(payload.config.start_date),
        end_date=_coerce_date_to_datetime(payload.config.end_date),
        status="pending",
        requested_by=payload.requested_by,
        config=_serialize_config_payload(payload),
    )
    session.add(run)
    await session.flush()

    worker_payload = payload.config.to_worker_payload()
    try:
        celery_app = get_celery_app()
        async_result = celery_app.send_task(
            "run_scrape_job",
            args=[run.id, worker_payload],
            queue="sports-scraper",
            routing_key="sports-scraper",
        )
        run.job_id = async_result.id

        # Create a SportsJobRun so the task appears in the Runs Drawer
        # with status="queued" — visible immediately, cancelable.
        job_run = SportsJobRun(
            phase="data_backfill",
            leagues=[league.code.upper()],
            status="queued",
            started_at=now_utc(),  # placeholder — overwritten when worker starts
            celery_task_id=async_result.id,
        )
        session.add(job_run)
    except Exception as exc:  # pragma: no cover
        from ...logging_config import get_logger

        logger = get_logger(__name__)
        logger.error(
            "failed_to_enqueue_scrape",
            extra={"error": str(exc)},
            exc_info=True,
        )
        run.status = "error"
        run.error_details = f"Failed to enqueue scrape: {exc}"
        raise HTTPException(
            status_code=500, detail="Failed to enqueue scrape job"
        ) from exc

    return serialize_run(run, league.code)


@router.get("/scraper/runs", response_model=list[ScrapeRunResponse])
async def list_scrape_runs(
    league: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_db),
) -> list[ScrapeRunResponse]:
    stmt: Select[tuple[SportsScrapeRun]] = (
        select(SportsScrapeRun)
        .order_by(desc(SportsScrapeRun.created_at))
        .limit(limit)
    )
    if league:
        league_obj = await get_league(session, league)
        stmt = stmt.where(SportsScrapeRun.league_id == league_obj.id)
    if status_filter:
        stmt = stmt.where(SportsScrapeRun.status == status_filter)

    results = await session.execute(stmt)
    runs = results.scalars().all()

    league_map: dict[int, str] = {}
    if runs:
        stmt_leagues = select(
            SportsLeague.id, SportsLeague.code
        ).where(SportsLeague.id.in_({run.league_id for run in runs}))
        league_rows = await session.execute(stmt_leagues)
        league_map = {row.id: row.code for row in league_rows}

    return [
        serialize_run(run, league_map.get(run.league_id, "UNKNOWN")) for run in runs
    ]


@router.get("/scraper/runs/{run_id}", response_model=ScrapeRunResponse)
async def fetch_run(
    run_id: int, session: AsyncSession = Depends(get_db)
) -> ScrapeRunResponse:
    result = await session.execute(
        select(SportsScrapeRun)
        .options(selectinload(SportsScrapeRun.league))
        .where(SportsScrapeRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
        )
    league_code = run.league.code if run.league else "UNKNOWN"
    return serialize_run(run, league_code)


@router.post("/scraper/cache/clear")
async def clear_scraper_cache(
    league: str = Query(..., description="League code (e.g., NBA, NHL)"),
    days: int = Query(7, ge=1, le=30, description="Days of cache to clear"),
) -> dict:
    """Clear cached scoreboard HTML files for the last N days.

    This is useful before running a manual scrape to ensure fresh data is fetched.
    Only clears scoreboard pages (not boxscores or PBP which are immutable).
    """
    from ...logging_config import get_logger

    logger = get_logger(__name__)

    try:
        celery_app = get_celery_app()
        async_result = celery_app.send_task(
            "clear_scraper_cache",
            args=[league.upper(), days],
            queue="sports-scraper",
            routing_key="sports-scraper",
        )

        # Wait for the result (short timeout since this is fast)
        result = async_result.get(timeout=30)

        return {
            "status": "success",
            "league": league.upper(),
            "days": days,
            "deleted_count": result.get("deleted_count", 0),
            "deleted_files": result.get("deleted_files", []),
        }
    except Exception as exc:
        logger.error(
            "clear_cache_failed",
            extra={"league": league, "days": days, "error": str(exc)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear cache: {exc}",
        ) from exc


@router.post("/scraper/runs/{run_id}/cancel", response_model=ScrapeRunResponse)
async def cancel_scrape_run(
    run_id: int, session: AsyncSession = Depends(get_db)
) -> ScrapeRunResponse:
    result = await session.execute(
        select(SportsScrapeRun)
        .options(selectinload(SportsScrapeRun.league))
        .where(SportsScrapeRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
        )

    if run.status not in {"pending", "running"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending or running jobs can be canceled",
        )

    if run.job_id:
        celery_app = get_celery_app()
        try:
            celery_app.control.revoke(run.job_id, terminate=True)
        except Exception as exc:  # pragma: no cover - best-effort logging
            from ...logging_config import get_logger

            logger = get_logger(__name__)
            logger.warning(
                "failed_to_revoke_scrape_job",
                extra={
                    "run_id": run.id,
                    "job_id": run.job_id,
                    "error": str(exc),
                },
            )

    cancel_message = "Canceled by user via admin UI"
    now = now_utc()
    run.status = "canceled"
    run.finished_at = now
    run.summary = f"{run.summary} | {cancel_message}" if run.summary else cancel_message
    run.error_details = cancel_message
    await session.commit()
    league_code = run.league.code if run.league else "UNKNOWN"
    return serialize_run(run, league_code)
