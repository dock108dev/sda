"""Add clubs table and update golf_pools for club-scoped tenancy.

Revision ID: 20260421_000061
Revises: 20260421_000060
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260421_000061"
down_revision = "20260421_000060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clubs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("club_id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'cancelled')",
            name="ck_clubs_status",
        ),
    )
    op.create_index("ix_clubs_club_id", "clubs", ["club_id"], unique=True)
    op.create_index("ix_clubs_slug", "clubs", ["slug"], unique=True)
    op.create_index("ix_clubs_owner_user_id", "clubs", ["owner_user_id"])

    # Add club_id FK to golf_pools for club-scoped tenancy (Phase 3).
    op.add_column("golf_pools", sa.Column("club_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_golf_pools_club_id",
        "golf_pools",
        "clubs",
        ["club_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_golf_pools_club_id", "golf_pools", ["club_id"])

    # Allow null tournament_id for draft pools created during provisioning.
    # Pools are linked to a tournament in Phase 4 when the admin schedules them.
    op.alter_column("golf_pools", "tournament_id", nullable=True)


def downgrade() -> None:
    op.alter_column("golf_pools", "tournament_id", nullable=False)
    op.drop_index("ix_golf_pools_club_id", table_name="golf_pools")
    op.drop_constraint("fk_golf_pools_club_id", "golf_pools", type_="foreignkey")
    op.drop_column("golf_pools", "club_id")

    op.drop_index("ix_clubs_owner_user_id", table_name="clubs")
    op.drop_index("ix_clubs_slug", table_name="clubs")
    op.drop_index("ix_clubs_club_id", table_name="clubs")
    op.drop_table("clubs")
