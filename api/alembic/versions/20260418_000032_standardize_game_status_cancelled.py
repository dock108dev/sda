"""Standardize GameStatus cancelled spelling: canceled → cancelled.

Revision ID: game_status_cancelled_001
Revises: forecast_blend_cols_001
Create Date: 2026-04-18

sports_games.status is VARCHAR(20), not a native PG enum, so this is a
plain UPDATE. Both old variants ('canceled' and 'cancelled') are backfilled
to the canonical 'cancelled' value.
"""

from __future__ import annotations

from alembic import op


revision = "game_status_cancelled_001"
down_revision = "forecast_blend_cols_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE sports_games SET status = 'cancelled' WHERE status IN ('canceled', 'cancelled')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE sports_games SET status = 'canceled' WHERE status = 'cancelled'"
    )
