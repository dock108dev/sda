"""Tests for live/nhl_pbp.py module."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


from sports_scraper.live.nhl_pbp import NHLPbpFetcher


class TestNHLPbpFetcherInit:
    """Tests for NHLPbpFetcher initialization."""

    def test_init_stores_client_and_cache(self):
        """__init__ stores client and cache."""
        mock_client = MagicMock()
        mock_cache = MagicMock()

        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        assert fetcher.client is mock_client
        assert fetcher._cache is mock_cache


class TestFetchPlayByPlay:
    """Tests for fetch_play_by_play method."""

    def test_returns_cached_data(self):
        """Returns cached data when available."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get.return_value = {
            "plays": [],
            "homeTeam": {"id": 1, "abbrev": "TBL"},
            "awayTeam": {"id": 2, "abbrev": "BOS"},
            "rosterSpots": [],
            "gameState": "OFF",
        }

        fetcher = NHLPbpFetcher(mock_client, mock_cache)
        result = fetcher.fetch_play_by_play(2025020001)

        assert result.source_game_key == "2025020001"
        mock_client.get.assert_not_called()

    def test_fetches_from_api_on_cache_miss(self):
        """Fetches from API when cache misses, does not cache empty responses."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "plays": [],
            "homeTeam": {"id": 1, "abbrev": "TBL"},
            "awayTeam": {"id": 2, "abbrev": "BOS"},
            "rosterSpots": [],
        }
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLPbpFetcher(mock_client, mock_cache)
        result = fetcher.fetch_play_by_play(2025020001)

        assert result.source_game_key == "2025020001"
        mock_client.get.assert_called_once()
        # Empty responses should NOT be cached to allow retry
        mock_cache.put.assert_not_called()

    def test_caches_response_with_plays(self):
        """Caches API responses that have actual play data."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "gameState": "OFF",
            "plays": [
                {
                    "eventId": 1,
                    "sortOrder": 1,
                    "periodDescriptor": {"number": 1, "periodType": "REG"},
                    "typeDescKey": "faceoff",
                    "details": {},
                }
            ],
            "homeTeam": {"id": 1, "abbrev": "TBL"},
            "awayTeam": {"id": 2, "abbrev": "BOS"},
            "rosterSpots": [],
        }
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLPbpFetcher(mock_client, mock_cache)
        result = fetcher.fetch_play_by_play(2025020001)

        assert result.source_game_key == "2025020001"
        assert len(result.plays) == 1
        mock_client.get.assert_called_once()
        # Responses with plays SHOULD be cached
        mock_cache.put.assert_called_once()

    def test_returns_empty_on_404(self):
        """Returns empty plays on 404."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLPbpFetcher(mock_client, mock_cache)
        result = fetcher.fetch_play_by_play(2025020001)

        assert result.plays == []

    def test_returns_empty_on_error_status(self):
        """Returns empty plays on error status code."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_client.get.return_value = mock_response

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLPbpFetcher(mock_client, mock_cache)
        result = fetcher.fetch_play_by_play(2025020001)

        assert result.plays == []

    def test_returns_empty_on_exception(self):
        """Returns empty plays on exception."""
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Network error")

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        fetcher = NHLPbpFetcher(mock_client, mock_cache)
        result = fetcher.fetch_play_by_play(2025020001)

        assert result.plays == []


