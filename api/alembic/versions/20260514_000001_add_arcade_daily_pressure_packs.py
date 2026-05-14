"""Add arcade_daily_pressure_packs table.

Persists the daily arcade pressure pack. One row per ``pack_date``;
``pack_version`` increments on regeneration of the same date. Payload is
JSONB so the pack shape can evolve without schema churn.

Revision ID: 20260514_000001
Revises: 20260510_000074
Create Date: 2026-05-14
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260514_000001"
down_revision = "20260510_000074"
branch_labels = None
depends_on = None

_TABLE = "arcade_daily_pressure_packs"
_PACK_DATE_INDEX = "ix_arcade_daily_pressure_packs_pack_date"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pack_date", sa.Date(), nullable=False),
        sa.Column("pack_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "is_final",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(_PACK_DATE_INDEX, _TABLE, ["pack_date"], unique=True)


def downgrade() -> None:
    op.drop_index(_PACK_DATE_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
