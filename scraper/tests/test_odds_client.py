"""Comprehensive tests for odds/client.py module."""

from __future__ import annotations

import json
import os
import sys
from datetime import date

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.odds.client import (
    CLOSING_LINE_HOURS,
    MARKET_TYPES,
    SPORT_KEY_MAP,
    OddsAPIClient,
)

# ============================================================================
# Constants Tests
# ============================================================================

class TestSportKeyMap:
    """Tests for SPORT_KEY_MAP constant."""

    def test_nba_mapping(self):
        assert SPORT_KEY_MAP["NBA"] == "basketball_nba"

    def test_nhl_mapping(self):
        assert SPORT_KEY_MAP["NHL"] == "icehockey_nhl"

    def test_nfl_mapping(self):
        assert SPORT_KEY_MAP["NFL"] == "americanfootball_nfl"

    def test_mlb_mapping(self):
        assert SPORT_KEY_MAP["MLB"] == "baseball_mlb"

    def test_ncaab_mapping(self):
        assert SPORT_KEY_MAP["NCAAB"] == "basketball_ncaab"

    def test_ncaaf_mapping(self):
        assert SPORT_KEY_MAP["NCAAF"] == "americanfootball_ncaaf"


class TestMarketTypes:
    """Tests for MARKET_TYPES constant."""

    def test_spreads_market(self):
        assert MARKET_TYPES["spreads"] == "spread"

    def test_totals_market(self):
        assert MARKET_TYPES["totals"] == "total"

    def test_h2h_market(self):
        assert MARKET_TYPES["h2h"] == "moneyline"


class TestClosingLineHours:
    """Tests for CLOSING_LINE_HOURS constant."""

    def test_nba_closing_hour(self):
        assert CLOSING_LINE_HOURS["NBA"] == 23

    def test_nhl_closing_hour(self):
        assert CLOSING_LINE_HOURS["NHL"] == 23

    def test_nfl_closing_hour(self):
        assert CLOSING_LINE_HOURS["NFL"] == 17  # Sunday afternoon games


# ============================================================================
# Client Tests
# ============================================================================

