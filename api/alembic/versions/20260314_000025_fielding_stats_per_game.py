"""Convert mlb_player_fielding_stats from season-level to per-game.

Drop the empty season-level table and recreate as per-game with game_id FK,
matching the pattern of mlb_pitcher_game_stats.

Revision ID: 20260314_fielding_per_game
Revises: 20260314_merge_tip_time
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

revision = "20260314_fielding_per_game"
down_revision = "20260314_merge_tip_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the empty season-level table
    op.drop_index("idx_fielding_team_season", table_name="mlb_player_fielding_stats")
    op.drop_index("idx_fielding_player", table_name="mlb_player_fielding_stats")
    op.drop_constraint("uq_mlb_fielding_player_season_pos", "mlb_player_fielding_stats", type_="unique")
    op.drop_table("mlb_player_fielding_stats")

    # Recreate as per-game table
    op.create_table(
        "mlb_player_fielding_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("sports_games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("sports_teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_external_ref", sa.String(100), nullable=False),
        sa.Column("player_name", sa.String(200), nullable=False),
        sa.Column("position", sa.String(10), nullable=True),
        # Basic fielding metrics (from boxscores)
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assists", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("putouts", sa.Integer(), nullable=False, server_default="0"),
        # Advanced metrics (future enrichment from Baseball Savant)
        sa.Column("outs_above_average", sa.Float(), nullable=True),
        sa.Column("defensive_runs_saved", sa.Float(), nullable=True),
        sa.Column("uzr", sa.Float(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_fielding_game", "mlb_player_fielding_stats", ["game_id"])
    op.create_index("idx_fielding_player", "mlb_player_fielding_stats", ["player_external_ref"])
    op.create_index("idx_fielding_team", "mlb_player_fielding_stats", ["team_id"])
    op.create_unique_constraint(
        "uq_mlb_fielding_game_player",
        "mlb_player_fielding_stats",
        ["game_id", "player_external_ref"],
    )


def downgrade() -> None:
    # Drop per-game table
    op.drop_index("idx_fielding_game", table_name="mlb_player_fielding_stats")
    op.drop_index("idx_fielding_player", table_name="mlb_player_fielding_stats")
    op.drop_index("idx_fielding_team", table_name="mlb_player_fielding_stats")
    op.drop_constraint("uq_mlb_fielding_game_player", "mlb_player_fielding_stats", type_="unique")
    op.drop_table("mlb_player_fielding_stats")

    # Recreate original season-level table
    op.create_table(
        "mlb_player_fielding_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_external_ref", sa.String(100), nullable=False),
        sa.Column("player_name", sa.String(200), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("sports_teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(10), nullable=True),
        sa.Column("outs_above_average", sa.Float(), nullable=True),
        sa.Column("defensive_runs_saved", sa.Float(), nullable=True),
        sa.Column("uzr", sa.Float(), nullable=True),
        sa.Column("games_played", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("innings_at_position", sa.Float(), nullable=True),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assists", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("putouts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("defensive_value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("raw_extras", sa.JSON(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_fielding_player", "mlb_player_fielding_stats", ["player_external_ref"])
    op.create_index("idx_fielding_team_season", "mlb_player_fielding_stats", ["team_id", "season"])
    op.create_unique_constraint(
        "uq_mlb_fielding_player_season_pos",
        "mlb_player_fielding_stats",
        ["player_external_ref", "season", "position"],
    )
