"""Add pool_lifecycle_events audit table.

Revision ID: 20260421_000062
Revises: 20260421_000061
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260421_000062"
down_revision = "20260421_000061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pool_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pool_id",
            sa.Integer(),
            sa.ForeignKey("golf_pools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(length=30), nullable=False),
        sa.Column("to_state", sa.String(length=30), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_pool_lifecycle_events_pool_id", "pool_lifecycle_events", ["pool_id"])
    op.create_index("ix_pool_lifecycle_events_created_at", "pool_lifecycle_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_pool_lifecycle_events_created_at", table_name="pool_lifecycle_events")
    op.drop_index("ix_pool_lifecycle_events_pool_id", table_name="pool_lifecycle_events")
    op.drop_table("pool_lifecycle_events")
