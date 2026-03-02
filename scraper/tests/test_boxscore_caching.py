"""Tests for conditional caching logic in boxscore and PBP fetchers.

All fetchers use the same should_cache_final gate: cache only when the game
is in a final state AND the response contains meaningful data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.live.mlb_boxscore import MLBBoxscoreFetcher
from sports_scraper.live.mlb_pbp import MLBPbpFetcher
from sports_scraper.live.nba_boxscore import NBABoxscoreFetcher
from sports_scraper.live.ncaab_pbp import NCAABPbpFetcher
from sports_scraper.live.nhl_boxscore import NHLBoxscoreFetcher
from sports_scraper.live.nhl_pbp import NHLPbpFetcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(payload: dict | list, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# NBA boxscore fetcher caching
# ---------------------------------------------------------------------------


class TestNBABoxscoreCaching:
    """Verify NBABoxscoreFetcher caches only final games with player data."""

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = None  # cache miss
        return mock

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    def _nba_payload(
        self,
        game_status: int,
        home_players: list | None = None,
        away_players: list | None = None,
    ) -> dict:
        return {
            "game": {
                "gameStatus": game_status,
                "homeTeam": {
                    "teamTricode": "LAL",
                    "teamCity": "Los Angeles",
                    "teamName": "Lakers",
                    "score": 110,
                    "players": home_players or [],
                    "statistics": {},
                },
                "awayTeam": {
                    "teamTricode": "BOS",
                    "teamCity": "Boston",
                    "teamName": "Celtics",
                    "score": 105,
                    "players": away_players or [],
                    "statistics": {},
                },
            },
        }

    def test_caches_final_game_with_players(self, client: MagicMock, cache: MagicMock) -> None:
        """Final (status=3) game with player data is cached."""
        payload = self._nba_payload(3, home_players=[{"name": "LeBron"}])
        client.get.return_value = _make_http_response(payload)

        fetcher = NBABoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore("0022400001")

        cache.put.assert_called_once()

    def test_skips_cache_for_live_game(self, client: MagicMock, cache: MagicMock) -> None:
        """Live (status=2) game is never cached."""
        payload = self._nba_payload(2, home_players=[{"name": "LeBron"}])
        client.get.return_value = _make_http_response(payload)

        fetcher = NBABoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore("0022400001")

        cache.put.assert_not_called()

    def test_skips_cache_for_scheduled_game(self, client: MagicMock, cache: MagicMock) -> None:
        """Scheduled (status=1) game is never cached."""
        payload = self._nba_payload(1)
        client.get.return_value = _make_http_response(payload)

        fetcher = NBABoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore("0022400001")

        cache.put.assert_not_called()

    def test_skips_cache_for_final_without_players(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game with empty player lists is not cached."""
        payload = self._nba_payload(3, home_players=[], away_players=[])
        client.get.return_value = _make_http_response(payload)

        fetcher = NBABoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore("0022400001")

        cache.put.assert_not_called()

    def test_uses_cached_response(self, client: MagicMock, cache: MagicMock) -> None:
        """Returns cached data without hitting the network."""
        payload = self._nba_payload(3, home_players=[{"name": "LeBron"}])
        cache.get.return_value = payload

        fetcher = NBABoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore("0022400001")

        client.get.assert_not_called()
        assert result is not None


# ---------------------------------------------------------------------------
# NHL boxscore fetcher caching
# ---------------------------------------------------------------------------


