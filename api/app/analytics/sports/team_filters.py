"""Canonical team-abbreviation filters per sport.

Single source of truth for filtering ``SportsTeam`` rows down to the
real-league franchises, excluding minor-league, all-star, exhibition,
and cross-sport rows that may have been seeded under the same league.

NCAAB is intentionally absent: D-I has 350+ schools and no canonical
short-list, so callers must rely on ``league_id`` alone for that sport.
Callers should treat a missing entry as "skip the canonical filter".
"""

from __future__ import annotations

from app.analytics.sports.mlb.constants import MLB_TEAM_ABBRS
from app.analytics.sports.nba.constants import NBA_TEAM_ABBRS
from app.analytics.sports.nhl.constants import NHL_TEAM_ABBRS

CANONICAL_TEAM_ABBRS: dict[str, frozenset[str]] = {
    "mlb": MLB_TEAM_ABBRS,
    "nba": NBA_TEAM_ABBRS,
    "nhl": NHL_TEAM_ABBRS,
}


def get_canonical_abbrs(sport: str) -> frozenset[str] | None:
    """Return the canonical abbreviation set for *sport*, or None if absent."""
    return CANONICAL_TEAM_ABBRS.get(sport.lower())