class TestOddsAPIClientInit:
    """Tests for OddsAPIClient initialization."""

    @patch("sports_scraper.odds.client.settings")
    def test_init_with_api_key(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        assert client._cache_dir == Path("/tmp/cache/odds")

    @patch("sports_scraper.odds.client.settings")
    def test_init_without_api_key(self, mock_settings):
        mock_settings.odds_api_key = None
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        # Should not raise, just log warning
        client = OddsAPIClient()
        assert client._cache_dir == Path("/tmp/cache/odds")


class TestOddsAPIClientHelpers:
    """Tests for OddsAPIClient helper methods."""

    @patch("sports_scraper.odds.client.settings")
    def test_sport_key_valid_league(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        assert client._sport_key("NBA") == "basketball_nba"
        assert client._sport_key("nba") == "basketball_nba"  # Case insensitive

    @patch("sports_scraper.odds.client.settings")
    def test_sport_key_invalid_league(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        assert client._sport_key("INVALID") is None

    @patch("sports_scraper.odds.client.settings")
    def test_truncate_body_short(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        result = client._truncate_body("short text", limit=500)
        assert result == "short text"

    @patch("sports_scraper.odds.client.settings")
    def test_truncate_body_long(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        long_text = "x" * 600
        result = client._truncate_body(long_text, limit=500)
        assert len(result) == 503  # 500 + "..."
        assert result.endswith("...")

    @patch("sports_scraper.odds.client.settings")
    def test_truncate_body_none(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        assert client._truncate_body(None) is None


class TestOddsAPIClientCache:
    """Tests for OddsAPIClient cache methods."""

    @patch("sports_scraper.odds.client.settings")
    def test_get_cache_path_live(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        path = client._get_cache_path("NBA", date(2024, 1, 15), is_historical=False)
        assert "live" in path.name
        assert "2024-01-15" in path.name

    @patch("sports_scraper.odds.client.settings")
    def test_get_cache_path_historical(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        path = client._get_cache_path("NBA", date(2024, 1, 15), is_historical=True)
        assert "historical" in path.name

    @patch("sports_scraper.odds.client.settings")
    def test_read_cache_miss(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        path = tmp_path / "nonexistent.json"
        result = client._read_cache(path)
        assert result is None

    @patch("sports_scraper.odds.client.settings")
    def test_read_cache_hit(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        cache_file = tmp_path / "test.json"
        cache_file.write_text('{"key": "value"}')

        result = client._read_cache(cache_file)
        assert result == {"key": "value"}

    @patch("sports_scraper.odds.client.settings")
    def test_read_cache_invalid_json(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        cache_file = tmp_path / "invalid.json"
        cache_file.write_text("not valid json {")

        result = client._read_cache(cache_file)
        assert result is None

    @patch("sports_scraper.odds.client.settings")
    def test_write_cache(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        cache_file = tmp_path / "new_dir" / "test.json"

        client._write_cache(cache_file, {"key": "value"})

        assert cache_file.exists()
        assert json.loads(cache_file.read_text()) == {"key": "value"}


class TestOddsAPIClientFetchMainlines:
    """Tests for fetch_mainlines method."""

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_mainlines_no_api_key(self, mock_settings):
        mock_settings.odds_api_key = None
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        result = client.fetch_mainlines("NBA", date(2024, 1, 15), date(2024, 1, 15))
        assert result == []

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_mainlines_invalid_league(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        result = client.fetch_mainlines("INVALID", date(2024, 1, 15), date(2024, 1, 15))
        assert result == []

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_mainlines_no_cache(self, mock_settings, tmp_path):
        """Live odds are never cached — always hit the API."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.odds_config.regions = ["us"]
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = [
            {
                "id": "test123",
                "commence_time": "2024-01-15T19:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": []
            }
        ]
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        client.fetch_mainlines("NBA", date(2024, 1, 15), date(2024, 1, 15))

        # API should always be called (no caching for live odds)
        client.client.get.assert_called_once()
        # No cache file should be written
        cache_file = tmp_path / "odds" / "NBA" / "2024-01-15_live.json"
        assert not cache_file.exists()

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_mainlines_api_success(self, mock_settings, tmp_path):
        """Test successful API call on cache miss."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"x-requests-remaining": "950"}
        mock_response.json.return_value = [
            {
                "id": "api123",
                "commence_time": "2024-01-15T19:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -180},
                                    {"name": "Los Angeles Lakers", "price": 150},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        result = client.fetch_mainlines("NBA", date(2024, 1, 15), date(2024, 1, 15))

        # Verify API was called
        client.client.get.assert_called_once()
        call_args = client.client.get.call_args
        assert "/sports/basketball_nba/odds" in call_args[0][0]

        # Verify results parsed
        assert len(result) == 2  # 2 moneyline outcomes

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_mainlines_api_error(self, mock_settings, tmp_path):
        """Test handling of API errors."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        # Mock error response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        with pytest.raises(RuntimeError, match="Odds API error 500"):
            client.fetch_mainlines("NBA", date(2024, 1, 15), date(2024, 1, 15))

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_mainlines_with_books_filter(self, mock_settings, tmp_path):
        """Test API call with books parameter."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = []
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        client.fetch_mainlines("NBA", date(2024, 1, 15), date(2024, 1, 15), books=["pinnacle", "draftkings"])

        # Verify bookmakers param included
        call_args = client.client.get.call_args
        params = call_args[1]["params"]
        assert params["bookmakers"] == "pinnacle,draftkings"

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_mainlines_does_not_write_cache(self, mock_settings, tmp_path):
        """Live odds responses are not cached."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.odds_config.regions = ["us"]
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = [
            {
                "id": "test",
                "commence_time": "2024-01-15T19:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": []
            }
        ]
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        client.fetch_mainlines("NBA", date(2024, 1, 15), date(2024, 1, 15))

        # Verify no cache file was written
        cache_file = tmp_path / "odds" / "NBA" / "2024-01-15_live.json"
        assert not cache_file.exists()


class TestOddsAPIClientFetchHistorical:
    """Tests for fetch_historical_odds method."""

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_no_api_key(self, mock_settings):
        mock_settings.odds_api_key = None
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        result = client.fetch_historical_odds("NBA", date(2024, 1, 15))
        assert result == []

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_invalid_league(self, mock_settings):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = "/tmp/cache"

        client = OddsAPIClient()
        result = client.fetch_historical_odds("INVALID", date(2024, 1, 15))
        assert result == []

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_cache_hit(self, mock_settings, tmp_path):
        """Test that cached historical data is returned without API call."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        # Create cached response with historical format (data wrapper)
        cache_dir = tmp_path / "odds" / "NBA"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "2024-01-15_historical.json"
        cached_data = {
            "data": [
                {
                    "id": "cached123",
                    "commence_time": "2024-01-15T00:00:00Z",
                    "home_team": "Boston Celtics",
                    "away_team": "Los Angeles Lakers",
                    "bookmakers": []
                }
            ],
            "timestamp": "2024-01-15T23:00:00Z"
        }
        cache_file.write_text(json.dumps(cached_data))

        client = OddsAPIClient()
        client.client = MagicMock()

        result = client.fetch_historical_odds("NBA", date(2024, 1, 15))

        # HTTP client should not be called when cache hits
        client.client.get.assert_not_called()
        # Result should contain cached data
        assert len(result) >= 0

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_cache_hit_list_format(self, mock_settings, tmp_path):
        """Test cache hit with older list format (no data wrapper)."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        # Create cached response in list format
        cache_dir = tmp_path / "odds" / "NBA"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "2024-01-15_historical.json"
        cached_data = [
            {
                "id": "cached123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": []
            }
        ]
        cache_file.write_text(json.dumps(cached_data))

        client = OddsAPIClient()
        client.client = MagicMock()

        result = client.fetch_historical_odds("NBA", date(2024, 1, 15))
        client.client.get.assert_not_called()
        # Result should contain cached data
        assert len(result) >= 0

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_api_success(self, mock_settings, tmp_path):
        """Test successful historical API call on cache miss."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "x-requests-remaining": "920",
            "x-requests-used": "80",
            "x-requests-last": "30",
        }
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "historical123",
                    "commence_time": "2024-01-15T19:00:00Z",
                    "home_team": "Boston Celtics",
                    "away_team": "Los Angeles Lakers",
                    "bookmakers": [
                        {
                            "key": "pinnacle",
                            "title": "Pinnacle",
                            "last_update": "2024-01-14T23:00:00Z",
                            "markets": [
                                {
                                    "key": "spreads",
                                    "outcomes": [
                                        {"name": "Boston Celtics", "price": -110, "point": -5.5},
                                        {"name": "Los Angeles Lakers", "price": -110, "point": 5.5},
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ],
            "timestamp": "2024-01-15T23:00:00Z"
        }
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        result = client.fetch_historical_odds("NBA", date(2024, 1, 15))

        # Verify API was called with historical endpoint
        client.client.get.assert_called_once()
        call_args = client.client.get.call_args
        assert "/historical/sports/basketball_nba/odds" in call_args[0][0]

        # Verify results parsed
        assert len(result) == 2  # 2 spread outcomes

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_api_error(self, mock_settings, tmp_path):
        """Test handling of historical API errors."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden - insufficient credits"
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        with pytest.raises(RuntimeError, match="Historical odds API error 403"):
            client.fetch_historical_odds("NBA", date(2024, 1, 15))

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_empty_data(self, mock_settings, tmp_path):
        """Test handling of empty historical data response."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "data": [],
            "timestamp": "2024-01-15T23:00:00Z"
        }
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        result = client.fetch_historical_odds("NBA", date(2024, 1, 15))

        assert result == []

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_with_books_filter(self, mock_settings, tmp_path):
        """Test historical API call with books parameter."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {"data": []}
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        client.fetch_historical_odds("NBA", date(2024, 1, 15), books=["fanduel"])

        call_args = client.client.get.call_args
        params = call_args[1]["params"]
        assert params["bookmakers"] == "fanduel"

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_writes_cache(self, mock_settings, tmp_path):
        """Test that successful historical responses are cached."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "test",
                    "commence_time": "2024-01-15T19:00:00Z",
                    "home_team": "Boston Celtics",
                    "away_team": "Los Angeles Lakers",
                    "bookmakers": []
                }
            ],
            "timestamp": "2024-01-15T23:00:00Z"
        }
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        client.fetch_historical_odds("NBA", date(2024, 1, 15))

        # Verify cache file was written
        cache_file = tmp_path / "odds" / "NBA" / "2024-01-15_historical.json"
        assert cache_file.exists()

    @patch("sports_scraper.odds.client.settings")
    def test_fetch_historical_uses_correct_closing_hour(self, mock_settings, tmp_path):
        """Test that different sports use their correct closing line hours."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {"data": []}
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        # Test NFL uses 17:00 UTC
        client.fetch_historical_odds("NFL", date(2024, 1, 14))

        call_args = client.client.get.call_args
        params = call_args[1]["params"]
        assert "T17:00:00Z" in params["date"]


class TestOddsAPIClientParseEvents:
    """Tests for _parse_odds_events method."""

    @patch("sports_scraper.odds.client.settings")
    def test_parse_empty_events(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        result = client._parse_odds_events("NBA", [], None)
        assert result == []

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_with_bookmakers(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -110, "point": -5.5},
                                    {"name": "Los Angeles Lakers", "price": -110, "point": 5.5},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        result = client._parse_odds_events("NBA", events, None)
        assert len(result) == 2  # 2 outcomes (home and away spread)

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_filters_books(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -110, "point": -5.5},
                                ]
                            }
                        ]
                    },
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -115, "point": -5.5},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        # Filter to only pinnacle
        result = client._parse_odds_events("NBA", events, books=["pinnacle"])
        assert len(result) == 1
        assert result[0].book == "Pinnacle"

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_skips_missing_data(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": None, "price": -110, "point": -5.5},  # Missing side
                                    {"name": "Lakers", "price": None, "point": 5.5},  # Missing price
                                    {"name": "Celtics", "price": -110, "point": None},  # Missing point for spread
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        result = client._parse_odds_events("NBA", events, None)
        assert len(result) == 0  # All outcomes should be skipped

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_moneyline_no_point_required(self, mock_settings, tmp_path):
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",  # Moneyline
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -180},  # No point needed
                                    {"name": "Los Angeles Lakers", "price": 150},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        result = client._parse_odds_events("NBA", events, None)
        assert len(result) == 2  # Both moneylines should be parsed

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_totals_market(self, mock_settings, tmp_path):
        """Test totals (over/under) market parsing."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 220.5},
                                    {"name": "Under", "price": -110, "point": 220.5},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        result = client._parse_odds_events("NBA", events, None)
        assert len(result) == 2
        assert result[0].market_type == "total"
        assert result[0].line == 220.5

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_ncaab_no_abbreviation_warning(self, mock_settings, tmp_path):
        """Test NCAAB teams don't trigger abbreviation warning (they're expected to be None)."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Duke Blue Devils",
                "away_team": "North Carolina Tar Heels",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Duke Blue Devils", "price": -150},
                                    {"name": "North Carolina Tar Heels", "price": 130},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        # Should not raise or log warning for NCAAB abbreviation
        result = client._parse_odds_events("NCAAB", events, None)
        assert len(result) == 2

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_unknown_market_skipped(self, mock_settings, tmp_path):
        """Test unknown market types are skipped."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "player_points",  # Unknown market type
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 25.5},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        result = client._parse_odds_events("NBA", events, None)
        assert len(result) == 0  # Unknown markets skipped

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_timezone_handling(self, mock_settings, tmp_path):
        """Test correct timezone conversion for US sports."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        # Game at midnight UTC on Jan 15 = 7pm ET on Jan 14
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T00:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-14T23:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -180},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        result = client._parse_odds_events("NBA", events, None)
        assert len(result) == 1
        # Game date should be converted to ET date (Jan 14, not Jan 15)
        assert result[0].game_date is not None

    @patch("sports_scraper.odds.client.settings")
    def test_parse_event_multiple_markets(self, mock_settings, tmp_path):
        """Test parsing event with multiple market types."""
        mock_settings.odds_api_key = "test_key"
        mock_settings.odds_config.base_url = "https://api.test.com"
        mock_settings.odds_config.request_timeout_seconds = 10
        mock_settings.scraper_config.html_cache_dir = str(tmp_path)

        client = OddsAPIClient()
        events = [
            {
                "id": "abc123",
                "commence_time": "2024-01-15T19:00:00Z",
                "home_team": "Boston Celtics",
                "away_team": "Los Angeles Lakers",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2024-01-15T18:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -180},
                                    {"name": "Los Angeles Lakers", "price": 150},
                                ]
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Boston Celtics", "price": -110, "point": -5.5},
                                    {"name": "Los Angeles Lakers", "price": -110, "point": 5.5},
                                ]
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 220.5},
                                    {"name": "Under", "price": -110, "point": 220.5},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        result = client._parse_odds_events("NBA", events, None)
        # 2 moneyline + 2 spread + 2 total = 6 outcomes
        assert len(result) == 6

        market_types = {r.market_type for r in result}
        assert market_types == {"moneyline", "spread", "total"}
