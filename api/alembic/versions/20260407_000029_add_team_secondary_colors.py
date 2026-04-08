"""Add secondary color columns to sports_teams.

Revision ID: team_secondary_colors_001
Revises: mlb_daily_forecasts_001
Create Date: 2026-04-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "team_secondary_colors_001"
down_revision = "mlb_daily_forecasts_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sports_teams",
        sa.Column("color_secondary_light_hex", sa.String(7), nullable=True),
    )
    op.add_column(
        "sports_teams",
        sa.Column("color_secondary_dark_hex", sa.String(7), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sports_teams", "color_secondary_dark_hex")
    op.drop_column("sports_teams", "color_secondary_light_hex")