class TestParsePbpResponse:
    """Tests for _parse_pbp_response method."""

    def test_parses_empty_plays(self):
        """Parses empty plays list."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        payload = {
            "plays": [],
            "homeTeam": {"id": 1, "abbrev": "TBL"},
            "awayTeam": {"id": 2, "abbrev": "BOS"},
            "rosterSpots": [],
        }
        result = fetcher._parse_pbp_response(payload, 2025020001)

        assert result == []

    def test_parses_plays_with_roster(self):
        """Parses plays with roster data."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        payload = {
            "plays": [
                {
                    "sortOrder": 1,
                    "periodDescriptor": {"number": 1, "periodType": "REG"},
                    "typeDescKey": "faceoff",
                    "timeRemaining": "20:00",
                    "details": {"eventOwnerTeamId": 1, "winningPlayerId": 101},
                }
            ],
            "homeTeam": {"id": 1, "abbrev": "TBL"},
            "awayTeam": {"id": 2, "abbrev": "BOS"},
            "rosterSpots": [
                {"playerId": 101, "firstName": {"default": "John"}, "lastName": {"default": "Doe"}},
            ],
        }
        result = fetcher._parse_pbp_response(payload, 2025020001)

        assert len(result) == 1
        assert result[0].play_type == "FACEOFF"
        assert result[0].player_name == "John Doe"
        assert result[0].team_abbreviation == "TBL"

    def test_handles_missing_roster(self):
        """Handles missing roster data."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        payload = {
            "plays": [
                {
                    "sortOrder": 1,
                    "periodDescriptor": {"number": 1},
                    "typeDescKey": "goal",
                    "details": {},
                }
            ],
            "homeTeam": {"id": 1, "abbrev": "TBL"},
            "awayTeam": {"id": 2, "abbrev": "BOS"},
            "rosterSpots": [],  # Empty roster
        }
        result = fetcher._parse_pbp_response(payload, 2025020001)

        assert len(result) == 1


class TestMapEventType:
    """Tests for _map_event_type method."""

    def test_maps_known_event_types(self):
        """Maps known event types."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        # These should be in NHL_EVENT_TYPE_MAP
        assert fetcher._map_event_type("goal", 1) == "GOAL"
        assert fetcher._map_event_type("shot-on-goal", 1) == "SHOT"
        assert fetcher._map_event_type("faceoff", 1) == "FACEOFF"

    def test_maps_unknown_to_uppercase(self):
        """Maps unknown event types to uppercase."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._map_event_type("custom-event", 1)
        assert result == "CUSTOM_EVENT"

    def test_handles_empty_string(self):
        """Handles empty string."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._map_event_type("", 1)
        assert result == "UNKNOWN"


class TestExtractPrimaryPlayerId:
    """Tests for _extract_primary_player_id method."""

    def test_extracts_goal_scorer(self):
        """Extracts scoring player for goals."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"scoringPlayerId": 12345}
        result = fetcher._extract_primary_player_id(details, "goal")
        assert result == 12345

    def test_extracts_shooter_for_shot(self):
        """Extracts shooting player for shots."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"shootingPlayerId": 12345}
        result = fetcher._extract_primary_player_id(details, "shot-on-goal")
        assert result == 12345

    def test_extracts_shooter_for_missed_shot(self):
        """Extracts shooting player for missed shots."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"shootingPlayerId": 12345}
        result = fetcher._extract_primary_player_id(details, "missed-shot")
        assert result == 12345

    def test_extracts_blocker_for_blocked_shot(self):
        """Extracts blocking player for blocked shots."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"blockingPlayerId": 12345}
        result = fetcher._extract_primary_player_id(details, "blocked-shot")
        assert result == 12345

    def test_extracts_hitter_for_hit(self):
        """Extracts hitting player for hits."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"hittingPlayerId": 12345}
        result = fetcher._extract_primary_player_id(details, "hit")
        assert result == 12345

    def test_extracts_penalized_player(self):
        """Extracts penalized player for penalties."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"committedByPlayerId": 12345}
        result = fetcher._extract_primary_player_id(details, "penalty")
        assert result == 12345

    def test_extracts_faceoff_winner(self):
        """Extracts winning player for faceoffs."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"winningPlayerId": 12345}
        result = fetcher._extract_primary_player_id(details, "faceoff")
        assert result == 12345

    def test_extracts_giveaway_player(self):
        """Extracts player for giveaways."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"playerId": 12345}
        result = fetcher._extract_primary_player_id(details, "giveaway")
        assert result == 12345

    def test_extracts_takeaway_player(self):
        """Extracts player for takeaways."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"playerId": 12345}
        result = fetcher._extract_primary_player_id(details, "takeaway")
        assert result == 12345

    def test_fallback_extraction(self):
        """Uses fallback extraction for unknown types."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {"playerId": 12345}
        result = fetcher._extract_primary_player_id(details, "unknown-type")
        assert result == 12345

    def test_returns_none_when_no_player(self):
        """Returns None when no player ID found."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        details = {}
        result = fetcher._extract_primary_player_id(details, "goal")
        assert result is None


class TestBuildDescription:
    """Tests for _build_description method."""

    def test_builds_goal_description(self):
        """Builds goal description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("goal", {"shotType": "wrist"})
        assert result == "Goal (wrist)"

    def test_builds_goal_description_without_shot_type(self):
        """Builds goal description without shot type."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("goal", {})
        assert result == "Goal"

    def test_builds_shot_description(self):
        """Builds shot on goal description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("shot-on-goal", {"shotType": "slap"})
        assert result == "Shot on goal (slap)"

    def test_builds_missed_shot_description(self):
        """Builds missed shot description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("missed-shot", {"reason": "wide"})
        assert result == "Missed shot (wide)"

    def test_builds_blocked_shot_description(self):
        """Builds blocked shot description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("blocked-shot", {})
        assert result == "Blocked shot"

    def test_builds_hit_description(self):
        """Builds hit description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("hit", {})
        assert result == "Hit"

    def test_builds_penalty_description(self):
        """Builds penalty description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("penalty", {"descKey": "tripping", "duration": 2})
        assert result == "Penalty: tripping (2 min)"

    def test_builds_faceoff_description(self):
        """Builds faceoff description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("faceoff", {"zoneCode": "N"})
        assert result == "Faceoff (N zone)"

    def test_builds_stoppage_description(self):
        """Builds stoppage description."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("stoppage", {"reason": "icing"})
        assert result == "Stoppage: icing"

    def test_builds_default_description(self):
        """Builds default description for unknown types."""
        mock_client = MagicMock()
        mock_cache = MagicMock()
        fetcher = NHLPbpFetcher(mock_client, mock_cache)

        result = fetcher._build_description("unknown-type", {})
        assert result == "Unknown Type"


