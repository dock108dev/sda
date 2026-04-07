"""Add MLB daily forecasts work table.

Revision ID: mlb_daily_forecasts_001
Revises: user_prefs_score_hide_001
Create Date: 2026-04-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "mlb_daily_forecasts_001"
down_revision = "user_prefs_score_hide_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mlb_daily_forecasts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_id", sa.Integer, nullable=False),
        sa.Column("game_date", sa.String(20), nullable=False),
        # Teams
        sa.Column("home_team", sa.String(200), nullable=False),
        sa.Column("away_team", sa.String(200), nullable=False),
        sa.Column("home_team_id", sa.Integer, nullable=False),
        sa.Column("away_team_id", sa.Integer, nullable=False),
        # Simulation results
        sa.Column("home_win_prob", sa.Float, nullable=False),
        sa.Column("away_win_prob", sa.Float, nullable=False),
        sa.Column("predicted_home_score", sa.Float, nullable=True),
        sa.Column("predicted_away_score", sa.Float, nullable=True),
        sa.Column("probability_source", sa.String(50), nullable=True),
        sa.Column("sim_iterations", sa.Integer, nullable=False, server_default="5000"),
        sa.Column("sim_wp_std_dev", sa.Float, nullable=True),
        sa.Column("score_std_home", sa.Float, nullable=True),
        sa.Column("score_std_away", sa.Float, nullable=True),
        sa.Column("profile_games_home", sa.Integer, nullable=True),
        sa.Column("profile_games_away", sa.Integer, nullable=True),
        # Line analysis
        sa.Column("market_home_ml", sa.Integer, nullable=True),
        sa.Column("market_away_ml", sa.Integer, nullable=True),
        sa.Column("market_home_wp", sa.Float, nullable=True),
        sa.Column("market_away_wp", sa.Float, nullable=True),
        sa.Column("home_edge", sa.Float, nullable=True),
        sa.Column("away_edge", sa.Float, nullable=True),
        sa.Column("model_home_line", sa.Integer, nullable=True),
        sa.Column("model_away_line", sa.Integer, nullable=True),
        sa.Column("home_ev_pct", sa.Float, nullable=True),
        sa.Column("away_ev_pct", sa.Float, nullable=True),
        sa.Column("line_provider", sa.String(50), nullable=True),
        sa.Column("line_type", sa.String(20), nullable=True),
        # Metadata
        sa.Column("model_id", sa.String(200), nullable=True),
        sa.Column("event_summary", JSONB, nullable=True),
        sa.Column("feature_snapshot", JSONB, nullable=True),
        # Timestamps
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Constraints
        sa.UniqueConstraint("game_id", name="uq_mlb_daily_forecasts_game_id"),
    )
    op.create_index("ix_mlb_daily_forecasts_game_date", "mlb_daily_forecasts", ["game_date"])
    op.create_index("ix_mlb_daily_forecasts_date_edge", "mlb_daily_forecasts", ["game_date", "home_edge"])


def downgrade() -> None:
    op.drop_table("mlb_daily_forecasts")
