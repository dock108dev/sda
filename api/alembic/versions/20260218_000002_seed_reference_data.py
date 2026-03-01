"""Seed reference data from prod snapshot.

Loads 6 leagues, 458 teams (NBA/NHL/NCAAB/MLB + colors + external_codes),
411 team social accounts, and 6 compact mode thresholds from seed_data.sql.

Revision ID: 20260218_seed
Revises: 20260218_baseline
Create Date: 2026-02-18
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "20260218_seed"
down_revision = "20260218_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    seed_sql = Path(__file__).parent / "seed_data.sql"
    statements = seed_sql.read_text().strip().splitlines()

    for stmt in statements:
        stmt = stmt.strip()
        if stmt and stmt.startswith("INSERT"):
            op.execute(stmt)

    # Reset sequences past max IDs so new inserts don't collide
    op.execute("SELECT setval('sports_leagues_id_seq', (SELECT COALESCE(MAX(id), 1) FROM sports_leagues));")
    op.execute("SELECT setval('sports_teams_id_seq', (SELECT COALESCE(MAX(id), 1) FROM sports_teams));")
    op.execute("SELECT setval('team_social_accounts_id_seq', (SELECT COALESCE(MAX(id), 1) FROM team_social_accounts));")
    op.execute("SELECT setval('compact_mode_thresholds_id_seq', (SELECT COALESCE(MAX(id), 1) FROM compact_mode_thresholds));")


def downgrade() -> None:
    op.execute("DELETE FROM compact_mode_thresholds;")
    op.execute("DELETE FROM team_social_accounts;")
    op.execute("DELETE FROM sports_teams;")
    op.execute("DELETE FROM sports_leagues;")
