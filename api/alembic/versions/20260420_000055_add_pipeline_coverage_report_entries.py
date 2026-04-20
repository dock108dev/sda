"""Add pipeline_coverage_report per-game entries table.

Revision ID: 20260420_000055
Revises: pipeline_jsonb_checks_001
Create Date: 2026-04-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260420_000055"
down_revision = "pipeline_jsonb_checks_001"
branch_labels = None
depends_on = None

_TABLE = "pipeline_coverage_report"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("has_flow", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("gap_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_date", "game_id", name="uq_coverage_report_date_game"),
    )
    op.create_index("idx_coverage_report_date", _TABLE, ["report_date"])
    op.create_index("idx_coverage_report_sport_date", _TABLE, ["sport", "report_date"])


def downgrade() -> None:
    op.drop_index("idx_coverage_report_sport_date", table_name=_TABLE)
    op.drop_index("idx_coverage_report_date", table_name=_TABLE)
    op.drop_table(_TABLE)
