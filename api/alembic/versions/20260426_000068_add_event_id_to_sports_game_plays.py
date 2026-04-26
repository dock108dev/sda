"""Add event_id column to sports_game_plays for stable upsert identity.

Background:
  NHL play-by-play rows are upserted on (game_id, play_index), where
  play_index = period * 10000 + sortOrder.  The NHL API occasionally
  returns the same logical event with a different sortOrder between
  scrape runs, so the same play lands at two different play_index values
  and the ON CONFLICT target never matches — producing visible duplicates
  in the PBP table.

  The NHL API does emit a stable per-event identifier (eventId).  Today
  it is captured into raw_data['event_id'] but is not used for uniqueness.
  This migration promotes it to a real column with a partial unique index,
  so the persistence layer can target ON CONFLICT (game_id, event_id) when
  an event_id is present (NHL today; available for other sources later).

Steps:
  1. Add event_id BIGINT column (nullable; only sources with a stable
     per-event id will populate it).
  2. Backfill from raw_data['event_id'] where present and numeric.
  3. Collapse pre-existing logical duplicates: for each (game_id, event_id)
     group, keep the row with the lowest play_index and delete the rest.
  4. Create a partial unique index on (game_id, event_id) so the ON
     CONFLICT target is well-defined for rows that carry an event_id,
     while leaving rows without one constrained only by the existing
     (game_id, play_index) unique constraint.

Revision ID: 20260426_000068
Revises: 20260422_000067
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_000068"
down_revision = "20260422_000067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sports_game_plays",
        sa.Column("event_id", sa.BigInteger(), nullable=True),
    )

    # Backfill from raw_data['event_id'] where it parses as an integer.
    # The ~ '^-?[0-9]+$' guard skips any malformed values that would
    # otherwise raise on the cast.
    op.execute(
        """
        UPDATE sports_game_plays
        SET event_id = (raw_data->>'event_id')::bigint
        WHERE raw_data ? 'event_id'
          AND raw_data->>'event_id' IS NOT NULL
          AND raw_data->>'event_id' ~ '^-?[0-9]+$'
        """
    )

    # Collapse logical duplicates produced by sortOrder drift across
    # scrape runs.  Keep the lowest play_index per (game_id, event_id);
    # this preserves the canonical chronological position for the play.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, event_id
                    ORDER BY play_index, id
                ) AS rn
            FROM sports_game_plays
            WHERE event_id IS NOT NULL
        )
        DELETE FROM sports_game_plays
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.create_index(
        "uq_sports_game_plays_game_event",
        "sports_game_plays",
        ["game_id", "event_id"],
        unique=True,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_sports_game_plays_game_event",
        table_name="sports_game_plays",
    )
    op.drop_column("sports_game_plays", "event_id")
