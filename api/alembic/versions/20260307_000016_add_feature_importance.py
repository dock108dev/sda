"""Add feature_importance column to analytics_training_jobs.

Revision ID: 20260307_feature_importance
Revises: 20260307_backtest_jobs
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260307_feature_importance"
down_revision = "20260307_backtest_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analytics_training_jobs",
        sa.Column("feature_importance", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analytics_training_jobs", "feature_importance")
