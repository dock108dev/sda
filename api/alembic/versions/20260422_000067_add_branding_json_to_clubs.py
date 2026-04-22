"""Add branding_json JSONB column to clubs table (ISSUE-022).

Revision ID: 20260422_000067
Revises: 20260422_000066
Create Date: 2026-04-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260422_000067"
down_revision = "20260422_000066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clubs",
        sa.Column("branding_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clubs", "branding_json")
