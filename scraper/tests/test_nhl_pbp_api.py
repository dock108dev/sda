"""Tests for NHL PBP ingestion via the official NHL API (api-web.nhle.com)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the scraper package is importable when running from repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test_db")

from sports_scraper.live.nhl import NHLLiveFeedClient
from sports_scraper.live.nhl_constants import NHL_EVENT_TYPE_MAP, NHL_MIN_EXPECTED_PLAYS
from sports_scraper.live.nhl_helpers import map_nhl_game_state
from sports_scraper.utils.parsing import parse_int

# Sample play data from the real NHL API
SAMPLE_GOAL_PLAY = {
    "eventId": 151,
    "periodDescriptor": {"number": 1, "periodType": "REG", "maxRegulationPeriods": 3},
    "timeInPeriod": "04:00",
    "timeRemaining": "16:00",
    "situationCode": "1551",
    "homeTeamDefendingSide": "right",
    "typeCode": 505,
    "typeDescKey": "goal",
    "sortOrder": 67,
    "details": {
        "xCoord": -86,
        "yCoord": 1,
        "zoneCode": "O",
        "shotType": "snap",
        "scoringPlayerId": 8480840,
        "scoringPlayerTotal": 4,
        "assist1PlayerId": 8480878,
        "assist1PlayerTotal": 4,
        "assist2PlayerId": 8482145,
        "assist2PlayerTotal": 9,
        "eventOwnerTeamId": 25,
        "goalieInNetId": 8476883,
        "awayScore": 0,
        "homeScore": 1,
    },
}

SAMPLE_PENALTY_PLAY = {
    "eventId": 133,
    "periodDescriptor": {"number": 1, "periodType": "REG"},
    "timeInPeriod": "05:24",
    "timeRemaining": "14:36",
    "typeCode": 509,
    "typeDescKey": "penalty",
    "sortOrder": 84,
    "details": {
        "xCoord": -81,
        "yCoord": 1,
        "zoneCode": "D",
        "typeCode": "MIN",
        "descKey": "hooking",
        "duration": 2,
        "committedByPlayerId": 8478416,
        "drawnByPlayerId": 8476889,
        "eventOwnerTeamId": 14,
    },
}

SAMPLE_FACEOFF_PLAY = {
    "eventId": 53,
    "periodDescriptor": {"number": 1, "periodType": "REG"},
    "timeInPeriod": "00:00",
    "timeRemaining": "20:00",
    "typeDescKey": "faceoff",
    "sortOrder": 11,
    "details": {
        "eventOwnerTeamId": 25,
        "losingPlayerId": 8476826,
        "winningPlayerId": 8482145,
        "xCoord": 0,
        "yCoord": 0,
        "zoneCode": "N",
    },
}


class TestNHLEventTypeMapping:
    """Test explicit event type mapping."""

    def test_all_required_event_types_mapped(self):
        """Verify all required event types are in the mapping."""
        required_types = [
            "goal",
            "shot-on-goal",
            "missed-shot",
            "blocked-shot",
            "hit",
            "penalty",
            "faceoff",
            "giveaway",
            "takeaway",
            "period-start",
            "period-end",
            "game-end",
        ]
        for event_type in required_types:
            assert event_type in NHL_EVENT_TYPE_MAP, f"Missing event type: {event_type}"

    def test_event_type_values_are_uppercase(self):
        """Verify all mapped values are uppercase for consistency."""
        for key, value in NHL_EVENT_TYPE_MAP.items():
            assert value == value.upper(), f"Event type {key} has non-uppercase value: {value}"


class TestNHLGameStateMapping:
    """Test game state to status mapping."""

    def test_final_states(self):
        assert map_nhl_game_state("OFF") == "final"
        assert map_nhl_game_state("FINAL") == "final"

    def test_live_states(self):
        assert map_nhl_game_state("LIVE") == "live"
        assert map_nhl_game_state("CRIT") == "live"

    def test_scheduled_states(self):
        assert map_nhl_game_state("FUT") == "scheduled"
        assert map_nhl_game_state("PRE") == "scheduled"

    def test_unknown_defaults_to_scheduled(self):
        assert map_nhl_game_state("UNKNOWN") == "scheduled"
        assert map_nhl_game_state("") == "scheduled"


class TestNHLPlayNormalization:
    """Test play normalization from raw NHL API data."""

    def test_normalize_goal_play(self):
        """Test goal event normalization."""
        client = NHLLiveFeedClient()
        team_id_to_abbr = {25: "DAL", 14: "TBL"}
        player_id_to_name: dict[int, str] = {}

        play = client._pbp_fetcher._normalize_play(SAMPLE_GOAL_PLAY, team_id_to_abbr, player_id_to_name, game_id=123)

        assert play is not None
        assert play.quarter == 1  # Period 1
        assert play.game_clock == "16:00"  # time_remaining
        assert play.play_type == "GOAL"
        assert play.team_abbreviation == "DAL"  # eventOwnerTeamId=25
        assert play.player_id == "8480840"  # scoringPlayerId
        assert play.home_score == 1
        assert play.away_score == 0
        assert "snap" in (play.description or "").lower()

    def test_normalize_penalty_play(self):
        """Test penalty event normalization."""
        client = NHLLiveFeedClient()
        team_id_to_abbr = {25: "DAL", 14: "TBL"}
        player_id_to_name: dict[int, str] = {}

        play = client._pbp_fetcher._normalize_play(SAMPLE_PENALTY_PLAY, team_id_to_abbr, player_id_to_name, game_id=123)

        assert play is not None
        assert play.quarter == 1
        assert play.game_clock == "14:36"
        assert play.play_type == "PENALTY"
        assert play.team_abbreviation == "TBL"  # eventOwnerTeamId=14
        assert play.player_id == "8478416"  # committedByPlayerId
        assert "hooking" in (play.description or "").lower()
        assert "2 min" in (play.description or "").lower()

    def test_normalize_faceoff_play(self):
        """Test faceoff event normalization."""
        client = NHLLiveFeedClient()
        team_id_to_abbr = {25: "DAL", 14: "TBL"}
        player_id_to_name: dict[int, str] = {}

        play = client._pbp_fetcher._normalize_play(SAMPLE_FACEOFF_PLAY, team_id_to_abbr, player_id_to_name, game_id=123)

        assert play is not None
        assert play.quarter == 1
        assert play.game_clock == "20:00"
        assert play.play_type == "FACEOFF"
        assert play.team_abbreviation == "DAL"
        assert play.player_id == "8482145"  # winningPlayerId

    def test_play_index_calculation(self):
        """Test that play_index is calculated correctly from period and sortOrder."""
        client = NHLLiveFeedClient()
        team_id_to_abbr: dict[int, str] = {}
        player_id_to_name: dict[int, str] = {}

        # Period 1, sortOrder 67
        play = client._pbp_fetcher._normalize_play(SAMPLE_GOAL_PLAY, team_id_to_abbr, player_id_to_name, game_id=123)
        assert play is not None
        assert play.play_index == 1 * 10000 + 67  # 10067

    def test_missing_sort_order_returns_none(self):
        """Test that plays without sortOrder are skipped."""
        client = NHLLiveFeedClient()
        play_without_sort = {"eventId": 1, "typeDescKey": "goal"}

        result = client._pbp_fetcher._normalize_play(play_without_sort, {}, {}, game_id=123)
        assert result is None


class TestNHLPBPScoreForwardFill:
    """The NHL API only emits homeScore/awayScore on goal events. We forward-fill
    so non-goal plays carry the running game score, matching the shape NBA/MLB
    feeds emit. Without this, downstream gameflow score detection sees phantom
    score reversals on every play immediately following a goal."""

    def _build_payload(self, plays_in_order):
        return {
            "gameState": "OFF",
            "homeTeam": {"id": 25, "abbrev": "DAL"},
            "awayTeam": {"id": 14, "abbrev": "TBL"},
            "plays": plays_in_order,
        }

    def test_pre_goal_plays_default_to_zero(self):
        client = NHLLiveFeedClient()
        # Faceoff (sort=11) before any goal — should fill to (0, 0).
        plays = client._pbp_fetcher._parse_pbp_response(
            self._build_payload([SAMPLE_FACEOFF_PLAY]), game_id=1,
        )
        assert plays[0].home_score == 0
        assert plays[0].away_score == 0

    def test_non_goal_play_after_goal_carries_score_forward(self):
        # Goal at sort=67 (home 1, away 0); penalty at sort=84 (no scores).
        # Sorted by play_index, the penalty comes after the goal and must
        # inherit (1, 0) — NOT collapse to (0, 0).
        client = NHLLiveFeedClient()
        plays = client._pbp_fetcher._parse_pbp_response(
            self._build_payload([SAMPLE_GOAL_PLAY, SAMPLE_PENALTY_PLAY]), game_id=1,
        )
        # Confirm ordering: goal first, then penalty.
        assert plays[0].play_type == "GOAL"
        assert plays[0].home_score == 1
        assert plays[0].away_score == 0
        assert plays[1].play_type == "PENALTY"
        assert plays[1].home_score == 1
        assert plays[1].away_score == 0

    def test_pre_first_goal_then_goal_then_post_goal_sequence(self):
        # Faceoff (sort=11) → Goal (sort=67) → Penalty (sort=84).
        client = NHLLiveFeedClient()
        plays = client._pbp_fetcher._parse_pbp_response(
            self._build_payload(
                [SAMPLE_FACEOFF_PLAY, SAMPLE_GOAL_PLAY, SAMPLE_PENALTY_PLAY]
            ),
            game_id=1,
        )
        assert [p.play_type for p in plays] == ["FACEOFF", "GOAL", "PENALTY"]
        assert (plays[0].home_score, plays[0].away_score) == (0, 0)
        assert (plays[1].home_score, plays[1].away_score) == (1, 0)
        assert (plays[2].home_score, plays[2].away_score) == (1, 0)


class TestNHLPBPValidation:
    """Test validation and guardrails."""

    def test_min_expected_plays_constant(self):
        """Verify minimum expected plays constant is reasonable."""
        assert NHL_MIN_EXPECTED_PLAYS >= 100
        assert NHL_MIN_EXPECTED_PLAYS <= 500  # Not too high


class TestHelperFunctions:
    """Test helper functions."""

    def test_parse_int_valid(self):
        assert parse_int(123) == 123
        assert parse_int("456") == 456

    def test_parse_int_invalid(self):
        assert parse_int(None) is None
        assert parse_int("abc") is None
        assert parse_int({}) is None


class TestNHLClientMocked:
    """Test NHL client with mocked HTTP responses."""

    @patch("sports_scraper.live.nhl.httpx.Client")
    def test_fetch_pbp_success(self, mock_client_class):
        """Test successful PBP fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "gameState": "OFF",
            "homeTeam": {"id": 25, "abbrev": "DAL"},
            "awayTeam": {"id": 14, "abbrev": "TBL"},
            "plays": [SAMPLE_GOAL_PLAY, SAMPLE_FACEOFF_PLAY],
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = NHLLiveFeedClient()
        result = client.fetch_play_by_play(2025020767)

        assert result.source_game_key == "2025020767"
        assert len(result.plays) == 2

    @patch("sports_scraper.live.nhl.httpx.Client")
    def test_fetch_pbp_404_returns_empty(self, mock_client_class):
        """Test that 404 returns empty PBP, not error."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = NHLLiveFeedClient()
        result = client.fetch_play_by_play(9999999999)

        assert result.source_game_key == "9999999999"
        assert len(result.plays) == 0

    @patch("sports_scraper.live.nhl_pbp.APICache")
    @patch("sports_scraper.live.nhl.httpx.Client")
    def test_unknown_event_type_still_stored(self, mock_client_class, mock_cache_class):
        """Test that unknown event types are stored (not dropped)."""
        # Mock cache to return None (no cached data)
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_cache_class.return_value = mock_cache

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "gameState": "OFF",
            "homeTeam": {"id": 25, "abbrev": "DAL"},
            "awayTeam": {"id": 14, "abbrev": "TBL"},
            "plays": [
                {
                    "eventId": 999,
                    "periodDescriptor": {"number": 1},
                    "timeRemaining": "10:00",
                    "typeDescKey": "unknown-future-event-type",
                    "sortOrder": 100,
                    "details": {},
                }
            ],
        }

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = NHLLiveFeedClient()
        # Need to also mock the cache on the PBP fetcher
        client._pbp_fetcher._cache = mock_cache
        result = client.fetch_play_by_play(2025020767)

        assert len(result.plays) == 1
        # Unknown type should be converted to uppercase with underscores
        assert result.plays[0].play_type == "UNKNOWN_FUTURE_EVENT_TYPE"
