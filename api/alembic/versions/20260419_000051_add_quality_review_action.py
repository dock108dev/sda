"""Add quality_review_action audit log table.

Revision ID: 20260419_000051
Revises: 20260419_000042
Create Date: 2026-04-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260419_000051"
down_revision = "20260419_000042"
branch_labels = None
depends_on = None

_TABLE = "quality_review_action"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=True),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_quality_review_action_flow_id", _TABLE, ["flow_id"])


def downgrade() -> None:
    op.drop_index("idx_quality_review_action_flow_id", table_name=_TABLE)
    op.drop_table(_TABLE)
