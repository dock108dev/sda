"""Comprehensive tests for utils modules."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


# ============================================================================
# Tests for utils/parsing.py
# ============================================================================

from sports_scraper.utils.parsing import parse_float, parse_int


class TestParseInt:
    """Tests for parse_int function."""

    def test_parse_int_from_int(self):
        assert parse_int(42) == 42
        assert parse_int(0) == 0
        assert parse_int(-5) == -5

    def test_parse_int_from_string(self):
        assert parse_int("42") == 42
        assert parse_int("0") == 0
        assert parse_int("-5") == -5

    def test_parse_int_from_float(self):
        assert parse_int(42.7) == 42
        assert parse_int(42.2) == 42
        assert parse_int(-5.9) == -5

    def test_parse_int_from_float_string(self):
        assert parse_int("42.7") == 42
        assert parse_int("42.0") == 42

    def test_parse_int_returns_none_for_none(self):
        assert parse_int(None) is None

    def test_parse_int_returns_none_for_empty_string(self):
        assert parse_int("") is None

    def test_parse_int_returns_none_for_dash(self):
        assert parse_int("-") is None

    def test_parse_int_returns_none_for_invalid(self):
        assert parse_int("abc") is None
        assert parse_int({}) is None
        assert parse_int([]) is None


class TestParseFloat:
    """Tests for parse_float function."""

    def test_parse_float_from_string(self):
        assert parse_float("42.5") == 42.5
        assert parse_float("0.0") == 0.0
        assert parse_float("-5.5") == -5.5

    def test_parse_float_from_int_string(self):
        assert parse_float("42") == 42.0

    def test_parse_float_returns_none_for_none(self):
        assert parse_float(None) is None

    def test_parse_float_returns_none_for_empty_string(self):
        assert parse_float("") is None

    def test_parse_float_returns_none_for_dash(self):
        assert parse_float("-") is None

    def test_parse_float_returns_none_for_invalid(self):
        assert parse_float("abc") is None

    def test_parse_float_handles_time_format(self):
        # 32:45 = 32 minutes + 45/60 minutes
        result = parse_float("32:45")
        assert result == pytest.approx(32.75, rel=0.01)

    def test_parse_float_handles_simple_time(self):
        result = parse_float("10:30")
        assert result == pytest.approx(10.5, rel=0.01)


# ============================================================================
# Tests for utils/date_utils.py
# ============================================================================

from sports_scraper.utils.date_utils import season_from_date


class TestSeasonFromDate:
    """Tests for season_from_date function."""

    def test_nba_season_october(self):
        # October 2024 = 2024 season (season starts)
        assert season_from_date(date(2024, 10, 15), "NBA") == 2024

    def test_nba_season_january(self):
        # January 2025 = 2024 season (mid-season)
        assert season_from_date(date(2025, 1, 15), "NBA") == 2024

    def test_nba_season_june(self):
        # June 2025 = 2024 season (playoffs/finals)
        assert season_from_date(date(2025, 6, 15), "NBA") == 2024

    def test_nhl_season_october(self):
        # October 2024 = 2024 season
        assert season_from_date(date(2024, 10, 15), "NHL") == 2024

    def test_nhl_season_february(self):
        # February 2025 = 2024 season
        assert season_from_date(date(2025, 2, 15), "NHL") == 2024

    def test_nfl_season_september(self):
        # September 2024 = 2024 season
        assert season_from_date(date(2024, 9, 15), "NFL") == 2024

    def test_nfl_season_january(self):
        # January 2025 = 2024 season (playoffs)
        assert season_from_date(date(2025, 1, 15), "NFL") == 2024

    def test_nfl_season_july(self):
        # July 2024 = 2023 season (offseason)
        assert season_from_date(date(2024, 7, 15), "NFL") == 2023

    def test_mlb_season_march(self):
        # March 2024 = 2024 season (spring training/start)
        assert season_from_date(date(2024, 3, 15), "MLB") == 2024

    def test_mlb_season_october(self):
        # October 2024 = 2024 season (playoffs)
        assert season_from_date(date(2024, 10, 15), "MLB") == 2024

    def test_mlb_season_january(self):
        # January 2024 = 2023 season (offseason)
        assert season_from_date(date(2024, 1, 15), "MLB") == 2023

    def test_ncaab_season_november(self):
        # November 2024 = 2024 season
        assert season_from_date(date(2024, 11, 15), "NCAAB") == 2024

    def test_ncaab_season_march(self):
        # March 2025 = 2024 season (March Madness)
        assert season_from_date(date(2025, 3, 15), "NCAAB") == 2024

    def test_ncaaf_season_november(self):
        # November 2024 = 2024 season
        assert season_from_date(date(2024, 11, 15), "NCAAF") == 2024

    def test_unknown_league_default(self):
        # Unknown league defaults to July cutoff
        assert season_from_date(date(2024, 7, 15), "UNKNOWN") == 2024
        assert season_from_date(date(2024, 6, 15), "UNKNOWN") == 2023


# ============================================================================
# Tests for utils/datetime_utils.py
# ============================================================================

from sports_scraper.utils.datetime_utils import (
    date_to_utc_datetime,
    date_window_for_matching,
    now_utc,
    today_utc,
)


class TestNowUtc:
    """Tests for now_utc function."""

    def test_now_utc_returns_datetime(self):
        result = now_utc()
        assert isinstance(result, datetime)

    def test_now_utc_is_timezone_aware(self):
        result = now_utc()
        assert result.tzinfo is not None
        assert result.tzinfo == UTC

    def test_now_utc_is_recent(self):
        before = datetime.now(UTC)
        result = now_utc()
        after = datetime.now(UTC)
        assert before <= result <= after


class TestTodayUtc:
    """Tests for today_utc function."""

    def test_today_utc_returns_date(self):
        result = today_utc()
        assert isinstance(result, date)

    def test_today_utc_matches_now(self):
        result = today_utc()
        expected = datetime.now(UTC).date()
        assert result == expected


class TestDateToUtcDatetime:
    """Tests for date_to_utc_datetime function."""

    def test_date_to_utc_datetime_returns_datetime(self):
        result = date_to_utc_datetime(date(2024, 1, 15))
        assert isinstance(result, datetime)

    def test_date_to_utc_datetime_is_midnight(self):
        result = date_to_utc_datetime(date(2024, 1, 15))
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0

    def test_date_to_utc_datetime_is_timezone_aware(self):
        result = date_to_utc_datetime(date(2024, 1, 15))
        assert result.tzinfo == UTC


class TestDateWindowForMatching:
    """Tests for date_window_for_matching function."""

    def test_date_window_default_range(self):
        start, end = date_window_for_matching(date(2024, 1, 15))
        # Default is 1 day before and 1 day after.
        # start = midnight ET Jan 14 = 05:00 UTC Jan 14 (EST)
        # end   = midnight ET Jan 17 = 05:00 UTC Jan 17 (EST, exclusive upper)
        assert start == datetime(2024, 1, 14, 5, 0, tzinfo=UTC)
        assert end == datetime(2024, 1, 17, 5, 0, tzinfo=UTC)

    def test_date_window_custom_range(self):
        start, end = date_window_for_matching(date(2024, 1, 15), days_before=3, days_after=2)
        # start = midnight ET Jan 12 = 05:00 UTC Jan 12
        # end   = midnight ET Jan 18 = 05:00 UTC Jan 18
        assert start == datetime(2024, 1, 12, 5, 0, tzinfo=UTC)
        assert end == datetime(2024, 1, 18, 5, 0, tzinfo=UTC)

    def test_date_window_zero_range(self):
        start, end = date_window_for_matching(date(2024, 1, 15), days_before=0, days_after=0)
        # start = midnight ET Jan 15 = 05:00 UTC Jan 15
        # end   = midnight ET Jan 16 = 05:00 UTC Jan 16
        assert start == datetime(2024, 1, 15, 5, 0, tzinfo=UTC)
        assert end == datetime(2024, 1, 16, 5, 0, tzinfo=UTC)


# ============================================================================
# Tests for utils/cache.py
# ============================================================================

from sports_scraper.utils.cache import MIN_SCOREBOARD_SIZE_BYTES, APICache, HTMLCache


class TestHTMLCache:
    """Tests for HTMLCache class."""

    def test_init(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        assert cache.cache_dir == tmp_path
        assert cache.league_code == "nba"
        assert cache.force_refresh is False

    def test_init_with_force_refresh(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba", force_refresh=True)
        assert cache.force_refresh is True

    def test_get_cache_path_boxscore(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/202410220BOS.html"
        path = cache._get_cache_path(url)
        assert path.name == "202410220BOS.html"

    def test_get_cache_path_pbp(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/pbp/202410220BOS.html"
        path = cache._get_cache_path(url)
        assert path.name == "pbp_202410220BOS.html"

    def test_get_cache_path_scoreboard(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/?month=10&day=22&year=2024"
        path = cache._get_cache_path(url)
        assert "scoreboard_" in path.name
        assert path.suffix == ".html"

    def test_get_cache_path_fallback_hash(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://example.com/some/random/path"
        path = cache._get_cache_path(url)
        assert path.name.startswith("page_")
        assert path.suffix == ".html"

    def test_is_scoreboard_url_true(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/?month=10&day=22&year=2024"
        assert cache._is_scoreboard_url(url) is True

    def test_is_scoreboard_url_false(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/202410220BOS.html"
        assert cache._is_scoreboard_url(url) is False

    def test_cache_miss(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://example.com/nonexistent"
        result = cache.get(url)
        assert result is None

    def test_cache_put_and_get(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/202410220BOS.html"
        html = "<html><body>Test content</body></html>"

        # Put content
        path = cache.put(url, html)
        assert path is not None
        assert path.exists()

        # Get content
        result = cache.get(url)
        assert result == html

    def test_cache_force_refresh(self, tmp_path):
        # First cache something with force_refresh=False
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/202410220BOS.html"
        html = "<html><body>Test content</body></html>"
        cache.put(url, html)

        # Now create cache with force_refresh=True
        cache_refresh = HTMLCache(tmp_path, "nba", force_refresh=True)
        result = cache_refresh.get(url)
        assert result is None  # Should return None due to force_refresh

    def test_cache_skips_small_scoreboard(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/?month=10&day=22&year=2024"
        html = "<html>small</html>"  # Too small

        path = cache.put(url, html)
        assert path is None  # Should not save

    def test_cache_saves_large_scoreboard(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        url = "https://www.basketball-reference.com/boxscores/?month=10&day=22&year=2024"
        html = "x" * (MIN_SCOREBOARD_SIZE_BYTES + 100)

        path = cache.put(url, html)
        assert path is not None

    def test_clear_recent_scoreboards_no_dir(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        result = cache.clear_recent_scoreboards(days=7)
        assert result["deleted_count"] == 0

    def test_clear_recent_scoreboards_deletes_files(self, tmp_path):
        cache = HTMLCache(tmp_path, "nba")
        league_dir = tmp_path / "nba"
        league_dir.mkdir()

        # Use today_et() to match the source function's timezone logic
        from sports_scraper.utils.datetime_utils import today_et

        today = today_et()
        filename = f"scoreboard_month{today.month}_day{today.day}_year{today.year}.html"
        (league_dir / filename).write_text("test")

        result = cache.clear_recent_scoreboards(days=0)
        assert result["deleted_count"] == 1


class TestAPICache:
    """Tests for APICache class."""

    def test_init(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")
        assert cache.cache_dir == tmp_path
        assert cache.api_name == "ncaab"

    def test_get_cache_path(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")
        path = cache._get_cache_path("teams_2024")
        assert path.name == "teams_2024.json"
        assert path.parent.name == "ncaab"

    def test_get_cache_path_sanitizes_special_chars(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")
        path = cache._get_cache_path("teams/2024:01?filter=active")
        assert "/" not in path.name
        assert ":" not in path.name
        assert "?" not in path.name

    def test_cache_miss(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")
        result = cache.get("nonexistent_key")
        assert result is None

    def test_cache_put_and_get(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")
        key = "teams_2024"
        data = {"teams": [{"id": 1, "name": "Duke"}]}

        # Put data
        path = cache.put(key, data)
        assert path is not None
        assert path.exists()

        # Get data
        result = cache.get(key)
        assert result == data

    def test_cache_get_invalid_json(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")
        key = "invalid_json"

        # Create invalid JSON file
        api_dir = tmp_path / "ncaab"
        api_dir.mkdir()
        (api_dir / "invalid_json.json").write_text("not valid json {")

        result = cache.get(key)
        assert result is None

    def test_cache_clear_all(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")

        # Create some cache files
        cache.put("key1", {"data": 1})
        cache.put("key2", {"data": 2})

        result = cache.clear()
        assert result["deleted_count"] == 2

    def test_cache_clear_with_pattern(self, tmp_path):
        cache = APICache(tmp_path, "ncaab")

        # Create some cache files
        cache.put("teams_2024", {"data": 1})
        cache.put("teams_2025", {"data": 2})
        cache.put("players_2024", {"data": 3})

        result = cache.clear("teams_*")
        assert result["deleted_count"] == 2

    def test_cache_clear_no_directory(self, tmp_path):
        cache = APICache(tmp_path, "nonexistent_api")
        result = cache.clear()
        assert result["deleted_count"] == 0
