"""Add golf domain tables.

Revision ID: golf_001
Revises: (latest)
Create Date: 2026-03-19

Golf data is a separate domain from team sports. Tables are prefixed
with ``golf_`` and use DataGolf's ``dg_id`` as the canonical player
identifier.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "golf_001"
down_revision = "20260314_fielding_per_game"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Players ---
    op.create_table(
        "golf_players",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dg_id", sa.Integer, nullable=False, unique=True, index=True),
        sa.Column("player_name", sa.String(200), nullable=False),
        sa.Column("country", sa.String(100)),
        sa.Column("country_code", sa.String(10)),
        sa.Column("amateur", sa.Boolean, default=False),
        sa.Column("dk_id", sa.Integer),
        sa.Column("fd_id", sa.Integer),
        sa.Column("yahoo_id", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # --- Tournaments ---
    op.create_table(
        "golf_tournaments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.String(50), nullable=False, index=True),
        sa.Column("tour", sa.String(20), nullable=False),  # pga, euro, kft, alt, opp
        sa.Column("event_name", sa.String(300), nullable=False),
        sa.Column("course", sa.String(300)),
        sa.Column("course_key", sa.String(100)),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("season", sa.Integer),
        sa.Column("purse", sa.Float),
        sa.Column("currency", sa.String(10), default="USD"),
        sa.Column("country", sa.String(100)),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("status", sa.String(30), default="scheduled"),  # scheduled, in_progress, completed
        sa.Column("current_round", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("event_id", "tour", name="uq_golf_tournament_event_tour"),
    )

    # --- Tournament Fields ---
    op.create_table(
        "golf_tournament_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, sa.ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, sa.ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_name", sa.String(200)),
        sa.Column("status", sa.String(30), default="active"),  # active, cut, wd, dq
        sa.Column("tee_time_r1", sa.String(20)),
        sa.Column("tee_time_r2", sa.String(20)),
        sa.Column("early_late", sa.String(10)),
        sa.Column("course", sa.String(200)),  # For multi-course events
        sa.Column("dk_salary", sa.Integer),
        sa.Column("fd_salary", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tournament_id", "dg_id", name="uq_golf_field_entry"),
    )
    op.create_index("idx_golf_field_tournament", "golf_tournament_fields", ["tournament_id"])

    # --- Leaderboard (snapshot table) ---
    op.create_table(
        "golf_leaderboard",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, sa.ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, sa.ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_name", sa.String(200)),
        sa.Column("position", sa.Integer),
        sa.Column("total_score", sa.Integer),  # Relative to par
        sa.Column("today_score", sa.Integer),
        sa.Column("thru", sa.Integer),
        sa.Column("total_strokes", sa.Integer),
        sa.Column("r1", sa.Integer),
        sa.Column("r2", sa.Integer),
        sa.Column("r3", sa.Integer),
        sa.Column("r4", sa.Integer),
        sa.Column("status", sa.String(30), default="active"),
        # Strokes gained
        sa.Column("sg_total", sa.Float),
        sa.Column("sg_ott", sa.Float),
        sa.Column("sg_app", sa.Float),
        sa.Column("sg_arg", sa.Float),
        sa.Column("sg_putt", sa.Float),
        # Live predictions
        sa.Column("win_prob", sa.Float),
        sa.Column("top_5_prob", sa.Float),
        sa.Column("top_10_prob", sa.Float),
        sa.Column("make_cut_prob", sa.Float),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tournament_id", "dg_id", name="uq_golf_leaderboard_entry"),
    )
    op.create_index("idx_golf_leaderboard_tournament", "golf_leaderboard", ["tournament_id"])

    # --- Rounds ---
    op.create_table(
        "golf_rounds",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, sa.ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, sa.ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_num", sa.Integer, nullable=False),
        sa.Column("score", sa.Integer),  # Relative to par
        sa.Column("strokes", sa.Integer),
        sa.Column("sg_total", sa.Float),
        sa.Column("sg_ott", sa.Float),
        sa.Column("sg_app", sa.Float),
        sa.Column("sg_arg", sa.Float),
        sa.Column("sg_putt", sa.Float),
        sa.Column("driving_dist", sa.Float),
        sa.Column("driving_acc", sa.Float),
        sa.Column("gir", sa.Float),
        sa.Column("scrambling", sa.Float),
        sa.Column("prox", sa.Float),
        sa.Column("putts_per_round", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tournament_id", "dg_id", "round_num", name="uq_golf_round"),
    )

    # --- Player Stats (periodic snapshots) ---
    op.create_table(
        "golf_player_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dg_id", sa.Integer, sa.ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(30), default="current"),  # "current", "long_term", "recent"
        sa.Column("sg_total", sa.Float),
        sa.Column("sg_ott", sa.Float),
        sa.Column("sg_app", sa.Float),
        sa.Column("sg_arg", sa.Float),
        sa.Column("sg_putt", sa.Float),
        sa.Column("driving_dist", sa.Float),
        sa.Column("driving_acc", sa.Float),
        sa.Column("dg_rank", sa.Integer),
        sa.Column("owgr", sa.Integer),
        sa.Column("sample_size", sa.Integer),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("dg_id", "period", name="uq_golf_player_stats"),
    )

    # --- Tournament Odds ---
    op.create_table(
        "golf_tournament_odds",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, sa.ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, sa.ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_name", sa.String(200)),
        sa.Column("book", sa.String(50), nullable=False),
        sa.Column("market", sa.String(30), nullable=False),  # win, top_5, top_10, make_cut
        sa.Column("odds", sa.Float, nullable=False),  # American odds
        sa.Column("implied_prob", sa.Float),
        sa.Column("dg_prob", sa.Float),  # DataGolf model probability
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tournament_id", "dg_id", "book", "market", name="uq_golf_odds"),
    )
    op.create_index("idx_golf_odds_tournament", "golf_tournament_odds", ["tournament_id"])

    # --- DFS Projections ---
    op.create_table(
        "golf_dfs_projections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, sa.ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, sa.ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_name", sa.String(200)),
        sa.Column("site", sa.String(30), nullable=False),  # draftkings, fanduel, yahoo
        sa.Column("salary", sa.Integer),
        sa.Column("projected_points", sa.Float),
        sa.Column("projected_ownership", sa.Float),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tournament_id", "dg_id", "site", name="uq_golf_dfs_projection"),
    )


def downgrade() -> None:
    op.drop_table("golf_dfs_projections")
    op.drop_table("golf_tournament_odds")
    op.drop_table("golf_player_stats")
    op.drop_table("golf_rounds")
    op.drop_table("golf_leaderboard")
    op.drop_table("golf_tournament_fields")
    op.drop_table("golf_tournaments")
    op.drop_table("golf_players")
