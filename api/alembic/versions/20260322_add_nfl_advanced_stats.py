"""Add NFL advanced stats tables (team-level and player-level EPA/WPA/CPOE).

Revision ID: nfl_adv_stats_001
Revises: sim_obs_001
Create Date: 2026-03-22

Two tables for nflverse-derived advanced stats:
- nfl_game_advanced_stats: team-level (2 rows per game)
- nfl_player_advanced_stats: player-level (per player per role per game)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "nfl_adv_stats_001"
down_revision = "nhl_adv_stats_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- nfl_game_advanced_stats ---
    op.create_table(
        "nfl_game_advanced_stats",
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
        # EPA metrics
        sa.Column("total_epa", sa.Float(), nullable=True),
        sa.Column("pass_epa", sa.Float(), nullable=True),
        sa.Column("rush_epa", sa.Float(), nullable=True),
        sa.Column("epa_per_play", sa.Float(), nullable=True),
        # WPA
        sa.Column("total_wpa", sa.Float(), nullable=True),
        # Success rates
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column("pass_success_rate", sa.Float(), nullable=True),
        sa.Column("rush_success_rate", sa.Float(), nullable=True),
        # Explosive plays
        sa.Column("explosive_play_rate", sa.Float(), nullable=True),
        # Passing context
        sa.Column("avg_cpoe", sa.Float(), nullable=True),
        sa.Column("avg_air_yards", sa.Float(), nullable=True),
        sa.Column("avg_yac", sa.Float(), nullable=True),
        # Volume
        sa.Column("total_plays", sa.Integer(), nullable=True),
        sa.Column("pass_plays", sa.Integer(), nullable=True),
        sa.Column("rush_plays", sa.Integer(), nullable=True),
        # Extensibility
        sa.Column("raw_extras", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Constraints
        sa.UniqueConstraint("game_id", "team_id", name="uq_nfl_advanced_game_team"),
    )
    op.create_index("idx_nfl_advanced_game", "nfl_game_advanced_stats", ["game_id"])
    op.create_index("idx_nfl_advanced_team", "nfl_game_advanced_stats", ["team_id"])

    # --- nfl_player_advanced_stats ---
    op.create_table(
        "nfl_player_advanced_stats",
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
        sa.Column("player_external_ref", sa.String(100), nullable=False),
        sa.Column("player_name", sa.String(200), nullable=False),
        sa.Column("player_role", sa.String(20), nullable=True),
        # EPA
        sa.Column("total_epa", sa.Float(), nullable=True),
        sa.Column("epa_per_play", sa.Float(), nullable=True),
        # Role-specific EPA
        sa.Column("pass_epa", sa.Float(), nullable=True),
        sa.Column("rush_epa", sa.Float(), nullable=True),
        sa.Column("receiving_epa", sa.Float(), nullable=True),
        # Passing
        sa.Column("cpoe", sa.Float(), nullable=True),
        sa.Column("air_epa", sa.Float(), nullable=True),
        sa.Column("yac_epa", sa.Float(), nullable=True),
        sa.Column("air_yards", sa.Float(), nullable=True),
        # WPA
        sa.Column("total_wpa", sa.Float(), nullable=True),
        # Success
        sa.Column("success_rate", sa.Float(), nullable=True),
        # Volume
        sa.Column("plays", sa.Integer(), nullable=True),
        # Extensibility
        sa.Column("raw_extras", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Constraints
        sa.UniqueConstraint(
            "game_id", "team_id", "player_external_ref", "player_role",
            name="uq_nfl_player_advanced_game_team_player_role",
        ),
    )
    op.create_index("idx_nfl_player_advanced_game", "nfl_player_advanced_stats", ["game_id"])
    op.create_index("idx_nfl_player_advanced_team", "nfl_player_advanced_stats", ["team_id"])


def downgrade() -> None:
    op.drop_table("nfl_player_advanced_stats")
    op.drop_table("nfl_game_advanced_stats")
