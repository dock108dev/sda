"""Add ingest error tracking columns to sports_games.

Revision ID: game_ingest_errors_001
Revises: nhl_toi_001
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "game_ingest_errors_001"
down_revision = "nhl_toi_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sports_games",
        sa.Column(
            "ingest_error_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "sports_games",
        sa.Column("last_ingest_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sports_games", "last_ingest_error")
    op.drop_column("sports_games", "ingest_error_count")
