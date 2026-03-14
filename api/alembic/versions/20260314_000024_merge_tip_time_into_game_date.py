"""Merge tip_time into game_date — store actual scheduled start time.

game_date previously stored midnight ET as a "sports calendar day" proxy,
while tip_time held the real scheduled start. This created timezone confusion
and required COALESCE fallbacks everywhere.

After this migration, game_date holds the actual scheduled start time (UTC).
The tip_time column is dropped.

Revision ID: 20260314_merge_tip_time
Revises: 20260314_fairbet_indexes
Create Date: 2026-03-14
"""

from alembic import op

revision = "20260314_merge_tip_time"
down_revision = "20260314_fairbet_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Populate game_date with actual start time where available
    op.execute(
        "UPDATE sports_games SET game_date = tip_time WHERE tip_time IS NOT NULL"
    )

    # Drop tip_time column and its indexes
    op.drop_index("ix_sports_games_tip_time", table_name="sports_games")
    op.drop_index("idx_games_status_tip_time", table_name="sports_games")
    op.drop_column("sports_games", "tip_time")


def downgrade() -> None:
    # Re-add tip_time column
    op.add_column(
        "sports_games",
        op.Column("tip_time", op.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sports_games_tip_time", "sports_games", ["tip_time"])
    op.create_index("idx_games_status_tip_time", "sports_games", ["status", "tip_time"])

    # Copy game_date back to tip_time (we can't perfectly reverse this)
    op.execute("UPDATE sports_games SET tip_time = game_date")