class TestNHLBoxscoreCaching:
    """Verify NHLBoxscoreFetcher caches only final games with player data."""

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = None
        return mock

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    def _nhl_payload(
        self,
        game_state: str,
        forwards: list | None = None,
        defense: list | None = None,
        goalies: list | None = None,
    ) -> dict:
        return {
            "gameState": game_state,
            "gameDate": "2025-01-15",
            "homeTeam": {"abbrev": "BOS", "name": {"default": "Boston Bruins"}, "score": 3},
            "awayTeam": {"abbrev": "TOR", "name": {"default": "Toronto Maple Leafs"}, "score": 2},
            "playerByGameStats": {
                "homeTeam": {
                    "forwards": forwards or [],
                    "defense": defense or [],
                    "goalies": goalies or [],
                },
                "awayTeam": {
                    "forwards": [],
                    "defense": [],
                    "goalies": [],
                },
            },
        }

    def test_caches_off_game_with_players(self, client: MagicMock, cache: MagicMock) -> None:
        """'OFF' (completed) game with player data is cached."""
        payload = self._nhl_payload("OFF", forwards=[{"name": "Pastrnak"}])
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(2025020767)

        cache.put.assert_called_once()

    def test_caches_final_game_with_players(self, client: MagicMock, cache: MagicMock) -> None:
        """'FINAL' game with player data is cached."""
        payload = self._nhl_payload("FINAL", defense=[{"name": "McAvoy"}])
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(2025020767)

        cache.put.assert_called_once()

    def test_skips_cache_for_live_game(self, client: MagicMock, cache: MagicMock) -> None:
        """'LIVE' game is never cached."""
        payload = self._nhl_payload("LIVE", forwards=[{"name": "Pastrnak"}])
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(2025020767)

        cache.put.assert_not_called()

    def test_skips_cache_for_future_game(self, client: MagicMock, cache: MagicMock) -> None:
        """'FUT' game is never cached."""
        payload = self._nhl_payload("FUT")
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(2025020767)

        cache.put.assert_not_called()

    def test_skips_cache_for_pregame(self, client: MagicMock, cache: MagicMock) -> None:
        """'PRE' game is never cached."""
        payload = self._nhl_payload("PRE")
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(2025020767)

        cache.put.assert_not_called()

    def test_skips_cache_for_off_without_players(self, client: MagicMock, cache: MagicMock) -> None:
        """Completed game with empty player stats is not cached."""
        payload = self._nhl_payload("OFF", forwards=[], defense=[], goalies=[])
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(2025020767)

        cache.put.assert_not_called()

    def test_goalies_only_counts_as_data(self, client: MagicMock, cache: MagicMock) -> None:
        """Goalies-only roster still counts as having data."""
        payload = self._nhl_payload("OFF", goalies=[{"name": "Swayman"}])
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(2025020767)

        cache.put.assert_called_once()

    def test_uses_cached_response(self, client: MagicMock, cache: MagicMock) -> None:
        """Returns cached data without hitting the network."""
        payload = self._nhl_payload("OFF", forwards=[{"name": "Pastrnak"}])
        cache.get.return_value = payload

        fetcher = NHLBoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore(2025020767)

        client.get.assert_not_called()
        assert result is not None


# ---------------------------------------------------------------------------
# NHL PBP fetcher caching
# ---------------------------------------------------------------------------


