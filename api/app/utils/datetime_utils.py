"""Datetime helpers for the API layer.

NOTE: Utilities shared with scraper/ (now_utc, today_utc, today_et, to_et_date,
date_to_utc_datetime) are intentionally duplicated because api/ and scraper/
deploy as independent packages. Names must stay aligned across both.

DATE CONVENTION:
All date parameters in the API use Eastern Time (America/New_York).
This represents "game day" as fans understand it - a 10pm ET game
on Jan 22 is a "Jan 22 game", regardless of UTC date.

All datetime fields in responses are UTC (ISO 8601).
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

# Eastern timezone for game date interpretation
EASTERN = ZoneInfo("America/New_York")


def now_utc() -> datetime:
    """Get the current time in UTC, timezone-aware."""
    return datetime.now(UTC)


def today_utc() -> date:
    """Return the current date in UTC timezone."""
    return now_utc().date()


def today_et() -> date:
    """Return the current date in Eastern Time."""
    return datetime.now(EASTERN).date()


def date_to_utc_datetime(day: date) -> datetime:
    """Convert a date to a timezone-aware UTC datetime at midnight."""
    return datetime.combine(day, datetime.min.time()).replace(tzinfo=UTC)


def to_et_date(dt: datetime) -> date:
    """Convert a UTC datetime to its Eastern Time calendar date."""
    return dt.astimezone(ZoneInfo("America/New_York")).date()


def start_of_et_day_utc(d: date) -> datetime:
    """Midnight ET on date *d*, expressed in UTC.  Use as ``>=`` bound."""
    return datetime.combine(d, datetime.min.time(), tzinfo=EASTERN).astimezone(UTC)


def end_of_et_day_utc(d: date) -> datetime:
    """Midnight ET on date *d+1*, expressed in UTC.  Use as ``<`` upper bound."""
    return datetime.combine(
        d + timedelta(days=1), datetime.min.time(), tzinfo=EASTERN,
    ).astimezone(UTC)


def parse_clock_to_seconds(clock: str | None) -> int | None:
    """
    Parse game clock string to seconds remaining.

    Accepts formats:
    - "MM:SS" (e.g., "11:45")
    - "MM:SS.x" (e.g., "5:30.0")

    Returns None if clock is invalid or None.
    """
    if not clock:
        return None
    try:
        parts = clock.replace(".", ":").split(":")
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        return int(float(parts[0]))
    except (ValueError, IndexError):
        return None
