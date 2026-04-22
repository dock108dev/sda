"""ClubMembership ORM model — club-scoped RBAC."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ClubMembership(Base):
    """A user's role within a club tenant.

    Created when an invite is accepted via POST /api/v1/clubs/invites/{token}/accept.
    Roles: owner (provisioned automatically), admin, viewer.
    """

    __tablename__ = "club_memberships"
    __table_args__ = (
        UniqueConstraint("club_id", "user_id", name="uq_club_memberships_club_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
