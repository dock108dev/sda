"""Tests for live/mlb.py — MLBLiveFeedClient delegation and schedule error handling."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from datetime import date

import httpx
import pytest


# ---------------------------------------------------------------------------
# MLBLiveFeedClient tests
# ---------------------------------------------------------------------------


class TestMLBLiveFeedClientSchedule:
    """Tests for fetch_schedule error handling and edge cases."""

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def _make_client(self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast):
        """Create an MLBLiveFeedClient with mocked dependencies."""
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        return client

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_schedule_http_exception_continues(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        """When an HTTP exception occurs, the day is skipped and iteration continues."""
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        client.client = MagicMock()
        client.client.get.side_effect = httpx.ConnectError("Connection refused")

        result = client.fetch_schedule(date(2025, 6, 1), date(2025, 6, 1))
        assert result == []
        client.client.get.assert_called_once()

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_schedule_non_200_continues(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        """When the API returns a non-200 status, the day is skipped."""
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        client.client = MagicMock()
        client.client.get.return_value = mock_resp

        result = client.fetch_schedule(date(2025, 6, 1), date(2025, 6, 1))
        assert result == []

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_parse_schedule_skips_missing_game_pk(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        """Games without gamePk should be skipped in parsing."""
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()

        payload = {
            "dates": [
                {
                    "games": [
                        {
                            # No gamePk — should be skipped
                            "status": {"abstractGameState": "Final"},
                            "teams": {
                                "home": {"team": {"id": 1, "name": "Team A", "abbreviation": "TA"}},
                                "away": {"team": {"id": 2, "name": "Team B", "abbreviation": "TB"}},
                            },
                        },
                    ]
                }
            ]
        }
        result = client._parse_schedule_response(payload, date(2025, 6, 1))
        assert result == []

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_schedule_success_parses_games(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        """Successful fetch parses the response into MLBLiveGame objects."""
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": 12345,
                            "gameDate": "2025-06-01T18:05:00Z",
                            "gameType": "R",
                            "status": {
                                "abstractGameState": "Final",
                                "statusCode": "F",
                            },
                            "teams": {
                                "home": {
                                    "score": 5,
                                    "team": {
                                        "id": 147,
                                        "name": "New York Yankees",
                                        "abbreviation": "NYY",
                                    },
                                },
                                "away": {
                                    "score": 3,
                                    "team": {
                                        "id": 111,
                                        "name": "Boston Red Sox",
                                        "abbreviation": "BOS",
                                    },
                                },
                            },
                            "venue": {"name": "Yankee Stadium"},
                            "weather": {"temp": "75"},
                        },
                    ]
                }
            ]
        }
        client.client = MagicMock()
        client.client.get.return_value = mock_resp

        result = client.fetch_schedule(date(2025, 6, 1), date(2025, 6, 1))
        assert len(result) == 1
        game = result[0]
        assert game.game_pk == 12345
        assert game.home_score == 5
        assert game.away_score == 3
        assert game.venue == "Yankee Stadium"
        assert game.game_type == "R"

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_parse_schedule_no_game_date_falls_back_to_target_date(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        """When gameDate is missing, fall back to the target date."""
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()

        payload = {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": 99999,
                            # No gameDate — should fall back
                            "status": {"abstractGameState": "Preview"},
                            "teams": {
                                "home": {
                                    "team": {
                                        "id": 1,
                                        "name": "Team A",
                                        "abbreviation": "TA",
                                    }
                                },
                                "away": {
                                    "team": {
                                        "id": 2,
                                        "name": "Team B",
                                        "abbreviation": "TB",
                                    }
                                },
                            },
                        },
                    ]
                }
            ]
        }
        result = client._parse_schedule_response(payload, date(2025, 6, 1))
        assert len(result) == 1
        assert result[0].game_pk == 99999


class TestMLBLiveFeedClientDelegation:
    """Tests for delegation methods on MLBLiveFeedClient."""

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_play_by_play_delegates(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        sentinel = object()
        client._pbp_fetcher.fetch_play_by_play.return_value = sentinel

        result = client.fetch_play_by_play(12345, game_status="final")
        assert result is sentinel
        client._pbp_fetcher.fetch_play_by_play.assert_called_once_with(
            12345, game_status="final"
        )

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_statcast_aggregates_delegates(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        sentinel = {"home": object(), "away": object()}
        client._statcast_fetcher.fetch_statcast_aggregates.return_value = sentinel

        result = client.fetch_statcast_aggregates(12345, game_status="final")
        assert result is sentinel
        client._statcast_fetcher.fetch_statcast_aggregates.assert_called_once_with(
            12345, game_status="final"
        )

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_player_statcast_aggregates_delegates(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        sentinel = [object()]
        client._statcast_fetcher.fetch_player_statcast_aggregates.return_value = sentinel

        result = client.fetch_player_statcast_aggregates(12345, game_status="final")
        assert result is sentinel
        client._statcast_fetcher.fetch_player_statcast_aggregates.assert_called_once_with(
            12345, game_status="final"
        )

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_pitcher_statcast_aggregates_delegates(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        sentinel = [object()]
        client._statcast_fetcher.fetch_pitcher_statcast_aggregates.return_value = sentinel

        result = client.fetch_pitcher_statcast_aggregates(12345, game_status="final")
        assert result is sentinel
        client._statcast_fetcher.fetch_pitcher_statcast_aggregates.assert_called_once_with(
            12345, game_status="final"
        )

    @patch("sports_scraper.live.mlb.MLBStatcastFetcher")
    @patch("sports_scraper.live.mlb.MLBPbpFetcher")
    @patch("sports_scraper.live.mlb.MLBBoxscoreFetcher")
    @patch("sports_scraper.live.mlb.APICache")
    @patch("sports_scraper.live.mlb.httpx.Client")
    @patch("sports_scraper.live.mlb.settings")
    def test_fetch_boxscore_delegates(
        self, mock_settings, MockHttpClient, MockCache, MockBox, MockPbp, MockStatcast
    ):
        mock_settings.scraper_config.request_timeout_seconds = 30
        mock_settings.scraper_config.html_cache_dir = "/tmp/test_cache"

        from sports_scraper.live.mlb import MLBLiveFeedClient

        client = MLBLiveFeedClient()
        sentinel = object()
        client._boxscore_fetcher.fetch_boxscore.return_value = sentinel

        result = client.fetch_boxscore(12345, game_status="final")
        assert result is sentinel
        client._boxscore_fetcher.fetch_boxscore.assert_called_once_with(
            12345, game_status="final"
        )
