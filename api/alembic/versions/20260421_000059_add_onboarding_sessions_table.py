"""Add onboarding_sessions table.

Revision ID: 20260421_000059
Revises: 20260421_000058
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260421_000059"
down_revision = "20260421_000058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_token", sa.String(length=64), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("claim_id", sa.String(length=32), nullable=False),
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'claimed', 'expired')",
            name="ck_onboarding_sessions_status",
        ),
    )
    op.create_index(
        "ix_onboarding_sessions_session_token",
        "onboarding_sessions",
        ["session_token"],
        unique=True,
    )
    op.create_index(
        "ix_onboarding_sessions_claim_token",
        "onboarding_sessions",
        ["claim_token"],
        unique=True,
    )
    op.create_index(
        "ix_onboarding_sessions_claim_id",
        "onboarding_sessions",
        ["claim_id"],
    )
    op.create_index(
        "ix_onboarding_sessions_stripe_checkout_session_id",
        "onboarding_sessions",
        ["stripe_checkout_session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_onboarding_sessions_stripe_checkout_session_id",
        table_name="onboarding_sessions",
    )
    op.drop_index(
        "ix_onboarding_sessions_claim_id",
        table_name="onboarding_sessions",
    )
    op.drop_index(
        "ix_onboarding_sessions_claim_token",
        table_name="onboarding_sessions",
    )
    op.drop_index(
        "ix_onboarding_sessions_session_token",
        table_name="onboarding_sessions",
    )
    op.drop_table("onboarding_sessions")
