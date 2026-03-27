"""Add toi_minutes column to nhl_skater_advanced_stats.

Revision ID: nhl_toi_001
Revises: nhl_adv_stats_001
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "nhl_toi_001"
down_revision = "nhl_adv_stats_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nhl_skater_advanced_stats",
        sa.Column("toi_minutes", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nhl_skater_advanced_stats", "toi_minutes")
