"""Stripe commerce models — customers, subscriptions, and webhook idempotency."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StripeCustomer(Base):
    """Maps a club to its Stripe customer record.

    ``club_id`` is an application-level reference; the FK constraint to a
    ``clubs`` table will be added in the Phase 3 club-provisioning migration
    once that table exists.
    """

    __tablename__ = "stripe_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    stripe_customer_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StripeSubscription(Base):
    """Mirrors the Stripe subscription object for server-side payment truth."""

    __tablename__ = "stripe_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    stripe_customer_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )


class ProcessedStripeEvent(Base):
    """Idempotency anchor for Stripe webhook events.

    ``event_id`` is the Stripe ``evt_*`` identifier and serves as the primary
    key so ``INSERT … ON CONFLICT DO NOTHING`` gives free idempotency without
    a separate unique index.
    """

    __tablename__ = "processed_stripe_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WebhookDeliveryAttempt(Base):
    """Audit trail for async Stripe webhook delivery attempts.

    One row per attempt (initial + retries). ``is_dead_letter`` is set on the
    final row when all retries are exhausted and the event cannot be processed.
    """

    __tablename__ = "webhook_delivery_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt_num: Mapped[int] = mapped_column(Integer, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)  # 'success' | 'fail'
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_dead_letter: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
