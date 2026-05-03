"""Add v2 schema fields to sports_game_stories.

Adds top-level columns required by the v2 game flow output schema:
  - version          (str)        — schema version literal, e.g. "game-flow-v2"
  - archetype        (str)        — deterministic game-shape label
  - winner_team_id   (str)        — winning team abbreviation
  - source_counts    (jsonb)      — {plays, scoring_events, lead_changes, ties}
  - validation       (jsonb)      — {status, warnings}

All columns are nullable so historical rows (and v1 readers) continue to work.
Per-block v2 fields (reason, lead_before, lead_after, evidence, label) live
inside the existing blocks_json column and need no migration.

Revision ID: 20260503_000070
Revises: 20260428_000069
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260503_000070"
down_revision = "20260428_000069"
branch_labels = None
depends_on = None

_TABLE = "sports_game_stories"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("version", sa.String(20), nullable=True))
    op.add_column(_TABLE, sa.Column("archetype", sa.String(50), nullable=True))
    op.add_column(_TABLE, sa.Column("winner_team_id", sa.String(20), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column("source_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "validation")
    op.drop_column(_TABLE, "source_counts")
    op.drop_column(_TABLE, "winner_team_id")
    op.drop_column(_TABLE, "archetype")
    op.drop_column(_TABLE, "version")
