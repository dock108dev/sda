"""Create scroll_down_mlb_decks table.

Storage for generated Scroll Down MLB decks. JSONB-first; the deck schema
is still evolving. Many rows per game: one per (deck_version, spoiler_policy).

Revision ID: 20260510_000074
Revises: 20260507_000073
Create Date: 2026-05-10
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260510_000074"
down_revision = "20260507_000073"
branch_labels = None
depends_on = None

_TABLE = "scroll_down_mlb_decks"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("deck_version", sa.String(length=64), nullable=False),
        sa.Column("spoiler_policy", sa.String(length=32), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "planner_report_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "validation_warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "validation_errors_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
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
        sa.Column("card_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generator_label", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "game_id",
            "deck_version",
            "spoiler_policy",
            name="uq_scroll_down_mlb_decks_game_version_policy",
        ),
    )
    op.create_index(
        "ix_scroll_down_mlb_decks_game_id",
        _TABLE,
        ["game_id"],
    )
    op.create_index(
        "ix_scroll_down_mlb_decks_game_id_generated_at",
        _TABLE,
        ["game_id", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scroll_down_mlb_decks_game_id_generated_at", table_name=_TABLE)
    op.drop_index("ix_scroll_down_mlb_decks_game_id", table_name=_TABLE)
    op.drop_table(_TABLE)
