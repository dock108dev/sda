"""Seed social handles for all 30 MLB teams.

Inserts X (Twitter) handles for each MLB franchise into
team_social_accounts. Uses ON CONFLICT upsert so it is safe
to re-run.

Revision ID: 20260301_mlb_social
Revises: 20260301_mlb_teams
Create Date: 2026-03-01
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "20260301_mlb_social"
down_revision = "20260301_mlb_teams"
branch_labels = None
depends_on = None

# team name (must match sports_teams.name) -> X handle (without @)
MLB_SOCIAL_HANDLES: dict[str, str] = {
    "Arizona Diamondbacks": "Dbacks",
    "Atlanta Braves": "Braves",
    "Baltimore Orioles": "Orioles",
    "Boston Red Sox": "RedSox",
    "Chicago Cubs": "Cubs",
    "Chicago White Sox": "whitesox",
    "Cincinnati Reds": "Reds",
    "Cleveland Guardians": "CleGuardians",
    "Colorado Rockies": "Rockies",
    "Detroit Tigers": "tigers",
    "Houston Astros": "astros",
    "Kansas City Royals": "Royals",
    "Los Angeles Angels": "Angels",
    "Los Angeles Dodgers": "Dodgers",
    "Miami Marlins": "Marlins",
    "Milwaukee Brewers": "Brewers",
    "Minnesota Twins": "Twins",
    "New York Mets": "Mets",
    "New York Yankees": "Yankees",
    "Oakland Athletics": "Athletics",
    "Philadelphia Phillies": "Phillies",
    "Pittsburgh Pirates": "Pirates",
    "San Diego Padres": "Padres",
    "San Francisco Giants": "SFGiants",
    "Seattle Mariners": "Mariners",
    "St. Louis Cardinals": "Cardinals",
    "Tampa Bay Rays": "RaysBaseball",
    "Texas Rangers": "Rangers",
    "Toronto Blue Jays": "BlueJays",
    "Washington Nationals": "Nationals",
}


def upgrade() -> None:
    conn = op.get_bind()

    upsert_sql = text("""
        INSERT INTO team_social_accounts (team_id, league_id, platform, handle, is_active)
        SELECT t.id, t.league_id, 'x', :handle, true
        FROM sports_teams t
        JOIN sports_leagues l ON t.league_id = l.id
        WHERE l.code = 'MLB'
          AND t.name = :team_name
        ON CONFLICT (team_id, platform) DO UPDATE
          SET handle = EXCLUDED.handle
    """)

    updated = 0
    for team_name, handle in MLB_SOCIAL_HANDLES.items():
        result = conn.execute(upsert_sql, {"team_name": team_name, "handle": handle})
        if result.rowcount:
            updated += 1
        else:
            print(f"  WARNING: team not found: {team_name}")

    print(f"Upserted {updated}/{len(MLB_SOCIAL_HANDLES)} MLB social handles")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        DELETE FROM team_social_accounts
        WHERE league_id = (SELECT id FROM sports_leagues WHERE code = 'MLB')
    """))
