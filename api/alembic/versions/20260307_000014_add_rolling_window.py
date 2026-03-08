"""Add rolling_window column to analytics_training_jobs.

Revision ID: 20260307_rolling_window
Revises: 20260307_analytics_fc
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260307_rolling_window"
down_revision = "20260307_analytics_fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analytics_training_jobs",
        sa.Column("rolling_window", sa.Integer(), nullable=False, server_default="30"),
    )


def downgrade() -> None:
    op.drop_column("analytics_training_jobs", "rolling_window")
