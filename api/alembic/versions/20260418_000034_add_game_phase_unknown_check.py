"""Add UNKNOWN to GamePhase: add CHECK constraint on team_social_posts.game_phase.

Revision ID: game_phase_unknown_001
Revises: external_jsonb_checks_001
Create Date: 2026-04-18

game_phase is stored as VARCHAR(20), not a native PG enum, so this migration
adds a CHECK constraint to enforce the finite set of valid values, including
the new 'unknown' value that replaces NULL for no-game tweets.

The constraint allows NULL so that existing unmapped rows are not rejected
before ISSUE-023 backfills them. Downgrade drops the constraint.
"""

from __future__ import annotations

from alembic import op


revision = "game_phase_unknown_001"
down_revision = "external_jsonb_checks_001"
branch_labels = None
depends_on = None

_VALID_VALUES = ("'pregame'", "'in_game'", "'postgame'", "'unknown'")
_CHECK_NAME = "ck_team_social_posts_game_phase_valid"
_TABLE = "team_social_posts"
_COLUMN = "game_phase"


def upgrade() -> None:
    values_list = ", ".join(_VALID_VALUES)
    op.execute(
        f"""
        ALTER TABLE {_TABLE}
            ADD CONSTRAINT {_CHECK_NAME}
            CHECK ({_COLUMN} IS NULL OR {_COLUMN} IN ({values_list}))
        """
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_CHECK_NAME}"
    )
