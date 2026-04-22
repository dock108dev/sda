"""Add webhook_delivery_attempts table for async retry and dead-letter tracking.

Revision ID: 20260421_000064
Revises: 20260421_000063
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260421_000064"
down_revision = "20260421_000063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_delivery_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("attempt_num", sa.Integer(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "is_dead_letter",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_webhook_delivery_attempts_event_id",
        "webhook_delivery_attempts",
        ["event_id"],
    )
    op.create_index(
        "ix_webhook_delivery_attempts_is_dead_letter",
        "webhook_delivery_attempts",
        ["is_dead_letter"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_delivery_attempts_is_dead_letter",
        table_name="webhook_delivery_attempts",
    )
    op.drop_index(
        "ix_webhook_delivery_attempts_event_id",
        table_name="webhook_delivery_attempts",
    )
    op.drop_table("webhook_delivery_attempts")
