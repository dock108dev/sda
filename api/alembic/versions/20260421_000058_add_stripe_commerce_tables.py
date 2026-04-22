"""Add stripe_customers, stripe_subscriptions, processed_stripe_events tables.

Revision ID: 20260421_000058
Revises: 20260421_000057
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260421_000058"
down_revision = "20260421_000057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stripe_customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("club_id", sa.Integer(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_stripe_customers_club_id",
        "stripe_customers",
        ["club_id"],
    )
    op.create_index(
        "ix_stripe_customers_stripe_customer_id",
        "stripe_customers",
        ["stripe_customer_id"],
        unique=True,
    )

    op.create_table(
        "stripe_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("metadata", JSONB, nullable=True),
    )
    op.create_index(
        "ix_stripe_subscriptions_stripe_subscription_id",
        "stripe_subscriptions",
        ["stripe_subscription_id"],
        unique=True,
    )
    op.create_index(
        "ix_stripe_subscriptions_stripe_customer_id",
        "stripe_subscriptions",
        ["stripe_customer_id"],
    )

    op.create_table(
        "processed_stripe_events",
        sa.Column("event_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("processed_stripe_events")

    op.drop_index(
        "ix_stripe_subscriptions_stripe_customer_id",
        table_name="stripe_subscriptions",
    )
    op.drop_index(
        "ix_stripe_subscriptions_stripe_subscription_id",
        table_name="stripe_subscriptions",
    )
    op.drop_table("stripe_subscriptions")

    op.drop_index(
        "ix_stripe_customers_stripe_customer_id",
        table_name="stripe_customers",
    )
    op.drop_index(
        "ix_stripe_customers_club_id",
        table_name="stripe_customers",
    )
    op.drop_table("stripe_customers")
