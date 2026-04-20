"""Add recap_pending, recap_ready, recap_failed to GameStatus.

Revision ID: 20260419_000052
Revises: 20260419_000051
Create Date: 2026-04-19

sports_games.status is VARCHAR(20), not a native PG enum, so no DDL change
is required — the column already accepts any string up to 20 chars and all
three new values (recap_pending=13, recap_ready=11, recap_failed=12) fit.

This migration is a marker that records the valid value set expansion and
backfills any stale rows.  If the project later adds a CHECK constraint,
add it here.
"""

from __future__ import annotations

from alembic import op

revision = "20260419_000052"
down_revision = "20260419_000051"
branch_labels = None
depends_on = None

# New status values introduced by this migration
_NEW_VALUES = ("recap_pending", "recap_ready", "recap_failed")


def upgrade() -> None:
    # No DDL needed for VARCHAR(20).  Mark the schema intent with a comment.
    op.execute(
        "COMMENT ON COLUMN sports_games.status IS "
        "'GameStatus: scheduled|pregame|live|final|archived|postponed|cancelled"
        "|recap_pending|recap_ready|recap_failed'"
    )


def downgrade() -> None:
    # Reset any rows that landed in a recap_* state back to final so the app
    # can continue operating on the previous code.
    op.execute(
        "UPDATE sports_games SET status = 'final' "
        "WHERE status IN ('recap_pending', 'recap_ready', 'recap_failed')"
    )
    op.execute(
        "COMMENT ON COLUMN sports_games.status IS "
        "'GameStatus: scheduled|pregame|live|final|archived|postponed|cancelled'"
    )
