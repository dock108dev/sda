"""Pipeline execution models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .base import Base
from .sports import SportsGame


class PipelineRunStatus(str, Enum):
    """Status of a pipeline run."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    paused = "paused"


class PipelineStageStatus(str, Enum):
    """Status of a pipeline stage execution."""

    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


class PipelineTrigger(str, Enum):
    """Who/what triggered the pipeline run."""

    prod_auto = "prod_auto"
    admin = "admin"
    manual = "manual"
    backfill = "backfill"


class GamePipelineRun(Base):
    """Tracks a pipeline execution for a single game."""

    __tablename__ = "sports_game_pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_uuid: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()")
    )
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)
    auto_chain: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    current_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending", index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    game: Mapped[SportsGame] = relationship("SportsGame")
    stages: Mapped[list[GamePipelineStage]] = relationship(
        "GamePipelineStage", back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_pipeline_runs_uuid", "run_uuid", unique=True),)

    @property
    def is_complete(self) -> bool:
        """Check if the pipeline run has completed (success or failure)."""
        return self.status in (
            PipelineRunStatus.completed.value,
            PipelineRunStatus.failed.value,
        )

    @property
    def can_continue(self) -> bool:
        """Check if the pipeline can be continued."""
        return self.status in (
            PipelineRunStatus.pending.value,
            PipelineRunStatus.paused.value,
            PipelineRunStatus.running.value,
        )


class GamePipelineStage(Base):
    """Tracks execution of a single stage within a pipeline run."""

    __tablename__ = "sports_game_pipeline_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_game_pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending", index=True
    )
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    logs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, server_default=text("'[]'::jsonb")
    )
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[GamePipelineRun] = relationship(
        "GamePipelineRun", back_populates="stages"
    )

    __table_args__ = (
        UniqueConstraint("run_id", "stage", name="uq_pipeline_stages_run_stage"),
    )

    @property
    def is_complete(self) -> bool:
        """Check if the stage has completed (success or failure)."""
        return self.status in (
            PipelineStageStatus.success.value,
            PipelineStageStatus.failed.value,
            PipelineStageStatus.skipped.value,
        )

    def add_log(self, message: str, level: str = "info") -> None:
        """Add a log entry to this stage."""
        if self.logs_json is None:
            self.logs_json = []
        self.logs_json.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": level,
                "message": message,
            }
        )


class BulkFlowJobStatus(str, Enum):
    """Status of a bulk flow generation job."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class BulkFlowGenerationJob(Base):
    """Tracks bulk flow generation jobs."""

    __tablename__ = "bulk_story_generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_uuid: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending", index=True
    )
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    leagues: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    force_regenerate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_games: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    total_games: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_game: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    triggered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("idx_bulk_story_jobs_uuid", "job_uuid", unique=True),)


class PipelineCoverageReport(Base):
    """Daily pipeline coverage summary: FINAL games vs flows generated, by sport."""

    __tablename__ = "pipeline_coverage_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Unique per calendar day; re-running the task for the same date overwrites this row.
    report_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Per-sport rows: [{sport, finals_count, flows_count, missing_count, fallback_count, avg_quality_score}]
    sport_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Aggregate totals (denormalised for fast reads)
    total_finals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_flows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_fallbacks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PipelineCoverageReportEntry(Base):
    """Per-game pipeline coverage entry written by the daily coverage report task."""

    __tablename__ = "pipeline_coverage_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sport: Mapped[str] = mapped_column(Text, nullable=False)
    game_id: Mapped[int] = mapped_column(Integer, nullable=False)
    has_flow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Human-readable reason when has_flow is False (e.g. "no_pipeline_run", "pipeline_failed")
    gap_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("report_date", "game_id", name="uq_coverage_report_date_game"),
    )


# Re-export so callers can do `from app.db.pipeline import PipelineStage`.
# Placed at the bottom to avoid circular import: pipeline.py -> services.pipeline ->
# executor -> pipeline.py (classes not yet defined if imported at top of file).
from ..services.pipeline.models import PipelineStage  # noqa: F401 — single source of truth
