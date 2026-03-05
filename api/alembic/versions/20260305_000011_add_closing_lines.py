"""Add closing_lines table for durable closing-line snapshots.

Revision ID: 20260305_closing_lines
Revises: 20260303_mlb_player_adv
Create Date: 2026-03-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260305_closing_lines"
down_revision = "20260303_mlb_player_adv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "closing_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("sports_games.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("league", sa.String(10), nullable=False),
        sa.Column("market_key", sa.String(80), nullable=False),
        sa.Column("selection", sa.String(200), nullable=False),
        sa.Column("line_value", sa.Float(), nullable=True),
        sa.Column("price_american", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_type",
            sa.String(20),
            nullable=False,
            server_default="closing",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_closing_lines_identity",
        "closing_lines",
        ["game_id", "provider", "market_key", "selection", "line_value"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_closing_lines_identity", table_name="closing_lines")
    op.drop_table("closing_lines")
