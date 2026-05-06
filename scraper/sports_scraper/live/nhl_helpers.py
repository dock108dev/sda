"""Helper functions for NHL live feed processing.

Utility functions for parsing API responses and building domain objects.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..models import TeamIdentity
from ..normalization import normalize_team_name
from ..utils.datetime_utils import now_utc


def parse_toi_to_minutes(toi: str) -> float | None:
    """Parse time on ice string (e.g., '12:34') to decimal minutes (12.57)."""
    if not toi:
        return None
    try:
        parts = toi.split(":")
        if len(parts) == 2:
            mins = int(parts[0])
            secs = int(parts[1])
            return round(mins + secs / 60, 2)
    except (ValueError, IndexError):
        # Invalid format, return None below
        pass
    return None


def parse_save_shots(save_shots: str) -> tuple[int | None, int | None]:
    """Parse saveShotsAgainst string (e.g., '25/27') to (saves, shots_against)."""
    if not save_shots:
        return None, None
    try:
        parts = save_shots.split("/")
        if len(parts) == 2:
            saves = int(parts[0])
            shots_against = int(parts[1])
            return saves, shots_against
    except (ValueError, IndexError):
        # Invalid format, return (None, None) below
        pass
    return None, None


def build_team_identity_from_api(team_data: dict) -> TeamIdentity:
    """Build TeamIdentity from the NHL API team data."""
    abbr = team_data.get("abbrev", "")
    # Get full name from commonName or placeName
    common_name = team_data.get("commonName", {}).get("default", "")
    place_name = team_data.get("placeName", {}).get("default", "")

    # Build full name: "Place Name Common Name" (e.g., "Tampa Bay Lightning")
    full_name = f"{place_name} {common_name}".strip()

    # Normalize through our team name system
    canonical_name, normalized_abbr = normalize_team_name("NHL", full_name)

    return TeamIdentity(
        league_code="NHL",
        name=canonical_name or full_name,
        short_name=common_name or canonical_name,
        abbreviation=normalized_abbr or abbr,
        external_ref=abbr,
    )


def map_nhl_game_state(state: str, schedule_state: str | None = None) -> str:
    """Map NHL gameState (+ optional gameScheduleState) to normalized status.

    NHL surfaces postponements and cancellations through gameScheduleState
    (PPD/SUSP/CNCL) while gameState stays at FUT/PRE. Without this signal,
    a postponed game looks indistinguishable from a still-scheduled one and
    gets stuck on 0-0 forever once its date passes.
    """
    if state in ("OFF", "FINAL"):
        return "final"
    if state in ("LIVE", "CRIT"):
        return "live"
    if schedule_state:
        ss = schedule_state.upper()
        if ss in ("PPD", "SUSP"):
            return "postponed"
        if ss == "CNCL":
            return "cancelled"
    if state in ("FUT", "PRE"):
        return "scheduled"
    return "scheduled"


def parse_datetime(value: str | None) -> datetime:
    """Parse ISO datetime string to UTC datetime."""
    if not value:
        return now_utc()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return now_utc()


def one_day() -> timedelta:
    """Return timedelta of one day."""
    return timedelta(days=1)
