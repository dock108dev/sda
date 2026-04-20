"""Admin endpoint: pipeline coverage report.

GET /api/admin/coverage-report
  Returns paginated per-game pipeline coverage entries sorted by report_date desc.

GET /api/admin/pipeline/coverage-report
  Returns the most-recently generated aggregate PipelineCoverageReport row (legacy).

Requires admin API key (enforced at router registration level in main.py).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ── Per-game entry response ────────────────────────────────────────────────


class CoverageReportEntryResponse(BaseModel):
    model_config = _ALIAS_CFG

    id: int
    report_date: date
    sport: str
    game_id: int
    has_flow: bool
    gap_reason: Optional[str] = None
    created_at: datetime


class PaginatedCoverageReportResponse(BaseModel):
    model_config = _ALIAS_CFG

    items: list[CoverageReportEntryResponse]
    total: int
    page: int
    per_page: int


@router.get("/coverage-report", response_model=PaginatedCoverageReportResponse)
async def get_coverage_report_entries(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    sport: Optional[str] = Query(default=None),
    report_date: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedCoverageReportResponse:
    """Return paginated per-game pipeline coverage entries sorted by report_date desc."""
    from sqlalchemy import func as sqlfunc

    from app.db.pipeline import PipelineCoverageReportEntry

    base_stmt = select(PipelineCoverageReportEntry)

    if sport is not None:
        base_stmt = base_stmt.where(PipelineCoverageReportEntry.sport == sport)
    if report_date is not None:
        base_stmt = base_stmt.where(PipelineCoverageReportEntry.report_date == report_date)

    total_result = await db.execute(
        select(sqlfunc.count()).select_from(base_stmt.subquery())
    )
    total = total_result.scalar_one()

    offset = (page - 1) * per_page
    rows_result = await db.execute(
        base_stmt.order_by(
            desc(PipelineCoverageReportEntry.report_date),
            PipelineCoverageReportEntry.game_id,
        )
        .offset(offset)
        .limit(per_page)
    )
    rows = rows_result.scalars().all()

    return PaginatedCoverageReportResponse(
        items=[
            CoverageReportEntryResponse(
                id=row.id,
                report_date=row.report_date,
                sport=row.sport,
                game_id=row.game_id,
                has_flow=row.has_flow,
                gap_reason=row.gap_reason,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


# ── Aggregate daily summary (legacy) ──────────────────────────────────────


class SportBreakdownEntry(BaseModel):
    model_config = _ALIAS_CFG

    sport: str
    finals_count: int
    flows_count: int
    missing_count: int
    fallback_count: int
    avg_quality_score: Optional[float] = None


class CoverageReportResponse(BaseModel):
    model_config = _ALIAS_CFG

    id: int
    report_date: date
    generated_at: datetime
    sport_breakdown: list[SportBreakdownEntry]
    total_finals: int
    total_flows: int
    total_missing: int
    total_fallbacks: int
    avg_quality_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime


@router.get("/pipeline/coverage-report", response_model=CoverageReportResponse)
async def get_coverage_report(
    db: AsyncSession = Depends(get_db),
) -> CoverageReportResponse:
    """Return the most recent aggregate pipeline coverage report."""
    from app.db.pipeline import PipelineCoverageReport

    result = await db.execute(
        select(PipelineCoverageReport)
        .order_by(desc(PipelineCoverageReport.report_date))
        .limit(1)
    )
    row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No coverage report found.")

    breakdown = [
        SportBreakdownEntry(**entry) for entry in (row.sport_breakdown or [])
    ]

    return CoverageReportResponse(
        id=row.id,
        report_date=row.report_date,
        generated_at=row.generated_at,
        sport_breakdown=breakdown,
        total_finals=row.total_finals,
        total_flows=row.total_flows,
        total_missing=row.total_missing,
        total_fallbacks=row.total_fallbacks,
        avg_quality_score=row.avg_quality_score,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
