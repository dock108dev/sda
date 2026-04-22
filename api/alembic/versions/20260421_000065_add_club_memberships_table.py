"""Add club_memberships table for RBAC invite flow.

Revision ID: 20260421_000065
Revises: 20260421_000064
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260421_000065"
down_revision = "20260421_000064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "club_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "club_id",
            sa.Integer(),
            sa.ForeignKey("clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invited_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("club_id", "user_id", name="uq_club_memberships_club_user"),
    )
    op.create_index("ix_club_memberships_club_id", "club_memberships", ["club_id"])
    op.create_index("ix_club_memberships_user_id", "club_memberships", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_club_memberships_user_id", table_name="club_memberships")
    op.drop_index("ix_club_memberships_club_id", table_name="club_memberships")
    op.drop_table("club_memberships")
