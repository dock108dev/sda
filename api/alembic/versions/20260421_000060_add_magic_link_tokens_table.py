"""Add magic_link_tokens table and allow nullable password_hash on users.

Revision ID: 20260421_000060
Revises: 20260421_000059
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260421_000060"
down_revision = "20260421_000059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_magic_link_tokens_email", "magic_link_tokens", ["email"])
    op.create_index(
        "ix_magic_link_tokens_token_hash",
        "magic_link_tokens",
        ["token_hash"],
        unique=True,
    )
    # Allow club_admin accounts created during onboarding to have no password;
    # they authenticate via magic link and may set a password later via reset.
    op.alter_column("users", "password_hash", nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash", nullable=False)
    op.drop_index("ix_magic_link_tokens_token_hash", table_name="magic_link_tokens")
    op.drop_index("ix_magic_link_tokens_email", table_name="magic_link_tokens")
    op.drop_table("magic_link_tokens")
