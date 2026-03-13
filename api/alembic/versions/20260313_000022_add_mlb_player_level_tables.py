"""Add MLB player-level modeling tables.

New tables:
- mlb_pitcher_game_stats: Per-pitcher per-game pitching stats + Statcast
- mlb_player_fielding_stats: Player fielding stats (season-level)
- analytics_experiment_suites: Experiment sweep grouping
- analytics_experiment_variants: Individual variants within a suite
- analytics_replay_jobs: Historical replay for model evaluation

Revision ID: 20260313_mlb_player_level
Revises: 20260311_user_preferences
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260313_mlb_player_level"
down_revision = "20260311_user_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- MLB Pitcher Game Stats ---
    op.create_table(
        "mlb_pitcher_game_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("sports_games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("sports_teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_external_ref", sa.String(100), nullable=False),
        sa.Column("player_name", sa.String(200), nullable=False),
        sa.Column("is_starter", sa.Boolean(), nullable=False, server_default="false"),
        # Standard pitching line
        sa.Column("innings_pitched", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("earned_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("walks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("strikeouts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("home_runs_allowed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pitches_thrown", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("strikes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balls", sa.Integer(), nullable=False, server_default="0"),
        # Statcast aggregates
        sa.Column("batters_faced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zone_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zone_swings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("zone_contact", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outside_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outside_swings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outside_contact", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balls_in_play", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_exit_velo_against", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hard_hit_against", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("barrel_against", sa.Integer(), nullable=False, server_default="0"),
        # Derived rates
        sa.Column("k_rate", sa.Float(), nullable=True),
        sa.Column("bb_rate", sa.Float(), nullable=True),
        sa.Column("hr_rate", sa.Float(), nullable=True),
        sa.Column("whiff_rate", sa.Float(), nullable=True),
        sa.Column("z_contact_pct", sa.Float(), nullable=True),
        sa.Column("chase_rate", sa.Float(), nullable=True),
        sa.Column("avg_exit_velo_against", sa.Float(), nullable=True),
        sa.Column("hard_hit_pct_against", sa.Float(), nullable=True),
        sa.Column("barrel_pct_against", sa.Float(), nullable=True),
        # Extensibility
        sa.Column("raw_extras", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_pitcher_game_stats_game", "mlb_pitcher_game_stats", ["game_id"])
    op.create_index("idx_pitcher_game_stats_player", "mlb_pitcher_game_stats", ["player_external_ref"])
    op.create_unique_constraint(
        "uq_mlb_pitcher_game_stats_identity",
        "mlb_pitcher_game_stats",
        ["game_id", "team_id", "player_external_ref"],
    )

    # --- MLB Player Fielding Stats ---
    op.create_table(
        "mlb_player_fielding_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_external_ref", sa.String(100), nullable=False),
        sa.Column("player_name", sa.String(200), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("sports_teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(10), nullable=True),
        # Advanced metrics
        sa.Column("outs_above_average", sa.Float(), nullable=True),
        sa.Column("defensive_runs_saved", sa.Float(), nullable=True),
        sa.Column("uzr", sa.Float(), nullable=True),
        # Basic metrics
        sa.Column("games_played", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("innings_at_position", sa.Float(), nullable=True),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assists", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("putouts", sa.Integer(), nullable=False, server_default="0"),
        # Composite
        sa.Column("defensive_value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("raw_extras", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
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

    # --- Analytics Replay Jobs (must be before experiment variants due to FK) ---
    op.create_table(
        "analytics_replay_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sport", sa.String(50), nullable=False, server_default="mlb"),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("model_type", sa.String(100), nullable=False, server_default="plate_appearance"),
        sa.Column("date_start", sa.String(20), nullable=True),
        sa.Column("date_end", sa.String(20), nullable=True),
        sa.Column("game_count_requested", sa.Integer(), nullable=True),
        sa.Column("rolling_window", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("probability_mode", sa.String(50), nullable=False, server_default="ml"),
        sa.Column("iterations", sa.Integer(), nullable=False, server_default="5000"),
        sa.Column("suite_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("game_count", sa.Integer(), nullable=True),
        sa.Column("results", postgresql.JSONB(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- Analytics Experiment Suites ---
    op.create_table(
        "analytics_experiment_suites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sport", sa.String(50), nullable=False, server_default="mlb"),
        sa.Column("model_type", sa.String(100), nullable=False, server_default="plate_appearance"),
        sa.Column("parameter_grid", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("total_variants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_variants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_variants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("leaderboard", postgresql.JSONB(), nullable=True),
        sa.Column("promoted_model_id", sa.String(200), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Add suite_id FK to replay_jobs now that suites table exists
    op.create_foreign_key(
        "fk_replay_suite",
        "analytics_replay_jobs",
        "analytics_experiment_suites",
        ["suite_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- Analytics Experiment Variants ---
    op.create_table(
        "analytics_experiment_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("suite_id", sa.Integer(), sa.ForeignKey("analytics_experiment_suites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("algorithm", sa.String(100), nullable=False),
        sa.Column("rolling_window", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("feature_config_id", sa.Integer(), sa.ForeignKey("analytics_feature_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("training_date_start", sa.String(20), nullable=True),
        sa.Column("training_date_end", sa.String(20), nullable=True),
        sa.Column("test_split", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("extra_params", postgresql.JSONB(), nullable=True),
        sa.Column("training_job_id", sa.Integer(), sa.ForeignKey("analytics_training_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("replay_job_id", sa.Integer(), sa.ForeignKey("analytics_replay_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("training_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("replay_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_variant_suite", "analytics_experiment_variants", ["suite_id"])


def downgrade() -> None:
    op.drop_table("analytics_experiment_variants")
    op.drop_constraint("fk_replay_suite", "analytics_replay_jobs", type_="foreignkey")
    op.drop_table("analytics_experiment_suites")
    op.drop_table("analytics_replay_jobs")
    op.drop_table("mlb_player_fielding_stats")
    op.drop_table("mlb_pitcher_game_stats")
