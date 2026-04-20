"""Add golf pool tables.

Revision ID: pool_001
Revises: golf_001
Create Date: 2026-03-19

Pool management tables for golf pick-em pools. Tables are prefixed
with ``golf_pool_`` and reference the golf domain tables for
tournament and player data.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "pool_001"
down_revision = "golf_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Pools ---
    op.create_table(
        "golf_pools",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("club_code", sa.String(100), nullable=False),
        sa.Column("tournament_id", sa.Integer, sa.ForeignKey("golf_tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, default="draft"),  # draft, open, locked, live, final, archived
        sa.Column("rules_json", JSONB),
        sa.Column("entry_open_at", sa.DateTime(timezone=True)),
        sa.Column("entry_deadline", sa.DateTime(timezone=True)),
        sa.Column("scoring_enabled", sa.Boolean, default=False),
        sa.Column("max_entries_per_email", sa.Integer),
        sa.Column("require_upload", sa.Boolean, default=False),
        sa.Column("allow_self_service_entry", sa.Boolean, default=True),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tournament_id", "code", name="uq_golf_pool_tournament_code"),
    )
    op.create_index("idx_golf_pools_tournament", "golf_pools", ["tournament_id"])

    # --- Buckets ---
    op.create_table(
        "golf_pool_buckets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pool_id", sa.Integer, sa.ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bucket_number", sa.Integer, nullable=False),
        sa.Column("label", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("pool_id", "bucket_number", name="uq_golf_pool_bucket"),
    )

    # --- Bucket Players ---
    op.create_table(
        "golf_pool_bucket_players",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("bucket_id", sa.Integer, sa.ForeignKey("golf_pool_buckets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, sa.ForeignKey("golf_players.dg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_name_snapshot", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("bucket_id", "dg_id", name="uq_golf_pool_bucket_player"),
    )

    # --- Entries ---
    op.create_table(
        "golf_pool_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pool_id", sa.Integer, sa.ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(300), nullable=False),
        sa.Column("entry_name", sa.String(200)),
        sa.Column("entry_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), default="submitted"),
        sa.Column("source", sa.String(30), default="self_service"),
        sa.Column("upload_filename", sa.String(500)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("idx_golf_pool_entries_pool_email", "golf_pool_entries", ["pool_id", "email"])

    # --- Entry Picks ---
    op.create_table(
        "golf_pool_entry_picks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entry_id", sa.Integer, sa.ForeignKey("golf_pool_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, nullable=False),
        sa.Column("player_name_snapshot", sa.String(200), nullable=False),
        sa.Column("pick_slot", sa.Integer, nullable=False),
        sa.Column("bucket_number", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("entry_id", "pick_slot", name="uq_golf_pool_entry_pick"),
    )

    # --- Entry Score Players (materialized per-golfer scoring) ---
    op.create_table(
        "golf_pool_entry_score_players",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pool_id", sa.Integer, sa.ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.Integer, sa.ForeignKey("golf_pool_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dg_id", sa.Integer, nullable=False),
        sa.Column("player_name_snapshot", sa.String(200), nullable=False),
        sa.Column("pick_slot", sa.Integer, nullable=False),
        sa.Column("bucket_number", sa.Integer),
        sa.Column("status_snapshot", sa.String(30)),
        sa.Column("position_snapshot", sa.Integer),
        sa.Column("thru_snapshot", sa.Integer),
        sa.Column("r1", sa.Integer),
        sa.Column("r2", sa.Integer),
        sa.Column("r3", sa.Integer),
        sa.Column("r4", sa.Integer),
        sa.Column("total_score_snapshot", sa.Integer),
        sa.Column("made_cut_snapshot", sa.Boolean),
        sa.Column("counts_toward_total", sa.Boolean, nullable=False, default=True),
        sa.Column("is_dropped", sa.Boolean, nullable=False, default=False),
        sa.Column("sort_score", sa.Integer),
        sa.Column("last_scored_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("entry_id", "dg_id", name="uq_golf_pool_entry_score_player"),
    )

    # --- Entry Scores (materialized entry summary) ---
    op.create_table(
        "golf_pool_entry_scores",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pool_id", sa.Integer, sa.ForeignKey("golf_pools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.Integer, sa.ForeignKey("golf_pool_entries.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("aggregate_score", sa.Integer),
        sa.Column("qualified_golfers_count", sa.Integer, nullable=False),
        sa.Column("counted_golfers_count", sa.Integer, nullable=False),
        sa.Column("qualification_status", sa.String(30), nullable=False),
        sa.Column("is_complete", sa.Boolean, nullable=False, default=False),
        sa.Column("rank", sa.Integer),
        sa.Column("is_tied", sa.Boolean, nullable=False, default=False),
        sa.Column("scoring_json", JSONB),
        sa.Column("last_scored_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("idx_golf_pool_entry_scores_pool_rank", "golf_pool_entry_scores", ["pool_id", "rank"])

    # --- Score Runs (audit trail) ---
    op.create_table(
        "golf_pool_score_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pool_id", sa.Integer, sa.ForeignKey("golf_pools.id", ondelete="CASCADE")),
        sa.Column("tournament_id", sa.Integer, sa.ForeignKey("golf_tournaments.id", ondelete="CASCADE")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("entries_scored", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("golf_pool_score_runs")
    op.drop_table("golf_pool_entry_scores")
    op.drop_table("golf_pool_entry_score_players")
    op.drop_table("golf_pool_entry_picks")
    op.drop_table("golf_pool_entries")
    op.drop_table("golf_pool_bucket_players")
    op.drop_table("golf_pool_buckets")
    op.drop_table("golf_pools")