class TestNHLPbpCaching:
    """Verify NHLPbpFetcher caches only final games with play data."""

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = None
        return mock

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    def _nhl_pbp_payload(self, game_state: str, n_plays: int = 3) -> dict:
        plays = [
            {
                "eventId": i,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": f"0{i}:00",
                "timeRemaining": f"{19 - i}:00",
                "situationCode": "1551",
                "typeDescKey": "shot-on-goal",
                "sortOrder": i,
                "details": {},
            }
            for i in range(1, n_plays + 1)
        ]
        return {"gameState": game_state, "plays": plays}

    def test_caches_off_game_with_plays(self, client: MagicMock, cache: MagicMock) -> None:
        """'OFF' game with play data is cached."""
        payload = self._nhl_pbp_payload("OFF", n_plays=5)
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(2025020767)

        cache.put.assert_called_once()

    def test_caches_final_game_with_plays(self, client: MagicMock, cache: MagicMock) -> None:
        """'FINAL' game with play data is cached."""
        payload = self._nhl_pbp_payload("FINAL", n_plays=5)
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(2025020767)

        cache.put.assert_called_once()

    def test_skips_cache_for_live_game(self, client: MagicMock, cache: MagicMock) -> None:
        """'LIVE' game with plays is not cached."""
        payload = self._nhl_pbp_payload("LIVE", n_plays=5)
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(2025020767)

        cache.put.assert_not_called()

    def test_skips_cache_for_future_game(self, client: MagicMock, cache: MagicMock) -> None:
        """'FUT' game is not cached."""
        payload = self._nhl_pbp_payload("FUT", n_plays=0)
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(2025020767)

        cache.put.assert_not_called()

    def test_skips_cache_for_off_without_plays(self, client: MagicMock, cache: MagicMock) -> None:
        """Completed game with empty play list is not cached."""
        payload = self._nhl_pbp_payload("OFF", n_plays=0)
        client.get.return_value = _make_http_response(payload)

        fetcher = NHLPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(2025020767)

        cache.put.assert_not_called()

    def test_uses_cached_response(self, client: MagicMock, cache: MagicMock) -> None:
        """Returns cached data without hitting the network."""
        payload = self._nhl_pbp_payload("OFF", n_plays=5)
        cache.get.return_value = payload

        fetcher = NHLPbpFetcher(client, cache)
        result = fetcher.fetch_play_by_play(2025020767)

        client.get.assert_not_called()
        assert len(result.plays) > 0


# ---------------------------------------------------------------------------
# NCAAB PBP fetcher caching
# ---------------------------------------------------------------------------


