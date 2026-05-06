"""Add local_game_date to sports_games.

Stores the league-local (ET) calendar date a game is officially scheduled
for, separately from the UTC tipoff timestamp in ``game_date``. Lets
consumers group games by their "real" date without reimplementing
UTC→ET conversion (which previously caused late-evening west/central-time
games to be misfiled into the next day's bucket on the frontend).

Backfills existing rows by converting ``game_date`` to ET. Column is
nullable so a partial deploy is safe; a follow-up migration can promote
it to NOT NULL once all writers are confirmed populating it.

Revision ID: 20260505_000071
Revises: 20260503_000070
Create Date: 2026-05-05
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260505_000071"
down_revision = "20260503_000070"
branch_labels = None
depends_on = None

_TABLE = "sports_games"
_COLUMN = "local_game_date"
_INDEX = "ix_sports_games_local_game_date"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Date(), nullable=True))
    op.create_index(_INDEX, _TABLE, [_COLUMN])
    op.execute(
        f"""
        UPDATE {_TABLE}
        SET {_COLUMN} = (game_date AT TIME ZONE 'America/New_York')::date
        WHERE {_COLUMN} IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _COLUMN)
