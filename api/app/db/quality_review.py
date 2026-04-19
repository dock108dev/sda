"""Quality review queue and audit log models for human review escalation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from .base import Base


class QualityReviewQueue(Base):
    """Flows escalated for human review because their combined quality score
    fell below the grader escalation threshold.

    Status lifecycle: pending → reviewed | dismissed.
    """

    __tablename__ = "quality_review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_game_stories.id", ondelete="CASCADE"),
        nullable=False,
    )
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="CASCADE"),
        nullable=False,
    )
    sport: Mapped[str] = mapped_column(String(20), nullable=False)
    combined_score: Mapped[float] = mapped_column(Float, nullable=False)
    tier1_score: Mapped[float] = mapped_column(Float, nullable=False)
    tier2_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier_breakdown: Mapped[dict] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_quality_review_queue_flow_id", "flow_id"),
        Index("idx_quality_review_queue_status", "status"),
        Index("idx_quality_review_queue_sport", "sport"),
    )


class QualityReviewAction(Base):
    """Audit log for admin actions taken on quality review queue items.

    Persists every approve/reject/regenerate action with actor and timestamp.
    queue_id is nullable: queue rows may be deleted (reject/regenerate path) but
    the audit record is kept for history.
    """

    __tablename__ = "quality_review_action"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    queue_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_quality_review_action_flow_id", "flow_id"),)
