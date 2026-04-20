"""Migrate odds_api_event_id from external_ids JSONB to a proper column.

Revision ID: 20260419_000053
Revises: 20260419_000052
Create Date: 2026-04-19

external_ids["odds_api_event_id"] was queried directly as a JSONB key in
WHERE clauses.  This migration adds a typed VARCHAR(100) column and backfills
it from the existing JSONB payload so queries can target the real column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260419_000053"
down_revision = "20260419_000052"
branch_labels = None
depends_on = None

_TABLE = "sports_games"
_COLUMN = "odds_api_event_id"
_INDEX = "ix_sports_games_odds_api_event_id"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.String(100), nullable=True),
    )
    op.create_index(_INDEX, _TABLE, [_COLUMN])
    # Backfill from existing JSONB payload — safe on existing data
    op.execute(
        f"UPDATE {_TABLE} "
        f"SET {_COLUMN} = external_ids->>'odds_api_event_id' "
        f"WHERE external_ids ? 'odds_api_event_id'"
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _COLUMN)
