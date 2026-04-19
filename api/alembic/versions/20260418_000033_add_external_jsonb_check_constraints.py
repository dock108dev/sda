"""Add Postgres check constraints to enforce object shape on external_ids / external_codes.

Revision ID: external_jsonb_checks_001
Revises: game_status_cancelled_001
Create Date: 2026-04-18

Secondary guard: the primary validation is the SQLAlchemy event hook in
api/app/db/external_id_validators.py.  These constraints ensure that even
direct SQL writes (migrations, psql, ETL pipelines) cannot store a non-object
value in these columns.

Both columns default to '{}' so the constraint is satisfied by all existing rows.
"""

from __future__ import annotations

from alembic import op


revision = "external_jsonb_checks_001"
down_revision = "game_status_cancelled_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sports_games
            ADD CONSTRAINT ck_sports_games_external_ids_is_object
            CHECK (jsonb_typeof(external_ids) = 'object')
        """
    )
    op.execute(
        """
        ALTER TABLE sports_teams
            ADD CONSTRAINT ck_sports_teams_external_codes_is_object
            CHECK (jsonb_typeof(external_codes) = 'object')
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sports_games DROP CONSTRAINT IF EXISTS ck_sports_games_external_ids_is_object"
    )
    op.execute(
        "ALTER TABLE sports_teams DROP CONSTRAINT IF EXISTS ck_sports_teams_external_codes_is_object"
    )
