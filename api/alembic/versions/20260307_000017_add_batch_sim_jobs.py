"""Add analytics_batch_sim_jobs table.

Revision ID: 20260307_batch_sim_jobs
Revises: 20260307_feature_importance
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260307_batch_sim_jobs"
down_revision = "20260307_feature_importance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_batch_sim_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sport", sa.String(50), nullable=False),
        sa.Column(
            "probability_mode", sa.String(50), nullable=False, server_default="ml"
        ),
        sa.Column("iterations", sa.Integer(), nullable=False, server_default="5000"),
        sa.Column("rolling_window", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("date_start", sa.String(20), nullable=True),
        sa.Column("date_end", sa.String(20), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="'pending'"),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("game_count", sa.Integer(), nullable=True),
        sa.Column("results", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_batch_sim_jobs_status", "analytics_batch_sim_jobs", ["status"]
    )


def downgrade() -> None:
    op.drop_index("idx_batch_sim_jobs_status", table_name="analytics_batch_sim_jobs")
    op.drop_table("analytics_batch_sim_jobs")
