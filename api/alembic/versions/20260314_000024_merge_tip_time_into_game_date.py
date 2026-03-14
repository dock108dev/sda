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
import sqlalchemy as sa

revision = "20260314_merge_tip_time"
down_revision = "20260314_fairbet_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The unique constraint includes game_date, so copying tip_time into
    # game_date can create collisions when two rows exist for the same
    # matchup — one with game_date already set to the real start time and
    # another with a midnight placeholder + tip_time.
    #
    # Strategy:
    #   1. Drop the unique constraint so the UPDATE can proceed.
    #   2. Copy tip_time → game_date.
    #   3. Delete duplicates, keeping the row with the most recent update.
    #   4. Recreate the constraint.

    # 1. Drop unique constraint
    op.drop_constraint("uq_game_identity", "sports_games", type_="unique")

    # 2. Populate game_date with actual start time where available
    op.execute(
        "UPDATE sports_games SET game_date = tip_time WHERE tip_time IS NOT NULL"
    )

    # 3. Remove duplicates — keep the row with the latest updated_at
    #    (or highest id as tiebreaker).
    op.execute(sa.text("""
        DELETE FROM sports_games
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY league_id, season, game_date,
                                        home_team_id, away_team_id
                           ORDER BY updated_at DESC NULLS LAST, id DESC
                       ) AS rn
                FROM sports_games
            ) ranked
            WHERE rn > 1
        )
    """))

    # 4. Recreate unique constraint
    op.create_unique_constraint(
        "uq_game_identity",
        "sports_games",
        ["league_id", "season", "game_date", "home_team_id", "away_team_id"],
    )

    # Drop tip_time column and its indexes
    op.drop_index("ix_sports_games_tip_time", table_name="sports_games")
    op.drop_index("idx_games_status_tip_time", table_name="sports_games")
    op.drop_column("sports_games", "tip_time")


def downgrade() -> None:
    # Re-add tip_time column
    op.add_column(
        "sports_games",
        sa.Column("tip_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sports_games_tip_time", "sports_games", ["tip_time"])
    op.create_index("idx_games_status_tip_time", "sports_games", ["status", "tip_time"])

    # Copy game_date back to tip_time (we can't perfectly reverse this)
    op.execute("UPDATE sports_games SET tip_time = game_date")
