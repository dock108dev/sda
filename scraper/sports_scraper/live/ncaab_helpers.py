"""Helper functions for NCAAB live feed processing.

Utility functions for parsing API responses and building domain objects.
"""

from __future__ import annotations

from ..models import TeamIdentity
from ..normalization import normalize_team_name
from ..utils.parsing import parse_int


def build_team_identity(name: str, team_id: int) -> TeamIdentity:
    """Build TeamIdentity for an NCAAB team.

    Looks up the abbreviation from the NCAAB SSOT dictionary via
    normalize_team_name. Falls back to None if the team is not recognized
    (the persistence layer will derive a fallback abbreviation).
    """
    canonical, abbreviation = normalize_team_name("NCAAB", name)
    return TeamIdentity(
        league_code="NCAAB",
        name=canonical,
        short_name=canonical,
        abbreviation=abbreviation,
        external_ref=str(team_id),
    )


def extract_points(value: int | dict | None) -> int:
    """Extract points from API response which may be int or dict.

    The CBB API sometimes returns points as an integer, and sometimes as a dict:
    {"total": 89, "byPeriod": [...], "offTurnovers": 17}

    This handles both formats.
    """
    if value is None:
        return 0
    if isinstance(value, dict):
        # Nested format: {"total": 89, ...}
        return parse_int(value.get("total")) or 0
    # Flat format: just an integer
    return parse_int(value) or 0


def parse_minutes(value: str | int | float | None) -> float | None:
    """Parse minutes value which may be 'MM:SS' or numeric."""
    if value is None:
        return None

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        # Try parsing "MM:SS" format
        if ":" in value:
            try:
                parts = value.split(":")
                if len(parts) == 2:
                    mins = int(parts[0])
                    secs = int(parts[1])
                    return round(mins + secs / 60, 2)
            except (ValueError, IndexError):
                # If "MM:SS" parsing fails, fall through to numeric parsing
                pass

        # Try parsing as plain number
        try:
            return float(value)
        except ValueError:
            # If numeric parsing fails, return None below
            pass

    return None


def extract_total(value: int | dict | None) -> int | None:
    """Extract an int from a value that may be int or ``{"total": int, ...}``.

    Used for player stats where the CBB API returns either flat integers or
    nested objects.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return parse_int(value.get("total"))
    return parse_int(value)


def extract_shooting_stat(
    ps: dict,
    flat_key: str,
    nested_key: str,
    sub_key: str,
) -> int | None:
    """Extract a shooting stat that may be flat or nested.

    Tries ``ps[flat_key]`` first (flat format), then falls back to
    ``ps[nested_key][sub_key]`` (nested format).
    """
    flat_val = extract_total(ps.get(flat_key))
    if flat_val is not None:
        return flat_val
    nested = ps.get(nested_key)
    if isinstance(nested, dict):
        return extract_total(nested.get(sub_key))
    return None