class TestBuildDescriptionWithPlayerName:
    """Descriptions must embed the primary player so consumers that only
    read the description column (LLM summarizer, search) know who did what.
    """

    def _fetcher(self) -> NHLPbpFetcher:
        return NHLPbpFetcher(MagicMock(), MagicMock())

    def test_goal_includes_scorer(self):
        result = self._fetcher()._build_description(
            "goal", {"shotType": "wrist"}, player_name="Connor McDavid"
        )
        assert result == "Goal by Connor McDavid (wrist)"

    def test_goal_with_assists_includes_scorer(self):
        result = self._fetcher()._build_description(
            "goal",
            {"shotType": "wrist", "assist1PlayerId": 1, "assist2PlayerId": 2},
            player_id_to_name={1: "Leon Draisaitl", 2: "Evan Bouchard"},
            player_name="Connor McDavid",
        )
        assert result == "Goal by Connor McDavid (wrist) (assists: Leon Draisaitl, Evan Bouchard)"

    def test_shot_on_goal_includes_shooter(self):
        result = self._fetcher()._build_description(
            "shot-on-goal", {"shotType": "slap"}, player_name="Auston Matthews"
        )
        assert result == "Shot on goal by Auston Matthews (slap)"

    def test_missed_shot_includes_shooter(self):
        result = self._fetcher()._build_description(
            "missed-shot", {"reason": "wide-right"}, player_name="Mitch Marner"
        )
        assert result == "Missed shot by Mitch Marner (wide-right)"

    def test_penalty_includes_offender(self):
        result = self._fetcher()._build_description(
            "penalty",
            {"descKey": "tripping", "duration": 2},
            player_name="Brad Marchand",
        )
        assert result == "Penalty on Brad Marchand: tripping (2 min)"

    def test_faceoff_includes_winner(self):
        result = self._fetcher()._build_description(
            "faceoff", {"zoneCode": "N"}, player_name="Patrice Bergeron"
        )
        assert result == "Faceoff won by Patrice Bergeron (N zone)"

    def test_giveaway_includes_player(self):
        result = self._fetcher()._build_description(
            "giveaway", {"zoneCode": "D"}, player_name="Jakob Chychrun"
        )
        assert result == "Giveaway by Jakob Chychrun (D zone)"

    def test_takeaway_includes_player(self):
        result = self._fetcher()._build_description(
            "takeaway", {"zoneCode": "O"}, player_name="Patrice Bergeron"
        )
        assert result == "Takeaway by Patrice Bergeron (O zone)"

    def test_stoppage_unaffected_by_player_name(self):
        """Stoppages have no acting player; description should not invent one."""
        result = self._fetcher()._build_description(
            "stoppage", {"reason": "icing"}, player_name="Should Not Appear"
        )
        assert result == "Stoppage: icing"


class TestModuleImports:
    """Tests for nhl_pbp module imports."""

    def test_has_nhl_pbp_fetcher(self):
        """Module has NHLPbpFetcher class."""
        from sports_scraper.live import nhl_pbp
        assert hasattr(nhl_pbp, 'NHLPbpFetcher')
