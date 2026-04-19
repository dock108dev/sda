"""Add NOT NULL constraint to team_social_posts.game_phase after backfill.

Revision ID: game_phase_not_null_001
Revises: game_phase_unknown_001
Create Date: 2026-04-18

Backfills any remaining NULL game_phase rows to 'unknown', validates the
backfill completed (raises if any NULLs remain), then applies NOT NULL.
Also tightens the existing CHECK constraint to drop the now-redundant
IS NULL OR clause.

Down: reverts the column to nullable and restores the permissive CHECK.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "game_phase_not_null_001"
down_revision = "game_phase_unknown_001"
branch_labels = None
depends_on = None

_TABLE = "team_social_posts"
_COLUMN = "game_phase"
_CHECK_NAME = "ck_team_social_posts_game_phase_valid"
_VALID_VALUES = ("'pregame'", "'in_game'", "'postgame'", "'unknown'")


def upgrade() -> None:
    conn = op.get_bind()

    # Count nulls before backfill for audit log
    before = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE {_COLUMN} IS NULL")
    ).scalar()

    if before:
        op.execute(
            sa.text(
                f"UPDATE {_TABLE} SET {_COLUMN} = 'unknown' WHERE {_COLUMN} IS NULL"
            )
        )

    # Validate: must be zero nulls before we can add NOT NULL
    after = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE} WHERE {_COLUMN} IS NULL")
    ).scalar()
    if after != 0:
        raise RuntimeError(
            f"Backfill incomplete: {after} NULL game_phase rows remain in {_TABLE}"
        )

    # Replace the permissive CHECK (allowed NULL) with a strict one
    values_list = ", ".join(_VALID_VALUES)
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_CHECK_NAME}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CHECK_NAME} "
        f"CHECK ({_COLUMN} IN ({values_list}))"
    )

    op.alter_column(_TABLE, _COLUMN, existing_type=sa.String(20), nullable=False)


def downgrade() -> None:
    # Make nullable again
    op.alter_column(_TABLE, _COLUMN, existing_type=sa.String(20), nullable=True)

    # Restore permissive CHECK that allows NULL
    values_list = ", ".join(_VALID_VALUES)
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_CHECK_NAME}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CHECK_NAME} "
        f"CHECK ({_COLUMN} IS NULL OR {_COLUMN} IN ({values_list}))"
    )
