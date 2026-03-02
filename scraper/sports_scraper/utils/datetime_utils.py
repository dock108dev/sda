"""
Low-level timezone and timestamp utilities.

NOTE: Some utilities (now_utc, today_utc, date_to_utc_datetime) are intentionally
duplicated in api/app/utils/datetime_utils.py because api/ and scraper/ deploy as
independent packages.

This module provides helpers for timezone-aware UTC datetime operations,
conversion, and window generation. It is domain-agnostic and should NOT
contain sports-specific logic (e.g., season boundaries), which belongs in
date_utils.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SPORTS_DAY_BOUNDARY_HOUR_ET = 4


def sports_today_et() -> date:
    """Return the current sports calendar date in Eastern Time.

    In sports, action runs until ~4 AM ET. A timestamp at 2 AM ET on Feb 18
    belongs to the Feb 17 sports day. This shifts the day boundary from
    midnight to 4 AM ET.
    """
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.hour < SPORTS_DAY_BOUNDARY_HOUR_ET:
        return (now_et - timedelta(days=1)).date()
    return now_et.date()


def now_utc() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def today_utc() -> date:
    """Return the current date in UTC timezone."""
    return now_utc().date()


def today_et() -> date:
    """Return the current date in US Eastern Time (sports calendar day).

    US sports schedule on Eastern Time. A 10 PM ET game on Feb 5 is a
    "Feb 5 game" even though it's Feb 6 in UTC. Use this instead of
    today_utc() when determining sports calendar dates.
    """
    return datetime.now(ZoneInfo("America/New_York")).date()


def date_to_utc_datetime(day: date) -> datetime:
    """Convert a date to a timezone-aware UTC datetime at midnight."""
    return datetime.combine(day, datetime.min.time()).replace(tzinfo=UTC)


def date_window_for_matching(day: date, days_before: int = 1, days_after: int = 1) -> tuple[datetime, datetime]:
    """Get a datetime window for matching games by date.

    Useful when games are stored at midnight but odds use actual tipoff times.

    Args:
        day: Target date
        days_before: Days before to include in window
        days_after: Days after to include in window

    Returns:
        Tuple of (window_start, window_end) in UTC
    """
    start_day = day - timedelta(days=days_before)
    end_day = day + timedelta(days=days_after)
    return start_of_et_day_utc(start_day), end_of_et_day_utc(end_day)


def start_of_et_day_utc(d: date) -> datetime:
    """Midnight ET on date *d*, expressed in UTC. Use as ``>=`` bound."""
    return datetime.combine(d, datetime.min.time(), tzinfo=ET).astimezone(UTC)


def end_of_et_day_utc(d: date) -> datetime:
    """Midnight ET on date *d+1*, expressed in UTC. Use as ``<`` (exclusive) upper bound."""
    return datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=ET).astimezone(UTC)


def eastern_date_range_to_utc_iso(
    start_date: date, end_date: date
) -> tuple[str, str]:
    """Convert Eastern Time date range to UTC ISO 8601 strings for API calls.

    User-submitted dates are in Eastern Time. This function converts them to UTC
    for APIs that require ISO 8601 timestamps. America/New_York automatically
    handles both EST (UTC-5) and EDT (UTC-4) depending on the time of year.

    The end date is treated as inclusive - the returned end timestamp is the
    start of the day AFTER end_date to include all games on that day.

    Args:
        start_date: Start date (inclusive) in Eastern Time
        end_date: End date (inclusive) in Eastern Time

    Returns:
        Tuple of (start_utc_iso, end_utc_iso) formatted as "YYYY-MM-DDTHH:MM:SSZ"
    """
    eastern = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    # Start of start_date in Eastern Time, converted to UTC
    start_eastern = datetime.combine(start_date, datetime.min.time(), tzinfo=eastern)
    start_utc = start_eastern.astimezone(utc)

    # Start of day AFTER end_date in Eastern Time (to include full end_date)
    end_eastern = datetime.combine(
        end_date + timedelta(days=1), datetime.min.time(), tzinfo=eastern
    )
    end_utc = end_eastern.astimezone(utc)

    return (
        start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

