"""Stat normalization for team and player boxscores.

Resolves alias differences across data sources (Basketball Reference,
NBA API, CBB API) into canonical keys with display labels, so clients
don't need to maintain alias tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class StatDefinition:
    """Definition of a normalized stat."""

    canonical_key: str
    display_label: str
    group: str  # e.g., "scoring", "rebounds", "playmaking", "defense", "shooting"
    format_type: str = "int"  # "int", "float", "pct", "str"
    aliases: tuple[str, ...] = field(default_factory=tuple)


# Shared basketball stat definitions (NBA + NCAAB)
_BASKETBALL_STATS: tuple[StatDefinition, ...] = (
    # Scoring
    StatDefinition("points", "PTS", "scoring", "int", ("pts", "PTS")),
    StatDefinition("field_goals_made", "FGM", "shooting", "int", ("fg", "fgm", "FGM", "field_goals.made")),
    StatDefinition("field_goals_attempted", "FGA", "shooting", "int", ("fga", "FGA", "field_goals.attempted")),
    StatDefinition("field_goal_pct", "FG%", "shooting", "pct", ("fg_pct", "fg%", "FG%", "field_goals.percentage")),
    StatDefinition("three_pointers_made", "3PM", "shooting", "int", ("fg3", "tp", "three_pointers_made", "3pm", "threes", "three_pointers.made")),
    StatDefinition("three_pointers_attempted", "3PA", "shooting", "int", ("fg3a", "tpa", "three_pointers_attempted", "3pa", "three_pointers.attempted")),
    StatDefinition("three_point_pct", "3P%", "shooting", "pct", ("fg3_pct", "tp_pct", "three_point_pct", "3p%", "three_pointers.percentage")),
    StatDefinition("free_throws_made", "FTM", "shooting", "int", ("ft", "ftm", "FTM", "free_throws.made")),
    StatDefinition("free_throws_attempted", "FTA", "shooting", "int", ("fta", "FTA", "free_throws.attempted")),
    StatDefinition("free_throw_pct", "FT%", "shooting", "pct", ("ft_pct", "ft%", "FT%", "free_throws.percentage")),
    # Rebounds
    StatDefinition("rebounds", "REB", "rebounds", "int", ("trb", "reb", "totalRebounds", "total_rebounds", "rebounds.total")),
    StatDefinition("offensive_rebounds", "OREB", "rebounds", "int", ("orb", "oreb", "offensive_rebounds", "rebounds.offensive")),
    StatDefinition("defensive_rebounds", "DREB", "rebounds", "int", ("drb", "dreb", "defensive_rebounds", "rebounds.defensive")),
    # Playmaking
    StatDefinition("assists", "AST", "playmaking", "int", ("ast", "AST")),
    StatDefinition("turnovers", "TO", "playmaking", "int", ("tov", "to", "turnovers")),
    # Defense
    StatDefinition("steals", "STL", "defense", "int", ("stl", "STL")),
    StatDefinition("blocks", "BLK", "defense", "int", ("blk", "BLK")),
    StatDefinition("personal_fouls", "PF", "defense", "int", ("pf", "PF", "fouls.personal")),
)

NBA_STATS = _BASKETBALL_STATS
NCAAB_STATS = _BASKETBALL_STATS

MLB_STATS: tuple[StatDefinition, ...] = (
    # Core line score
    # Runs are stored as top-level "points" by _build_team_stats, and also
    # nested under batting.runs in raw_stats.
    StatDefinition("runs", "R", "scoring", "int", ("points", "batting.runs")),
    StatDefinition("hits", "H", "scoring", "int", ("hits", "batting.hits")),
    StatDefinition("errors", "E", "scoring", "int", ("fielding.errors",)),
    StatDefinition("left_on_base", "LOB", "scoring", "int", ("batting.leftOnBase", "leftOnBase", "lob")),
    # Batting
    StatDefinition("at_bats", "AB", "batting", "int", ("batting.atBats", "atBats", "ab")),
    StatDefinition("home_runs", "HR", "batting", "int", ("batting.homeRuns", "homeRuns", "hr")),
    StatDefinition("rbi", "RBI", "batting", "int", ("batting.rbi", "rbi")),
    StatDefinition("base_on_balls", "BB", "batting", "int", ("batting.baseOnBalls", "baseOnBalls", "bb")),
    StatDefinition("strike_outs", "SO", "batting", "int", ("batting.strikeOuts", "strikeOuts", "so")),
    StatDefinition("stolen_bases", "SB", "batting", "int", ("batting.stolenBases", "stolenBases", "sb")),
    StatDefinition("avg", "AVG", "batting", "str", ("batting.avg",)),
    StatDefinition("obp", "OBP", "batting", "str", ("batting.obp",)),
    StatDefinition("slg", "SLG", "batting", "str", ("batting.slg",)),
    # Pitching
    StatDefinition("era", "ERA", "pitching", "str", ("pitching.era",)),
)

# Registry by league
_LEAGUE_STATS: dict[str, tuple[StatDefinition, ...]] = {
    "NBA": NBA_STATS,
    "NCAAB": NCAAB_STATS,
    "MLB": MLB_STATS,
}


def _resolve_value(raw_stats: dict[str, Any], aliases: tuple[str, ...], canonical_key: str) -> Any | None:
    """Try canonical key first, then each alias, handling nested dicts."""
    # Try canonical key directly
    val = raw_stats.get(canonical_key)
    if val is not None:
        # If it's a nested dict, extract .total
        if isinstance(val, dict):
            total = val.get("total")
            if total is not None:
                return total
        else:
            return val

    for alias in aliases:
        # Handle dot-notation for nested dicts (e.g., "rebounds.total")
        if "." in alias:
            parts = alias.split(".", 1)
            nested = raw_stats.get(parts[0])
            if isinstance(nested, dict):
                inner = nested.get(parts[1])
                if inner is not None:
                    return inner
        else:
            alias_val = raw_stats.get(alias)
            if alias_val is not None:
                if isinstance(alias_val, dict):
                    total = alias_val.get("total")
                    if total is not None:
                        return total
                else:
                    return alias_val

    return None


def normalize_stats(
    raw_stats: dict[str, Any],
    league_code: str,
) -> list[dict[str, Any]]:
    """Normalize raw JSONB stats into a canonical stat array.

    Args:
        raw_stats: Raw stats dict from team/player boxscore.
        league_code: League code (e.g., "NBA", "NCAAB").

    Returns:
        List of normalized stat dicts with keys:
        key, displayLabel, group, value, formatType.
    """
    if not raw_stats:
        return []

    stat_defs = _LEAGUE_STATS.get(league_code.upper(), _BASKETBALL_STATS)
    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for stat_def in stat_defs:
        if stat_def.canonical_key in seen_keys:
            continue

        value = _resolve_value(raw_stats, stat_def.aliases, stat_def.canonical_key)
        if value is None:
            continue

        # Coerce to the right type
        if stat_def.format_type == "int":
            try:
                value = int(value)
            except (ValueError, TypeError):
                continue
        elif stat_def.format_type == "float" or stat_def.format_type == "pct":
            try:
                value = round(float(value), 3)
            except (ValueError, TypeError):
                continue

        seen_keys.add(stat_def.canonical_key)
        result.append({
            "key": stat_def.canonical_key,
            "displayLabel": stat_def.display_label,
            "group": stat_def.group,
            "value": value,
            "formatType": stat_def.format_type,
        })

    return result
