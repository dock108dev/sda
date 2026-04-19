"""Admin endpoint: pipeline coverage report.

GET /api/admin/pipeline/coverage-report
  Returns the most-recently generated PipelineCoverageReport row, which
  summarises FINAL-game coverage (flows vs missing, fallback rate, quality)
  broken down by sport for yesterday.

Requires admin API key (enforced at router registration level in main.py).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.pipeline import PipelineCoverageReport

logger = logging.getLogger(__name__)

router = APIRouter()

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


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
    """Return the most recent pipeline coverage report."""
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
