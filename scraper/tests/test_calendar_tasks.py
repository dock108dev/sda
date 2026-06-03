from __future__ import annotations

from datetime import date, timedelta

from sports_scraper.jobs.calendar_tasks import (
    _CALENDAR_LOOKAHEAD_DAYS,
    _calendar_days,
    _nba_team_identity,
)


def test_calendar_days_include_named_lookahead_end_day() -> None:
    today = date(2026, 6, 3)
    days = _calendar_days(today)

    assert days[0] == today
    assert days[-1] == today + timedelta(days=_CALENDAR_LOOKAHEAD_DAYS)
    assert len(days) == _CALENDAR_LOOKAHEAD_DAYS + 1


def test_nba_calendar_team_identity_uses_canonical_names_and_abbreviations() -> None:
    home = _nba_team_identity("SAS")
    away = _nba_team_identity("NYK")

    assert home.name == "San Antonio Spurs"
    assert home.short_name == "San Antonio Spurs"
    assert home.abbreviation == "SAS"
    assert away.name == "New York Knicks"
    assert away.short_name == "New York Knicks"
    assert away.abbreviation == "NYK"
