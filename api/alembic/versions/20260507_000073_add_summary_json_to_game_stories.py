"""Add summary_json column to sports_game_stories.

Adds the column that backs the v3-summary story_version. v3-summary rows
store a single LLM-generated narrative (3-5 paragraphs + referenced play
ids + final score) here; v2-blocks rows leave it NULL.

Nullable so historical rows continue to read.

Revision ID: 20260507_000073
Revises: 20260505_000072
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260507_000073"
down_revision = "20260505_000072"
branch_labels = None
depends_on = None

_TABLE = "sports_game_stories"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "summary_json")
