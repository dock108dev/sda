"""Add analytics_backtest_jobs table.

Revision ID: 20260307_backtest_jobs
Revises: 20260307_rolling_window
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260307_backtest_jobs"
down_revision = "20260307_rolling_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_backtest_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("artifact_path", sa.String(500), nullable=False),
        sa.Column("sport", sa.String(50), nullable=False),
        sa.Column("model_type", sa.String(100), nullable=False),
        sa.Column("date_start", sa.String(20), nullable=True),
        sa.Column("date_end", sa.String(20), nullable=True),
        sa.Column("rolling_window", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("status", sa.String(50), nullable=False, server_default="'pending'"),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("game_count", sa.Integer(), nullable=True),
        sa.Column("correct_count", sa.Integer(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("predictions", postgresql.JSONB(), nullable=True),
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
        "idx_backtest_jobs_model_id", "analytics_backtest_jobs", ["model_id"]
    )
    op.create_index(
        "idx_backtest_jobs_status", "analytics_backtest_jobs", ["status"]
    )


def downgrade() -> None:
    op.drop_index("idx_backtest_jobs_status", table_name="analytics_backtest_jobs")
    op.drop_index("idx_backtest_jobs_model_id", table_name="analytics_backtest_jobs")
    op.drop_table("analytics_backtest_jobs")
