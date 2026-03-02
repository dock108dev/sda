"""Seed 30 MLB teams into sports_teams.

Adds all 30 MLB franchises (league_id=5) with official colors,
abbreviations, and short names matching the normalization dict.

Revision ID: 20260301_mlb_teams
Revises: 20260227_celery_task_id
Create Date: 2026-03-01
"""

from __future__ import annotations

from alembic import op

revision = "20260301_mlb_teams"
down_revision = "20260227_celery_task_id"
branch_labels = None
depends_on = None

# (name, short_name, abbreviation, color_light_hex, color_dark_hex)
MLB_TEAMS = [
    ("Arizona Diamondbacks", "Diamondbacks", "ARI", "#A71930", "#E3D4AD"),
    ("Atlanta Braves", "Braves", "ATL", "#CE1141", "#13274F"),
    ("Baltimore Orioles", "Orioles", "BAL", "#DF4601", "#000000"),
    ("Boston Red Sox", "Red Sox", "BOS", "#BD3039", "#0C2340"),
    ("Chicago Cubs", "Cubs", "CHC", "#0E3386", "#CC3433"),
    ("Chicago White Sox", "White Sox", "CWS", "#27251F", "#C4CED4"),
    ("Cincinnati Reds", "Reds", "CIN", "#C6011F", "#000000"),
    ("Cleveland Guardians", "Guardians", "CLE", "#00385D", "#E31937"),
    ("Colorado Rockies", "Rockies", "COL", "#333366", "#C4CED4"),
    ("Detroit Tigers", "Tigers", "DET", "#0C2340", "#FA4616"),
    ("Houston Astros", "Astros", "HOU", "#002D62", "#EB6E1F"),
    ("Kansas City Royals", "Royals", "KC", "#004687", "#BD9B60"),
    ("Los Angeles Angels", "Angels", "LAA", "#BA0021", "#003263"),
    ("Los Angeles Dodgers", "Dodgers", "LAD", "#005A9C", "#EF3E42"),
    ("Miami Marlins", "Marlins", "MIA", "#00A3E0", "#EF3340"),
    ("Milwaukee Brewers", "Brewers", "MIL", "#12284B", "#FFC52F"),
    ("Minnesota Twins", "Twins", "MIN", "#002B5C", "#D31145"),
    ("New York Mets", "Mets", "NYM", "#002D72", "#FF5910"),
    ("New York Yankees", "Yankees", "NYY", "#003087", "#E4002B"),
    ("Oakland Athletics", "Athletics", "OAK", "#003831", "#EFB21E"),
    ("Philadelphia Phillies", "Phillies", "PHI", "#E81828", "#002D72"),
    ("Pittsburgh Pirates", "Pirates", "PIT", "#27251F", "#FDB827"),
    ("San Diego Padres", "Padres", "SD", "#2F241D", "#FFC425"),
    ("San Francisco Giants", "Giants", "SF", "#FD5A1E", "#27251F"),
    ("Seattle Mariners", "Mariners", "SEA", "#0C2C56", "#005C5C"),
    ("St. Louis Cardinals", "Cardinals", "STL", "#C41E3A", "#0C2340"),
    ("Tampa Bay Rays", "Rays", "TB", "#092C5C", "#8FBCE6"),
    ("Texas Rangers", "Rangers", "TEX", "#003278", "#C0111F"),
    ("Toronto Blue Jays", "Blue Jays", "TOR", "#134A8E", "#1D2D5C"),
    ("Washington Nationals", "Nationals", "WSH", "#AB0003", "#14225A"),
]


def upgrade() -> None:
    for name, short_name, abbr, color_light, color_dark in MLB_TEAMS:
        # Escape single quotes in team names (e.g. none currently, but safe)
        esc_name = name.replace("'", "''")
        esc_short = short_name.replace("'", "''")
        op.execute(
            f"INSERT INTO sports_teams "
            f"(id, league_id, external_ref, name, short_name, abbreviation, "
            f"location, external_codes, created_at, updated_at, x_handle, "
            f"color_light_hex, color_dark_hex) "
            f"VALUES (nextval('sports_teams_id_seq'), 5, NULL, '{esc_name}', "
            f"'{esc_short}', '{abbr}', NULL, '{{}}', now(), now(), NULL, "
            f"'{color_light}', '{color_dark}') "
            f"ON CONFLICT (league_id, name) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DELETE FROM sports_teams WHERE league_id = 5")
