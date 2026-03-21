"""Add sim observability columns to analytics_prediction_outcomes.

Revision ID: sim_obs_001
Revises: pool_001
Create Date: 2026-03-21

Adds variance, iteration count, profile metadata, and feature snapshot
columns to support the model-odds calibration and uncertainty pipeline.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "sim_obs_001"
down_revision = "pool_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("sim_wp_std_dev", sa.Float(), nullable=True),
    )
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("sim_iterations", sa.Integer(), nullable=True),
    )
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("sim_score_std_home", sa.Float(), nullable=True),
    )
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("sim_score_std_away", sa.Float(), nullable=True),
    )
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("profile_games_home", sa.Integer(), nullable=True),
    )
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("profile_games_away", sa.Integer(), nullable=True),
    )
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("sim_probability_source", sa.String(50), nullable=True),
    )
    op.add_column(
        "analytics_prediction_outcomes",
        sa.Column("feature_snapshot", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analytics_prediction_outcomes", "feature_snapshot")
    op.drop_column("analytics_prediction_outcomes", "sim_probability_source")
    op.drop_column("analytics_prediction_outcomes", "profile_games_away")
    op.drop_column("analytics_prediction_outcomes", "profile_games_home")
    op.drop_column("analytics_prediction_outcomes", "sim_score_std_away")
    op.drop_column("analytics_prediction_outcomes", "sim_score_std_home")
    op.drop_column("analytics_prediction_outcomes", "sim_iterations")
    op.drop_column("analytics_prediction_outcomes", "sim_wp_std_dev")
