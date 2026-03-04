"""Add mlb_game_advanced_stats table and last_advanced_stats_at column.

Revision ID: 20260303_mlb_adv_stats
Revises: 20260301_mlb_social
Create Date: 2026-03-03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260303_mlb_adv_stats"
down_revision = "20260301_mlb_social"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mlb_game_advanced_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "game_id",
            sa.Integer(),
            sa.ForeignKey("sports_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("sports_teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_home", sa.Boolean(), nullable=False),
        # Plate discipline — raw counts
        sa.Column("total_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zone_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zone_swings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zone_contact", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outside_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outside_swings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outside_contact", sa.Integer(), nullable=False, server_default="0"),
        # Plate discipline — derived percentages
        sa.Column("z_swing_pct", sa.Float(), nullable=True),
        sa.Column("o_swing_pct", sa.Float(), nullable=True),
        sa.Column("z_contact_pct", sa.Float(), nullable=True),
        sa.Column("o_contact_pct", sa.Float(), nullable=True),
        # Quality of contact — raw counts
        sa.Column("balls_in_play", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_exit_velo", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hard_hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("barrel_count", sa.Integer(), nullable=False, server_default="0"),
        # Quality of contact — derived percentages
        sa.Column("avg_exit_velo", sa.Float(), nullable=True),
        sa.Column("hard_hit_pct", sa.Float(), nullable=True),
        sa.Column("barrel_pct", sa.Float(), nullable=True),
        # Extensibility
        sa.Column(
            "raw_extras",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
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
        sa.UniqueConstraint("game_id", "team_id", name="uq_mlb_advanced_game_team"),
    )
    op.create_index("idx_mlb_advanced_game", "mlb_game_advanced_stats", ["game_id"])
    op.create_index("idx_mlb_advanced_team", "mlb_game_advanced_stats", ["team_id"])

    op.add_column(
        "sports_games",
        sa.Column("last_advanced_stats_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sports_games", "last_advanced_stats_at")
    op.drop_index("idx_mlb_advanced_team", table_name="mlb_game_advanced_stats")
    op.drop_index("idx_mlb_advanced_game", table_name="mlb_game_advanced_stats")
    op.drop_table("mlb_game_advanced_stats")