class TestNCAABPbpCaching:
    """Verify NCAABPbpFetcher caches only final games with play data."""

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = None
        return mock

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    def _plays_payload(self, n: int = 3) -> list:
        """Build a list of n minimal CBB play dicts."""
        return [
            {
                "period": 1,
                "sequenceNumber": i,
                "clock": f"{15 - i}:00",
                "playType": "JumpShot",
                "team": "Duke",
                "homeScore": i * 2,
                "awayScore": i,
                "description": f"Play {i}",
            }
            for i in range(1, n + 1)
        ]

    def test_caches_final_game_with_plays(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game with plays is cached."""
        payload = self._plays_payload(5)
        client.get.return_value = _make_http_response(payload)

        fetcher = NCAABPbpFetcher(client, cache)
        result = fetcher.fetch_play_by_play(12345, game_status="final")

        cache.put.assert_called_once()
        assert len(result.plays) == 5

    def test_skips_cache_for_live_game(self, client: MagicMock, cache: MagicMock) -> None:
        """Live game with plays is not cached."""
        payload = self._plays_payload(5)
        client.get.return_value = _make_http_response(payload)

        fetcher = NCAABPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(12345, game_status="live")

        cache.put.assert_not_called()

    def test_skips_cache_for_scheduled_game(self, client: MagicMock, cache: MagicMock) -> None:
        """Scheduled game is not cached even with plays."""
        payload = self._plays_payload(3)
        client.get.return_value = _make_http_response(payload)

        fetcher = NCAABPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(12345, game_status="scheduled")

        cache.put.assert_not_called()

    def test_skips_cache_when_status_none(self, client: MagicMock, cache: MagicMock) -> None:
        """Not cached when game_status is not provided."""
        payload = self._plays_payload(5)
        client.get.return_value = _make_http_response(payload)

        fetcher = NCAABPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(12345)

        cache.put.assert_not_called()

    def test_skips_cache_for_final_without_plays(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game with empty plays is not cached."""
        client.get.return_value = _make_http_response([])

        fetcher = NCAABPbpFetcher(client, cache)
        result = fetcher.fetch_play_by_play(12345, game_status="final")

        cache.put.assert_not_called()
        assert len(result.plays) == 0

    def test_uses_cached_response(self, client: MagicMock, cache: MagicMock) -> None:
        """Returns cached data without hitting the network."""
        payload = self._plays_payload(3)
        cache.get.return_value = payload

        fetcher = NCAABPbpFetcher(client, cache)
        result = fetcher.fetch_play_by_play(12345, game_status="final")

        client.get.assert_not_called()
        assert len(result.plays) == 3


# ---------------------------------------------------------------------------
# MLB boxscore fetcher caching
# ---------------------------------------------------------------------------


class TestMLBBoxscoreCaching:
    """Verify MLBBoxscoreFetcher caches only final games with player data."""

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = None
        return mock

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    def _mlb_payload(self, has_players: bool = True) -> dict:
        players = {"ID123": {"person": {"id": 123, "fullName": "Mike Trout"}}} if has_players else {}
        return {
            "teams": {
                "home": {
                    "team": {"id": 108, "name": "Los Angeles Angels", "abbreviation": "LAA"},
                    "players": players,
                    "batters": [123] if has_players else [],
                    "pitchers": [],
                    "teamStats": {"batting": {"runs": "5"}, "pitching": {}, "fielding": {}},
                },
                "away": {
                    "team": {"id": 117, "name": "Houston Astros", "abbreviation": "HOU"},
                    "players": {},
                    "batters": [],
                    "pitchers": [],
                    "teamStats": {"batting": {"runs": "3"}, "pitching": {}, "fielding": {}},
                },
            },
        }

    def test_caches_final_game_with_players(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game with player data is cached."""
        payload = self._mlb_payload(has_players=True)
        client.get.return_value = _make_http_response(payload)

        fetcher = MLBBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(717001, game_status="final")

        cache.put.assert_called_once()

    def test_skips_cache_for_live_game(self, client: MagicMock, cache: MagicMock) -> None:
        """Live game is never cached."""
        payload = self._mlb_payload(has_players=True)
        client.get.return_value = _make_http_response(payload)

        fetcher = MLBBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(717001, game_status="live")

        cache.put.assert_not_called()

    def test_skips_cache_when_status_none(self, client: MagicMock, cache: MagicMock) -> None:
        """Not cached when game_status is not provided."""
        payload = self._mlb_payload(has_players=True)
        client.get.return_value = _make_http_response(payload)

        fetcher = MLBBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(717001)

        cache.put.assert_not_called()

    def test_skips_cache_for_final_without_players(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game with empty players is not cached."""
        payload = self._mlb_payload(has_players=False)
        client.get.return_value = _make_http_response(payload)

        fetcher = MLBBoxscoreFetcher(client, cache)
        fetcher.fetch_boxscore(717001, game_status="final")

        cache.put.assert_not_called()

    def test_uses_cached_response(self, client: MagicMock, cache: MagicMock) -> None:
        """Returns cached data without hitting the network."""
        payload = self._mlb_payload(has_players=True)
        cache.get.return_value = payload

        fetcher = MLBBoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore(717001, game_status="final")

        client.get.assert_not_called()
        assert result is not None


# ---------------------------------------------------------------------------
# MLB PBP fetcher caching
# ---------------------------------------------------------------------------


class TestMLBPbpCaching:
    """Verify MLBPbpFetcher caches only final games with play data."""

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = None
        return mock

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    def _pbp_payload(self, n_plays: int = 3) -> dict:
        plays = [
            {
                "about": {"inning": 1, "isTopInning": True, "atBatIndex": i},
                "result": {
                    "eventType": "single",
                    "event": "Single",
                    "description": f"Play {i}",
                    "homeScore": 0,
                    "awayScore": 0,
                },
                "matchup": {
                    "batter": {"id": 100 + i, "fullName": f"Batter {i}"},
                    "pitcher": {"id": 200 + i, "fullName": f"Pitcher {i}"},
                },
            }
            for i in range(1, n_plays + 1)
        ]
        return {"allPlays": plays}

    def test_caches_final_game_with_plays(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game with plays is cached."""
        payload = self._pbp_payload(5)
        client.get.return_value = _make_http_response(payload)

        fetcher = MLBPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(717001, game_status="final")

        cache.put.assert_called_once()

    def test_skips_cache_for_live_game(self, client: MagicMock, cache: MagicMock) -> None:
        """Live game with plays is not cached."""
        payload = self._pbp_payload(5)
        client.get.return_value = _make_http_response(payload)

        fetcher = MLBPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(717001, game_status="live")

        cache.put.assert_not_called()

    def test_skips_cache_when_status_none(self, client: MagicMock, cache: MagicMock) -> None:
        """Not cached when game_status is not provided."""
        payload = self._pbp_payload(5)
        client.get.return_value = _make_http_response(payload)

        fetcher = MLBPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(717001)

        cache.put.assert_not_called()

    def test_skips_cache_for_final_without_plays(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game with empty plays is not cached."""
        client.get.return_value = _make_http_response({"allPlays": []})

        fetcher = MLBPbpFetcher(client, cache)
        fetcher.fetch_play_by_play(717001, game_status="final")

        cache.put.assert_not_called()

    def test_uses_cached_response(self, client: MagicMock, cache: MagicMock) -> None:
        """Returns cached data without hitting the network."""
        payload = self._pbp_payload(3)
        cache.get.return_value = payload

        fetcher = MLBPbpFetcher(client, cache)
        result = fetcher.fetch_play_by_play(717001, game_status="final")

        client.get.assert_not_called()
        assert len(result.plays) == 3


# ---------------------------------------------------------------------------
# MLB Boxscore status threading
# ---------------------------------------------------------------------------


class TestMLBBoxscoreStatus:
    """Verify MLBBoxscoreFetcher threads game_status to the parsed result."""

    @pytest.fixture
    def cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = None
        return mock

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    def _mlb_payload(self) -> dict:
        return {
            "teams": {
                "home": {
                    "team": {"id": 108, "name": "Los Angeles Angels", "abbreviation": "LAA"},
                    "players": {"ID123": {"person": {"id": 123, "fullName": "Mike Trout"}}},
                    "batters": [123],
                    "pitchers": [],
                    "teamStats": {"batting": {"runs": "5"}, "pitching": {}, "fielding": {}},
                },
                "away": {
                    "team": {"id": 117, "name": "Houston Astros", "abbreviation": "HOU"},
                    "players": {},
                    "batters": [],
                    "pitchers": [],
                    "teamStats": {"batting": {"runs": "3"}, "pitching": {}, "fielding": {}},
                },
            },
        }

    def test_final_status_passed_through(self, client: MagicMock, cache: MagicMock) -> None:
        """Final game_status is reflected in the parsed MLBBoxscore."""
        client.get.return_value = _make_http_response(self._mlb_payload())

        fetcher = MLBBoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore(717001, game_status="final")

        assert result is not None
        assert result.status == "final"

    def test_live_status_preserved(self, client: MagicMock, cache: MagicMock) -> None:
        """Live game_status is NOT overridden to 'final'."""
        client.get.return_value = _make_http_response(self._mlb_payload())

        fetcher = MLBBoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore(717001, game_status="live")

        assert result is not None
        assert result.status == "live"

    def test_scheduled_status_preserved(self, client: MagicMock, cache: MagicMock) -> None:
        """Scheduled game_status is NOT overridden to 'final'."""
        client.get.return_value = _make_http_response(self._mlb_payload())

        fetcher = MLBBoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore(717001, game_status="scheduled")

        assert result is not None
        assert result.status == "scheduled"

    def test_none_status_defaults_to_scheduled(self, client: MagicMock, cache: MagicMock) -> None:
        """When game_status is None, defaults to 'scheduled' (safe, no premature finalization)."""
        client.get.return_value = _make_http_response(self._mlb_payload())

        fetcher = MLBBoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore(717001)

        assert result is not None
        assert result.status == "scheduled"

    def test_game_date_is_none(self, client: MagicMock, cache: MagicMock) -> None:
        """game_date is None since the boxscore endpoint doesn't provide it."""
        client.get.return_value = _make_http_response(self._mlb_payload())

        fetcher = MLBBoxscoreFetcher(client, cache)
        result = fetcher.fetch_boxscore(717001, game_status="final")

        assert result is not None
        assert result.game_date is None
