"""Make uq_game_play_index a partial unique on rows without event_id.

Background:
  Migration 0068 added a stable per-event id (sports_game_plays.event_id)
  and a partial unique index on (game_id, event_id) WHERE event_id IS NOT
  NULL.  The persistence layer now routes NHL upserts at that index
  because NHL's play_index = period * multiplier + sortOrder drifts
  between scrape responses.

  However, the legacy full UNIQUE on (game_id, play_index) was left in
  place.  When the NHL API renumbers sortOrder mid-game, two distinct
  events can swap play_indexes between polls: row A keeps its old
  play_index until UPDATE runs, while row B's INSERT lands on the same
  play_index.  ON CONFLICT (game_id, event_id) does not catch the
  collision on the (game_id, play_index) index, so the upsert raises
  UniqueViolation and the entire batch transaction rolls back — leaving
  affected NHL games stuck at whatever play count was committed before
  the collision (often P1 only).

  play_index uniqueness is only meaningful for sources that lack a stable
  event identifier.  Make the constraint partial WHERE event_id IS NULL
  so it continues to cover NBA/MLB/NCAAB (which never set event_id) while
  no longer applying to NHL (which always sets event_id).

Steps:
  1. Drop the full UNIQUE constraint uq_game_play_index.
  2. Recreate it as a partial unique index with the same name, scoped to
     event_id IS NULL.

Revision ID: 20260428_000069
Revises: 20260426_000068
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_000069"
down_revision = "20260426_000068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The original object is a UNIQUE INDEX (not a UNIQUE CONSTRAINT), even
    # though the ORM models it via UniqueConstraint(...).  Drop the index and
    # recreate it as a partial unique index with the same name.
    op.drop_index("uq_game_play_index", table_name="sports_game_plays")
    op.create_index(
        "uq_game_play_index",
        "sports_game_plays",
        ["game_id", "play_index"],
        unique=True,
        postgresql_where=sa.text("event_id IS NULL"),
    )


def downgrade() -> None:
    # Restoring the full unique can fail if NHL rows accumulated duplicate
    # (game_id, play_index) pairs while the partial index was in effect.
    # Collapse those duplicates first by keeping the lowest event_id per
    # (game_id, play_index) — event_id is the canonical identity for those
    # rows, so picking deterministically is safe.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, play_index
                    ORDER BY event_id NULLS LAST, id
                ) AS rn
            FROM sports_game_plays
        )
        DELETE FROM sports_game_plays
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )
    op.drop_index("uq_game_play_index", table_name="sports_game_plays")
    op.create_index(
        "uq_game_play_index",
        "sports_game_plays",
        ["game_id", "play_index"],
        unique=True,
    )
