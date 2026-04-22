"""AuditEvent ORM model — append-only structured audit log."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditEvent(Base):
    """Append-only record for provisioning, payment, and lifecycle events.

    Never updated or deleted — all mutations produce new rows.
    actor_type: user | webhook | system
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_club_id", "club_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    club_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clubs.id", ondelete="SET NULL"), nullable=True
    )
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
