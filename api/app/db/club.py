"""Club ORM model — top-level multi-tenant entity."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Club(Base):
    """A provisioned club tenant.

    Created by ClubProvisioningService when an OnboardingSession reaches
    'claimed' status. ``club_id`` is the public UUID handle; ``slug`` is the
    URL-safe identifier used for routing and idempotency checks.
    """

    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branding_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
