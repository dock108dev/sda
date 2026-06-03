"""Remove legacy spoiler policy from card feed artifacts.

Revision ID: 20260603_000078
Revises: 20260603_000077
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260603_000078"
down_revision = "20260603_000077"
branch_labels = None
depends_on = None

_TABLE = "sports_game_card_feed_artifacts"
_LEGACY_COLUMN = "spoiler_policy"


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _LEGACY_COLUMN in _column_names(inspector):
        op.drop_column(_TABLE, _LEGACY_COLUMN)


def downgrade() -> None:
    """No-op: spoiler-policy variants are no longer supported."""
