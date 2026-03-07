"""Add analytics_feature_configs and analytics_training_jobs tables.

Revision ID: 20260307_analytics_fc
Revises: 20260305_deactivate_social
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260307_analytics_fc"
down_revision = "20260305_deactivate_social"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_feature_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("sport", sa.String(50), nullable=False),
        sa.Column("model_type", sa.String(100), nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_analytics_fc_sport", "analytics_feature_configs", ["sport"]
    )
    op.create_index(
        "idx_analytics_fc_model_type", "analytics_feature_configs", ["model_type"]
    )

    op.create_table(
        "analytics_training_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "feature_config_id",
            sa.Integer(),
            sa.ForeignKey("analytics_feature_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sport", sa.String(50), nullable=False),
        sa.Column("model_type", sa.String(100), nullable=False),
        sa.Column(
            "algorithm", sa.String(100), nullable=False, server_default="gradient_boosting"
        ),
        sa.Column("date_start", sa.String(20), nullable=True),
        sa.Column("date_end", sa.String(20), nullable=True),
        sa.Column("test_split", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("random_state", sa.Integer(), nullable=False, server_default="42"),
        sa.Column("status", sa.String(50), nullable=False, server_default="'pending'"),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("model_id", sa.String(200), nullable=True),
        sa.Column("artifact_path", sa.String(500), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("train_count", sa.Integer(), nullable=True),
        sa.Column("test_count", sa.Integer(), nullable=True),
        sa.Column("feature_names", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_training_jobs_fc", "analytics_training_jobs", ["feature_config_id"]
    )
    op.create_index(
        "idx_training_jobs_status", "analytics_training_jobs", ["status"]
    )


def downgrade() -> None:
    op.drop_index("idx_training_jobs_status", table_name="analytics_training_jobs")
    op.drop_index("idx_training_jobs_fc", table_name="analytics_training_jobs")
    op.drop_table("analytics_training_jobs")
    op.drop_index("idx_analytics_fc_model_type", table_name="analytics_feature_configs")
    op.drop_index("idx_analytics_fc_sport", table_name="analytics_feature_configs")
    op.drop_table("analytics_feature_configs")
