"""Scraper run management endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import Select, desc, select
from sqlalchemy.orm import selectinload

from ...celery_client import get_celery_app
from ...config_sports import LEAGUE_CONFIG
from ...db import AsyncSession, get_db
from ...db.scraper import SportsJobRun, SportsScrapeRun
from ...db.sports import SportsLeague
from ...utils.datetime_utils import date_to_utc_datetime, now_utc
from .common import get_league, serialize_run
from .schemas import ScrapeRunCreateRequest, ScrapeRunResponse

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

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
            headers={"manual_trigger": True},
        )
        run.job_id = async_result.id

        # Create a SportsJobRun so the task appears in the Runs Drawer
        # with status="queued" — visible immediately, cancelable.
        # Flushed so the worker can find it by celery_task_id on startup.
        job_run = SportsJobRun(
            phase="data_backfill",
            leagues=[league.code.upper()],
            status="queued",
            started_at=now_utc(),  # placeholder — overwritten when worker starts
            celery_task_id=async_result.id,
        )
        session.add(job_run)
        await session.flush()
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


# ---------------------------------------------------------------------------
# Bulk backfill — season-aware chunking
# ---------------------------------------------------------------------------


def _league_season_range(league_code: str, year: int) -> tuple[date, date] | None:
    """Return (start, end) for a league's season in a given year.

    For cross-year leagues (NBA, NHL, NFL, NCAAB), *year* is the season
    start year — e.g. year=2024 → Oct 2024 – Apr 2025.

    Returns None if the league has no season config.  Adds a 6-week
    playoff buffer past the regular-season end date.
    """
    cfg = LEAGUE_CONFIG.get(league_code)
    if not cfg or not cfg.season_start_month or not cfg.season_end_month:
        return None

    start = date(year, cfg.season_start_month, cfg.season_start_day or 1)
    end_year = year + 1 if cfg.season_crosses_year else year
    end = date(end_year, cfg.season_end_month, cfg.season_end_day or 28)

    # Add 6-week playoff buffer
    end += timedelta(weeks=6)

    return start, end


def _month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split a date range into monthly chunks."""
    chunks = []
    cursor = start
    while cursor < end:
        # End of this month
        if cursor.month == 12:
            month_end = date(cursor.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(cursor.year, cursor.month + 1, 1) - timedelta(days=1)
        chunk_end = min(month_end, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def compute_backfill_chunks(
    leagues: list[str],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Compute season-aware monthly chunks for a multi-year backfill.

    For each league, only generates chunks that overlap the league's season
    (with a playoff buffer).  Skips off-season months entirely.
    """
    chunks = []
    today = date.today()

    for league_code in leagues:
        # Build list of season windows that overlap [start_date, end_date]
        season_windows = []
        for year in range(start_date.year - 1, end_date.year + 1):
            window = _league_season_range(league_code, year)
            if window:
                s, e = window
                # Clip to requested range and don't go past today
                s = max(s, start_date)
                e = min(e, end_date, today)
                if s < e:
                    season_windows.append((s, e))

        if not season_windows:
            # No season config — fall back to monthly chunks of the full range
            capped_end = min(end_date, today)
            if start_date < capped_end:
                season_windows = [(start_date, capped_end)]

        # Break each season window into monthly chunks
        for window_start, window_end in season_windows:
            for chunk_start, chunk_end in _month_chunks(window_start, window_end):
                chunks.append({
                    "league_code": league_code,
                    "start_date": chunk_start.isoformat(),
                    "end_date": chunk_end.isoformat(),
                })

    return chunks


class BulkBackfillRequest(BaseModel):
    leagues: list[str]
    start_date: date = Field(..., alias="startDate")
    end_date: date = Field(..., alias="endDate")
    boxscores: bool = True
    odds: bool = False
    pbp: bool = False
    social: bool = False
    advanced_stats: bool = Field(False, alias="advancedStats")
    only_missing: bool = Field(True, alias="onlyMissing")

    model_config = {"populate_by_name": True}


class BulkBackfillChunk(BaseModel):
    model_config = _ALIAS_CFG

    league_code: str
    start_date: str
    end_date: str
    run_id: int | None = None
    job_id: str | None = None
    error: str | None = None


class BulkBackfillResponse(BaseModel):
    model_config = _ALIAS_CFG

    total_chunks: int
    chunks_dispatched: int
    chunks: list[BulkBackfillChunk]


@router.post("/scraper/runs/bulk-preview")
async def preview_bulk_backfill(body: BulkBackfillRequest) -> dict:
    """Preview the chunks that would be created without dispatching."""
    chunks = compute_backfill_chunks(
        body.leagues, body.start_date, body.end_date,
    )
    return {"total_chunks": len(chunks), "chunks": chunks}


@router.post("/scraper/runs/bulk", response_model=BulkBackfillResponse)
async def create_bulk_backfill(
    body: BulkBackfillRequest,
    session: AsyncSession = Depends(get_db),
) -> BulkBackfillResponse:
    """Create a season-aware bulk backfill as a single sequential task.

    Splits a wide date range into monthly chunks per league, skipping
    off-season months.  Dispatches ONE Celery task that processes chunks
    sequentially — no queue flooding.  Each chunk creates its own
    SportsScrapeRun for per-chunk visibility in the Runs Drawer.
    """
    raw_chunks = compute_backfill_chunks(
        body.leagues, body.start_date, body.end_date,
    )

    if not raw_chunks:
        return BulkBackfillResponse(
            total_chunks=0, chunks_dispatched=0, chunks=[],
        )

    data_toggles = {
        "boxscores": body.boxscores,
        "odds": body.odds,
        "pbp": body.pbp,
        "social": body.social,
        "advanced_stats": body.advanced_stats,
        "only_missing": body.only_missing,
    }

    # Create the job run BEFORE dispatching so the worker can find it
    all_leagues = sorted(set(c["league_code"] for c in raw_chunks))
    job_run = SportsJobRun(
        phase="data_backfill",
        leagues=all_leagues,
        status="queued",
        started_at=now_utc(),
    )
    session.add(job_run)
    await session.flush()

    celery_app = get_celery_app()
    try:
        async_result = celery_app.send_task(
            "run_bulk_backfill",
            args=[raw_chunks, data_toggles],
            queue="sports-scraper",
            routing_key="sports-scraper",
            headers={"manual_trigger": True},
        )
        job_run.celery_task_id = async_result.id

        result_chunks = [
            BulkBackfillChunk(
                league_code=c["league_code"],
                start_date=c["start_date"],
                end_date=c["end_date"],
            )
            for c in raw_chunks
        ]

        return BulkBackfillResponse(
            total_chunks=len(raw_chunks),
            chunks_dispatched=1,  # single orchestrator task
            chunks=result_chunks,
        )

    except Exception as exc:
        from ...logging_config import get_logger
        logger = get_logger(__name__)
        logger.error("bulk_backfill_dispatch_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=500, detail=f"Failed to dispatch bulk backfill: {exc}"
        ) from exc
