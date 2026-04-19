"""Comprehensive tests for live feed client classes with mocked HTTP."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime
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


# ============================================================================
# Tests for live/nba.py - NBALiveFeedClient
# ============================================================================

from sports_scraper.live.nba import (
    NBALiveFeedClient,
    _parse_nba_clock,
    _parse_nba_game_datetime,
)


class TestParseNBAGameDatetime:
    """Tests for _parse_nba_game_datetime helper."""

    def test_parse_iso_format(self):
        result = _parse_nba_game_datetime("2024-01-15T19:30:00Z")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_with_offset(self):
        result = _parse_nba_game_datetime("2024-01-15T19:30:00-05:00")
        assert result.year == 2024

    def test_empty_returns_now(self):
        result = _parse_nba_game_datetime("")
        assert isinstance(result, datetime)

    def test_none_returns_now(self):
        result = _parse_nba_game_datetime(None)
        assert isinstance(result, datetime)

    def test_invalid_returns_now(self):
        result = _parse_nba_game_datetime("not-a-date")
        assert isinstance(result, datetime)


class TestParseNBAClock:
    """Tests for _parse_nba_clock helper."""

    def test_parse_pt_format_minutes_seconds(self):
        result = _parse_nba_clock("PT10M30S")
        assert result == "10:30"

    def test_parse_pt_format_only_seconds(self):
        result = _parse_nba_clock("PT45S")
        assert result == "0:45"

    def test_parse_pt_format_only_minutes(self):
        result = _parse_nba_clock("PT5M")
        assert result == "5:00"

    def test_parse_non_pt_format_passthrough(self):
        result = _parse_nba_clock("10:30")
        assert result == "10:30"

    def test_empty_returns_none(self):
        result = _parse_nba_clock("")
        assert result is None

    def test_none_returns_none(self):
        result = _parse_nba_clock(None)
        assert result is None


class TestNBALiveFeedClient:
    """Tests for NBALiveFeedClient with mocked HTTP."""

    @patch("sports_scraper.utils.datetime_utils.today_et", return_value=date(2024, 1, 15))
    def test_fetch_scoreboard_success(self, _mock_today):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "scoreboard": {
                "games": [
                    {
                        "gameId": "0022400123",
                        "gameStatus": 3,
                        "gameStatusText": "Final",
                        "gameEt": "2024-01-15T19:30:00Z",
                        "homeTeam": {"teamTricode": "BOS", "score": 110},
                        "awayTeam": {"teamTricode": "LAL", "score": 105},
                    }
                ]
            }
        }

        client = NBALiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_scoreboard(date(2024, 1, 15))

        assert len(games) == 1
        assert games[0].game_id == "0022400123"
        assert games[0].status == "final"
        assert games[0].home_abbr == "BOS"
        assert games[0].away_abbr == "LAL"
        assert games[0].home_score == 110
        assert games[0].away_score == 105

    @patch("sports_scraper.utils.datetime_utils.today_et", return_value=date(2024, 1, 15))
    def test_fetch_scoreboard_live_game(self, _mock_today):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "scoreboard": {
                "games": [
                    {
                        "gameId": "0022400124",
                        "gameStatus": 2,  # Live
                        "gameStatusText": "Q3 5:30",
                        "gameEt": "2024-01-15T19:30:00Z",
                        "homeTeam": {"teamTricode": "MIA", "score": 75},
                        "awayTeam": {"teamTricode": "CHI", "score": 72},
                    }
                ]
            }
        }

        client = NBALiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_scoreboard(date(2024, 1, 15))

        assert games[0].status == "live"

    @patch("sports_scraper.utils.datetime_utils.today_et", return_value=date(2024, 1, 15))
    def test_fetch_scoreboard_scheduled_game(self, _mock_today):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "scoreboard": {
                "games": [
                    {
                        "gameId": "0022400125",
                        "gameStatus": 1,  # Scheduled
                        "gameStatusText": "7:30 PM ET",
                        "gameEt": "2024-01-15T19:30:00Z",
                        "homeTeam": {"teamTricode": "NYK", "score": None},
                        "awayTeam": {"teamTricode": "BKN", "score": None},
                    }
                ]
            }
        }

        client = NBALiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_scoreboard(date(2024, 1, 15))

        assert games[0].status == "scheduled"
        assert games[0].home_score is None

    def test_fetch_scoreboard_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        client = NBALiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_scoreboard(date(2024, 1, 15))

        assert games == []

    def test_fetch_play_by_play_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "game": {
                "actions": [
                    {
                        "actionNumber": 1,
                        "period": 1,
                        "clock": "PT12M00S",
                        "actionType": "jumpball",
                        "teamTricode": "BOS",
                        "description": "Jump ball won",
                    },
                    {
                        "actionNumber": 2,
                        "period": 1,
                        "clock": "PT11M45S",
                        "actionType": "2pt",
                        "teamTricode": "BOS",
                        "personId": 203500,
                        "playerName": "J. Tatum",
                        "description": "J. Tatum makes 2-pt shot",
                        "scoreHome": 2,
                        "scoreAway": 0,
                    },
                ]
            }
        }

        client = NBALiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        result = client.fetch_play_by_play("0022400123")

        assert result.source_game_key == "0022400123"
        assert len(result.plays) == 2
        assert result.plays[0].play_type == "jumpball"
        assert result.plays[1].player_name == "J. Tatum"
        assert result.plays[1].home_score == 2

    def test_fetch_play_by_play_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        client = NBALiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        result = client.fetch_play_by_play("0022400123")

        assert result.source_game_key == "0022400123"
        assert result.plays == []


# ============================================================================
# Tests for live/nhl.py - NHLLiveFeedClient
# ============================================================================

from sports_scraper.live.nhl import NHLLiveFeedClient


class TestNHLLiveFeedClient:
    """Tests for NHLLiveFeedClient with mocked HTTP."""

    def test_fetch_schedule_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        # NHL API uses gameWeek structure with nested dates
        mock_response.json.return_value = {
            "gameWeek": [
                {
                    "date": "2024-10-15",
                    "games": [
                        {
                            "id": 2025020001,
                            "startTimeUTC": "2024-10-15T23:00:00Z",
                            "gameState": "OFF",
                            "homeTeam": {
                                "abbrev": "TBL",
                                "commonName": {"default": "Lightning"},
                                "placeName": {"default": "Tampa Bay"},
                                "score": 4,
                            },
                            "awayTeam": {
                                "abbrev": "BOS",
                                "commonName": {"default": "Bruins"},
                                "placeName": {"default": "Boston"},
                                "score": 3,
                            },
                        }
                    ],
                }
            ]
        }

        client = NHLLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_schedule(date(2024, 10, 15), date(2024, 10, 15))

        assert len(games) == 1
        assert games[0].game_id == 2025020001
        assert games[0].status == "final"
        assert games[0].home_score == 4
        assert games[0].away_score == 3

    def test_fetch_schedule_live_game(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "gameWeek": [
                {
                    "date": "2024-10-15",
                    "games": [
                        {
                            "id": 2025020002,
                            "startTimeUTC": "2024-10-15T23:00:00Z",
                            "gameState": "LIVE",
                            "homeTeam": {
                                "abbrev": "NYR",
                                "commonName": {"default": "Rangers"},
                                "placeName": {"default": "New York"},
                                "score": 2,
                            },
                            "awayTeam": {
                                "abbrev": "NJD",
                                "commonName": {"default": "Devils"},
                                "placeName": {"default": "New Jersey"},
                                "score": 2,
                            },
                        }
                    ],
                }
            ]
        }

        client = NHLLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_schedule(date(2024, 10, 15), date(2024, 10, 15))

        assert games[0].status == "live"

    def test_fetch_schedule_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"

        client = NHLLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_schedule(date(2024, 10, 15), date(2024, 10, 15))

        assert games == []


# ============================================================================
# Tests for live/ncaab.py - NCAABLiveFeedClient
# ============================================================================

from sports_scraper.live.ncaab import NCAABLiveFeedClient


class TestNCAABLiveFeedClient:
    """Tests for NCAABLiveFeedClient with mocked HTTP."""

    @patch("sports_scraper.live.ncaab.settings")
    def test_fetch_games_success(self, mock_settings):
        mock_settings.cbb_stats_api_key = "test-api-key"
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12345,
                "startDate": "2024-01-15T19:00:00Z",
                "status": "final",
                "homeTeamId": 1,
                "homeTeam": "Duke",
                "awayTeamId": 2,
                "awayTeam": "UNC",
                "homePoints": 75,
                "awayPoints": 70,
                "neutralSite": False,
            }
        ]

        client = NCAABLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_games(date(2024, 1, 15), date(2024, 1, 15))

        assert len(games) == 1
        assert games[0].game_id == 12345
        assert games[0].status == "final"
        assert games[0].home_team_name == "Duke"
        assert games[0].home_score == 75

    @patch("sports_scraper.live.ncaab.settings")
    def test_fetch_games_live_status(self, mock_settings):
        mock_settings.cbb_stats_api_key = "test-api-key"
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12346,
                "startDate": "2024-01-15T19:00:00Z",
                "status": "in progress",
                "homeTeamId": 3,
                "homeTeam": "Kentucky",
                "awayTeamId": 4,
                "awayTeam": "Louisville",
                "homePoints": 45,
                "awayPoints": 42,
                "neutralSite": False,
            }
        ]

        client = NCAABLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_games(date(2024, 1, 15), date(2024, 1, 15))

        assert games[0].status == "live"

    @patch("sports_scraper.live.ncaab.settings")
    def test_fetch_games_in_progress_underscore_status(self, mock_settings):
        """CBB API returns 'in_progress' (underscore) for live games."""
        mock_settings.cbb_stats_api_key = "test-api-key"
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12347,
                "startDate": "2024-01-15T19:00:00Z",
                "status": "in_progress",
                "homeTeamId": 5,
                "homeTeam": "Kansas",
                "awayTeamId": 6,
                "awayTeam": "Missouri",
                "homePoints": 38,
                "awayPoints": 35,
                "neutralSite": False,
            }
        ]

        client = NCAABLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_games(date(2024, 1, 15), date(2024, 1, 15))

        assert len(games) == 1
        assert games[0].status == "live"

    @patch("sports_scraper.live.ncaab.settings")
    def test_fetch_games_postponed_status(self, mock_settings):
        """CBB API returns 'postponed' for postponed games."""
        mock_settings.cbb_stats_api_key = "test-api-key"
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12348,
                "startDate": "2024-01-15T19:00:00Z",
                "status": "postponed",
                "homeTeamId": 7,
                "homeTeam": "UNC",
                "awayTeamId": 8,
                "awayTeam": "NC State",
                "homePoints": 0,
                "awayPoints": 0,
                "neutralSite": False,
            }
        ]

        client = NCAABLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_games(date(2024, 1, 15), date(2024, 1, 15))

        assert len(games) == 1
        assert games[0].status == "postponed"

    @patch("sports_scraper.live.ncaab.settings")
    def test_fetch_games_cancelled_status(self, mock_settings):
        """CBB API returns 'cancelled' for cancelled games."""
        mock_settings.cbb_stats_api_key = "test-api-key"
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12349,
                "startDate": "2024-01-15T19:00:00Z",
                "status": "cancelled",
                "homeTeamId": 9,
                "homeTeam": "Virginia",
                "awayTeamId": 10,
                "awayTeam": "Virginia Tech",
                "homePoints": 0,
                "awayPoints": 0,
                "neutralSite": False,
            }
        ]

        client = NCAABLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_games(date(2024, 1, 15), date(2024, 1, 15))

        assert len(games) == 1
        assert games[0].status == "cancelled"

    @patch("sports_scraper.live.ncaab.settings")
    def test_fetch_games_failure(self, mock_settings):
        mock_settings.cbb_stats_api_key = "test-api-key"
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        mock_response = MagicMock()
        mock_response.status_code = 401

        client = NCAABLiveFeedClient()
        client.client = MagicMock()
        client.client.get.return_value = mock_response

        games = client.fetch_games(date(2024, 1, 15), date(2024, 1, 15))

        assert games == []

    @patch("sports_scraper.live.ncaab.settings")
    def test_get_season_for_date_fall(self, mock_settings):
        mock_settings.cbb_stats_api_key = None
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        client = NCAABLiveFeedClient()
        # October-December: next year's season
        assert client._get_season_for_date(date(2024, 11, 15)) == 2025
        assert client._get_season_for_date(date(2024, 12, 1)) == 2025

    @patch("sports_scraper.live.ncaab.settings")
    def test_get_season_for_date_spring(self, mock_settings):
        mock_settings.cbb_stats_api_key = None
        mock_settings.scraper_config.html_cache_dir = tempfile.mkdtemp()

        client = NCAABLiveFeedClient()
        # January-September: current year's season
        assert client._get_season_for_date(date(2024, 1, 15)) == 2024
        assert client._get_season_for_date(date(2024, 3, 15)) == 2024


# ============================================================================
# Tests for live/ncaab_boxscore.py - NCAABBoxscoreFetcher
# ============================================================================

from sports_scraper.live.ncaab_boxscore import NCAABBoxscoreFetcher


class TestNCAABBoxscoreFetcher:
    """Tests for NCAABBoxscoreFetcher with mocked HTTP."""

    def test_fetch_game_teams_by_date_range_success(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "gameId": 12345,
                "teamId": 1,
                "isHome": True,
                "teamStats": {"points": 75, "rebounds": 35},
            },
            {
                "gameId": 12345,
                "teamId": 2,
                "isHome": False,
                "teamStats": {"points": 70, "rebounds": 32},
            },
        ]
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # No cache

        fetcher = NCAABBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_game_teams_by_date_range(
            date(2024, 1, 15), date(2024, 1, 15), 2024
        )

        assert len(result) == 2
        assert result[0]["teamStats"]["points"] == 75

    def test_fetch_game_teams_caches_past_dates(self):
        """Date-range methods cache responses for past date ranges."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"gameId": 12345, "teamId": 1}]
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # cache miss

        fetcher = NCAABBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_game_teams_by_date_range(
            date(2024, 1, 15), date(2024, 1, 15), 2024
        )

        assert len(result) == 1
        mock_client.get.assert_called_once()
        mock_cache.get.assert_called_once()  # checked cache first
        mock_cache.put.assert_called_once()  # cached the result

    def test_fetch_game_teams_failure(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NCAABBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_game_teams_by_date_range(
            date(2024, 1, 15), date(2024, 1, 15), 2024
        )

        assert result == []

    def test_fetch_boxscores_batch(self):
        mock_client = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        # Mock team stats response
        team_response = MagicMock()
        team_response.status_code = 200
        team_response.json.return_value = [
            {
                "gameId": 12345,
                "teamId": 1,
                "isHome": True,
                "teamStats": {"points": 75, "rebounds": 35, "assists": 15},
            },
            {
                "gameId": 12345,
                "teamId": 2,
                "isHome": False,
                "teamStats": {"points": 70, "rebounds": 32, "assists": 12},
            },
        ]

        # Mock player stats response
        player_response = MagicMock()
        player_response.status_code = 200
        player_response.json.return_value = [
            {
                "gameId": 12345,
                "teamId": 1,
                "players": [
                    {"playerId": 101, "name": "Player A", "points": 25, "rebounds": 10},
                    {"playerId": 102, "name": "Player B", "points": 18, "rebounds": 8},
                ],
            }
        ]

        mock_client.get.side_effect = [team_response, player_response]

        fetcher = NCAABBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_boxscores_batch(
            game_ids=[12345],
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            season=2024,
            team_names_by_game={12345: ("Duke", "UNC")},
        )

        assert 12345 in result
        assert result[12345].home_score == 75
        assert result[12345].away_score == 70


# ============================================================================
# Tests for live/nhl_boxscore.py - NHLBoxscoreFetcher
# ============================================================================

from sports_scraper.live.nhl_boxscore import NHLBoxscoreFetcher


class TestNHLBoxscoreFetcher:
    """Tests for NHLBoxscoreFetcher with mocked HTTP."""

    def test_fetch_boxscore_success(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "gameDate": "2024-10-15",
            "gameState": "OFF",
            "homeTeam": {
                "abbrev": "TBL",
                "commonName": {"default": "Lightning"},
                "placeName": {"default": "Tampa Bay"},
                "score": 4,
            },
            "awayTeam": {
                "abbrev": "BOS",
                "commonName": {"default": "Bruins"},
                "placeName": {"default": "Boston"},
                "score": 3,
            },
            "playerByGameStats": {
                "homeTeam": {
                    "forwards": [
                        {
                            "playerId": 8478010,
                            "name": {"default": "Brayden Point"},
                            "position": "C",
                            "sweaterNumber": 21,
                            "goals": 2,
                            "assists": 1,
                            "points": 3,
                            "sog": 5,
                            "toi": "18:45",
                        }
                    ],
                    "defense": [],
                    "goalies": [
                        {
                            "playerId": 8476883,
                            "name": {"default": "Andrei Vasilevskiy"},
                            "saveShotsAgainst": "30/33",
                            "goalsAgainst": 3,
                            "savePctg": 0.909,
                            "toi": "60:00",
                        }
                    ],
                },
                "awayTeam": {
                    "forwards": [],
                    "defense": [],
                    "goalies": [],
                },
            },
        }
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_boxscore(2025020001)

        assert result is not None
        assert result.game_id == 2025020001
        assert result.status == "final"
        assert result.home_score == 4
        assert result.away_score == 3
        assert len(result.player_boxscores) > 0

    def test_fetch_boxscore_uses_cache(self):
        mock_client = MagicMock()
        cached_payload = {
            "gameDate": "2024-10-15",
            "gameState": "OFF",
            "homeTeam": {
                "abbrev": "TBL",
                "commonName": {"default": "Lightning"},
                "placeName": {"default": "Tampa Bay"},
                "score": 4,
            },
            "awayTeam": {
                "abbrev": "BOS",
                "commonName": {"default": "Bruins"},
                "placeName": {"default": "Boston"},
                "score": 3,
            },
            "playerByGameStats": {
                "homeTeam": {"forwards": [], "defense": [], "goalies": []},
                "awayTeam": {"forwards": [], "defense": [], "goalies": []},
            },
        }

        mock_cache = MagicMock()
        mock_cache.get.return_value = cached_payload

        fetcher = NHLBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_boxscore(2025020001)

        assert result is not None
        mock_client.get.assert_not_called()

    def test_fetch_boxscore_404(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_boxscore(2025020999)

        assert result is None

    def test_fetch_boxscore_error(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLBoxscoreFetcher(mock_client, mock_cache)
        result = fetcher.fetch_boxscore(2025020001)

        assert result is None

    def test_parse_skater_stats(self):
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLBoxscoreFetcher(mock_client, mock_cache)

        from sports_scraper.models import TeamIdentity

        team_identity = TeamIdentity(
            league_code="NHL",
            name="Tampa Bay Lightning",
            short_name="Lightning",
            abbreviation="TBL",
            external_ref="TBL",
        )

        player_data = {
            "playerId": 8478010,
            "name": {"default": "Brayden Point"},
            "position": "C",
            "sweaterNumber": 21,
            "goals": 2,
            "assists": 1,
            "points": 3,
            "sog": 5,
            "toi": "18:45",
            "plusMinus": 2,
        }

        result = fetcher._parse_skater_stats(player_data, team_identity, 2025020001)

        assert result is not None
        assert result.player_id == "8478010"
        assert result.player_name == "Brayden Point"
        assert result.goals == 2
        assert result.assists == 1
        assert result.player_role == "skater"

    def test_parse_goalie_stats(self):
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLBoxscoreFetcher(mock_client, mock_cache)

        from sports_scraper.models import TeamIdentity

        team_identity = TeamIdentity(
            league_code="NHL",
            name="Tampa Bay Lightning",
            short_name="Lightning",
            abbreviation="TBL",
            external_ref="TBL",
        )

        player_data = {
            "playerId": 8476883,
            "name": {"default": "Andrei Vasilevskiy"},
            "saveShotsAgainst": "30/33",
            "goalsAgainst": 3,
            "savePctg": 0.909,
            "toi": "60:00",
        }

        result = fetcher._parse_goalie_stats(player_data, team_identity, 2025020001)

        assert result is not None
        assert result.player_id == "8476883"
        assert result.player_name == "Andrei Vasilevskiy"
        assert result.saves == 30
        assert result.shots_against == 33
        assert result.goals_against == 3
        assert result.player_role == "goalie"


# ============================================================================
# Tests for live/mlb.py - MLBLiveFeedClient schedule parsing
# ============================================================================

from sports_scraper.live.mlb import MLBLiveFeedClient


def _make_mlb_schedule_game(
    game_pk: int,
    home_abbr: str = "NYY",
    away_abbr: str = "BOS",
    game_date_iso: str | None = None,
    status: str = "Final",
) -> dict:
    """Build a minimal MLB schedule API game entry."""
    game = {
        "gamePk": game_pk,
        "status": {"abstractGameState": status, "statusCode": "F" if status == "Final" else "S"},
        "teams": {
            "home": {"team": {"abbreviation": home_abbr, "name": f"{home_abbr} Team", "teamName": home_abbr}},
            "away": {"team": {"abbreviation": away_abbr, "name": f"{away_abbr} Team", "teamName": away_abbr}},
        },
        "venue": {"name": "Test Park"},
    }
    if game_date_iso:
        game["gameDate"] = game_date_iso
    return game


class TestMLBParseScheduleResponse:
    """Tests for MLBLiveFeedClient._parse_schedule_response."""

    def _make_client(self):
        with patch("sports_scraper.live.mlb.settings") as mock_settings:
            mock_settings.scraper_config.request_timeout_seconds = 30
            mock_settings.scraper_config.html_cache_dir = "/tmp/test"
            return MLBLiveFeedClient()

    def test_parses_actual_game_datetime(self):
        """Uses gameDate ISO datetime from API when available."""
        client = self._make_client()
        payload = {
            "dates": [
                {
                    "games": [
                        _make_mlb_schedule_game(
                            748001,
                            game_date_iso="2025-07-04T17:10:00Z",
                        ),
                    ]
                }
            ]
        }
        games = client._parse_schedule_response(payload, date(2025, 7, 4))

        assert len(games) == 1
        assert games[0].game_pk == 748001
        assert games[0].game_date.hour == 17
        assert games[0].game_date.minute == 10

    def test_skips_game_when_no_game_date(self):
        """Skips game when gameDate is absent rather than using a placeholder."""
        client = self._make_client()
        payload = {
            "dates": [
                {
                    "games": [
                        _make_mlb_schedule_game(748002),
                    ]
                }
            ]
        }
        games = client._parse_schedule_response(payload, date(2025, 7, 4))

        assert len(games) == 0

    def test_doubleheader_produces_two_games(self):
        """Two games for same teams on same date are both returned."""
        client = self._make_client()
        payload = {
            "dates": [
                {
                    "games": [
                        _make_mlb_schedule_game(
                            748010,
                            game_date_iso="2025-07-04T13:10:00Z",
                        ),
                        _make_mlb_schedule_game(
                            748011,
                            game_date_iso="2025-07-04T19:10:00Z",
                        ),
                    ]
                }
            ]
        }
        games = client._parse_schedule_response(payload, date(2025, 7, 4))

        assert len(games) == 2
        pks = {g.game_pk for g in games}
        assert pks == {748010, 748011}
        # Earlier game has earlier time
        by_pk = sorted(games, key=lambda g: g.game_pk)
        assert by_pk[0].game_date.hour == 13
        assert by_pk[1].game_date.hour == 19
