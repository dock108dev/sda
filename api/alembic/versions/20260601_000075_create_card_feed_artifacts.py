"""Create materialized card feed artifacts table.

Revision ID: 20260601_000075
Revises: 20260514_000001
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260601_000075"
down_revision = "20260514_000001"
branch_labels = None
depends_on = None

_TABLE = "sports_game_card_feed_artifacts"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("sports_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("spoiler_policy", sa.String(length=32), nullable=False),
        sa.Column("generation_status", sa.String(length=32), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("card_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_play_index", sa.Integer(), nullable=True),
        sa.Column(
            "game_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "reveal_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "sections_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "cards_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "validation_issues_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generator_label", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "game_id",
            "contract_version",
            "spoiler_policy",
            name="uq_sports_game_card_feed_artifacts_game_contract_policy",
        ),
    )
    op.create_index("idx_sports_game_card_feed_artifacts_game", _TABLE, ["game_id"])
    op.create_index(
        "idx_sports_game_card_feed_artifacts_generated_at",
        _TABLE,
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_sports_game_card_feed_artifacts_generated_at", table_name=_TABLE)
    op.drop_index("idx_sports_game_card_feed_artifacts_game", table_name=_TABLE)
    op.drop_table(_TABLE)
