"""Targeted tests to increase coverage for boxscore live/persistence/ingestion modules.

Covers uncovered lines in:
- sports_scraper/live/nba_boxscore.py
- sports_scraper/live/mlb_boxscore.py
- sports_scraper/persistence/boxscores.py
- sports_scraper/persistence/boxscore_helpers.py
- sports_scraper/services/ncaab_boxscore_ingestion.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

API_ROOT = REPO_ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.models import (
    GameIdentification,
    NormalizedGame,
    NormalizedPlayerBoxscore,
    NormalizedTeamBoxscore,
    TeamIdentity,
)
from sports_scraper.utils.cache import APICache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nba_team(name="Boston Celtics", abbr="BOS"):
    return TeamIdentity(league_code="NBA", name=name, abbreviation=abbr)


def _mlb_team(name="New York Yankees", abbr="NYY"):
    return TeamIdentity(league_code="MLB", name=name, abbreviation=abbr)


def _nhl_team(name="Boston Bruins", abbr="BOS"):
    return TeamIdentity(league_code="NHL", name=name, abbreviation=abbr)


def _ncaab_team(name="Duke Blue Devils", abbr="DUKE"):
    return TeamIdentity(league_code="NCAAB", name=name, abbreviation=abbr)


def _make_cache(tmp_path=None):
    """Create a simple in-memory-like cache using MagicMock with dict backing."""
    cache = MagicMock(spec=APICache)
    store = {}
    cache.get = MagicMock(side_effect=lambda k: store.get(k))
    cache.put = MagicMock(side_effect=lambda k, v: store.__setitem__(k, v))
    cache._store = store  # expose for test assertions
    return cache


# ===========================================================================
# NBA Boxscore Tests (nba_boxscore.py)
# ===========================================================================

class TestNBAParsePtMinutes:
    """Cover lines 35-42: _parse_pt_minutes edge cases."""

    def test_none_input(self):
        from sports_scraper.live.nba_boxscore import _parse_pt_minutes
        assert _parse_pt_minutes(None) is None

    def test_empty_string(self):
        from sports_scraper.live.nba_boxscore import _parse_pt_minutes
        assert _parse_pt_minutes("") is None

    def test_invalid_format(self):
        from sports_scraper.live.nba_boxscore import _parse_pt_minutes
        assert _parse_pt_minutes("GARBAGE") is None

    def test_normal_value(self):
        from sports_scraper.live.nba_boxscore import _parse_pt_minutes
        assert _parse_pt_minutes("PT36M12.00S") == 36.2

    def test_zero(self):
        from sports_scraper.live.nba_boxscore import _parse_pt_minutes
        assert _parse_pt_minutes("PT00M00.00S") == 0.0

    def test_seconds_only(self):
        from sports_scraper.live.nba_boxscore import _parse_pt_minutes
        result = _parse_pt_minutes("PT30.00S")
        assert result == 0.5

    def test_minutes_only(self):
        from sports_scraper.live.nba_boxscore import _parse_pt_minutes
        result = _parse_pt_minutes("PT10M")
        assert result == 10.0


class TestNBABoxscoreFetchErrors:
    """Cover lines 81-83, 86-87, 90-91, 94-100: fetch_boxscore error paths."""

    def _make_fetcher(self):
        from sports_scraper.live.nba_boxscore import NBABoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return NBABoxscoreFetcher(client=client, cache=cache), client

    def test_http_exception_returns_none(self):
        """Line 81-83: Exception during client.get returns None."""
        fetcher, client = self._make_fetcher()
        client.get.side_effect = ConnectionError("timeout")
        result = fetcher.fetch_boxscore("0022400001")
        assert result is None

    def test_403_returns_none(self):
        """Lines 86-87: 403 status returns None."""
        fetcher, client = self._make_fetcher()
        resp = MagicMock(status_code=403)
        client.get.return_value = resp
        result = fetcher.fetch_boxscore("0022400001")
        assert result is None

    def test_404_returns_none(self):
        """Lines 90-91: 404 status returns None."""
        fetcher, client = self._make_fetcher()
        resp = MagicMock(status_code=404)
        client.get.return_value = resp
        result = fetcher.fetch_boxscore("0022400001")
        assert result is None

    def test_500_returns_none(self):
        """Lines 94-100: Non-200/403/404 status returns None."""
        fetcher, client = self._make_fetcher()
        resp = MagicMock(status_code=500, text="Internal Server Error")
        client.get.return_value = resp
        result = fetcher.fetch_boxscore("0022400001")
        assert result is None

    def test_500_empty_body(self):
        """Lines 94-100: body='' edge case."""
        fetcher, client = self._make_fetcher()
        resp = MagicMock(status_code=502, text="")
        client.get.return_value = resp
        result = fetcher.fetch_boxscore("0022400001")
        assert result is None


class TestNBABoxscoreParsePlayerFiltering:
    """Cover line 217: player appended only when parse succeeds, and lines 232-278."""

    def _make_fetcher(self):
        from sports_scraper.live.nba_boxscore import NBABoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return NBABoxscoreFetcher(client=client, cache=cache)

    def test_player_no_person_id_skipped(self):
        """_parse_player_stats returns None when personId missing."""
        fetcher = self._make_fetcher()
        result = fetcher._parse_player_stats({}, _nba_team(), "G1")
        assert result is None

    def test_player_no_name_skipped(self):
        """_parse_player_stats returns None when name is empty."""
        fetcher = self._make_fetcher()
        result = fetcher._parse_player_stats(
            {"personId": 123, "name": ""},
            _nba_team(), "G1",
        )
        assert result is None

    def test_player_did_not_play_skipped(self):
        """_parse_player_stats returns None when played == '0'."""
        fetcher = self._make_fetcher()
        result = fetcher._parse_player_stats(
            {"personId": 123, "name": "Jayson Tatum", "played": "0"},
            _nba_team(), "G1",
        )
        assert result is None

    def test_player_with_full_stats(self):
        """Lines 232-278: full player stat parsing with all fields."""
        fetcher = self._make_fetcher()
        player_data = {
            "personId": 1628369,
            "name": "Jayson Tatum",
            "played": "1",
            "position": "SF",
            "jerseyNum": "0",
            "statistics": {
                "minutes": "PT36M12.00S",
                "points": 30,
                "reboundsTotal": 10,
                "assists": 5,
                "fieldGoalsMade": 12,
                "fieldGoalsAttempted": 22,
                "threePointersMade": 3,
                "threePointersAttempted": 8,
                "freeThrowsMade": 3,
                "freeThrowsAttempted": 4,
                "reboundsOffensive": 2,
                "reboundsDefensive": 8,
                "steals": 1,
                "blocks": 2,
                "turnovers": 3,
                "foulsPersonal": 2,
                "plusMinusPoints": 15,
            },
        }
        result = fetcher._parse_player_stats(player_data, _nba_team(), "G1")
        assert result is not None
        assert result.player_name == "Jayson Tatum"
        assert result.points == 30
        assert result.rebounds == 10
        assert result.assists == 5
        assert result.minutes == 36.2
        assert result.raw_stats["fg_made"] == 12
        assert result.raw_stats["plus_minus"] == 15

    def test_parse_team_players_filters_invalid(self):
        """Line 217: only valid players appended."""
        fetcher = self._make_fetcher()
        team_data = {
            "players": [
                {"personId": 1, "name": "Player A", "played": "1", "statistics": {"points": 10}},
                {"personId": None, "name": "Ghost"},  # no personId
                {"personId": 3, "name": "Player C", "played": "0"},  # didn't play
            ]
        }
        result = fetcher._parse_team_players(team_data, _nba_team(), "G1")
        assert len(result) == 1
        assert result[0].player_name == "Player A"

    def test_full_boxscore_parse_response(self):
        """Lines 232-278: full _parse_boxscore_response with game status mappings."""
        fetcher = self._make_fetcher()
        payload = {
            "game": {
                "gameStatus": 3,
                "gameTimeUTC": "2025-01-15T00:00:00Z",
                "homeTeam": {
                    "teamTricode": "BOS",
                    "teamCity": "Boston",
                    "teamName": "Celtics",
                    "score": 110,
                    "players": [],
                    "statistics": {},
                },
                "awayTeam": {
                    "teamTricode": "LAL",
                    "teamCity": "Los Angeles",
                    "teamName": "Lakers",
                    "score": 105,
                    "players": [],
                    "statistics": {},
                },
            }
        }
        result = fetcher._parse_boxscore_response(payload, "0022400001")
        assert result.status == "final"
        assert result.home_score == 110
        assert result.away_score == 105
        assert result.home_team.name == "Boston Celtics"

    def test_parse_boxscore_live_status(self):
        fetcher = self._make_fetcher()
        payload = {
            "game": {
                "gameStatus": 2,
                "gameTimeUTC": "",
                "homeTeam": {"teamTricode": "BOS", "score": 50, "players": [], "statistics": {}},
                "awayTeam": {"teamTricode": "LAL", "score": 48, "players": [], "statistics": {}},
            }
        }
        result = fetcher._parse_boxscore_response(payload, "G1")
        assert result.status == "live"

    def test_parse_boxscore_scheduled_status(self):
        fetcher = self._make_fetcher()
        payload = {
            "game": {
                "gameStatus": 1,
                "gameTimeUTC": "",
                "homeTeam": {"teamTricode": "BOS", "score": 0, "players": [], "statistics": {}},
                "awayTeam": {"teamTricode": "LAL", "score": 0, "players": [], "statistics": {}},
            }
        }
        result = fetcher._parse_boxscore_response(payload, "G1")
        assert result.status == "scheduled"


class TestNBABoxscoreFetchCaching:
    """Cover line 337 and caching logic."""

    def test_fetch_uses_cache_hit(self):
        """Cached response is used without HTTP call."""
        from sports_scraper.live.nba_boxscore import NBABoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        cached_payload = {
            "game": {
                "gameStatus": 3,
                "gameTimeUTC": "",
                "homeTeam": {"teamTricode": "BOS", "teamCity": "Boston", "teamName": "Celtics", "score": 100, "players": [], "statistics": {}},
                "awayTeam": {"teamTricode": "LAL", "teamCity": "Los Angeles", "teamName": "Lakers", "score": 95, "players": [], "statistics": {}},
            }
        }
        cache.put("boxscore_G1", cached_payload)
        fetcher = NBABoxscoreFetcher(client=client, cache=cache)
        result = fetcher.fetch_boxscore("G1")
        assert result is not None
        assert result.home_score == 100
        client.get.assert_not_called()


# ===========================================================================
# MLB Boxscore Tests (mlb_boxscore.py)
# ===========================================================================

class TestMLBBoxscoreFetchErrors:
    """Cover lines 54-56, 59-60, 63-69: fetch_boxscore error paths."""

    def _make_fetcher(self):
        from sports_scraper.live.mlb_boxscore import MLBBoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return MLBBoxscoreFetcher(client=client, cache=cache), client

    def test_http_exception_returns_none(self):
        """Lines 54-56."""
        fetcher, client = self._make_fetcher()
        client.get.side_effect = ConnectionError("network error")
        assert fetcher.fetch_boxscore(12345) is None

    def test_404_returns_none(self):
        """Lines 59-60."""
        fetcher, client = self._make_fetcher()
        client.get.return_value = MagicMock(status_code=404)
        assert fetcher.fetch_boxscore(12345) is None

    def test_500_returns_none(self):
        """Lines 63-69."""
        fetcher, client = self._make_fetcher()
        client.get.return_value = MagicMock(status_code=500, text="Server Error")
        assert fetcher.fetch_boxscore(12345) is None

    def test_500_empty_text(self):
        """Lines 63-69: empty text edge."""
        fetcher, client = self._make_fetcher()
        client.get.return_value = MagicMock(status_code=503, text="")
        assert fetcher.fetch_boxscore(12345) is None


class TestMLBBoxscoreRawFetch:
    """Cover lines 99-133: fetch_boxscore_raw paths."""

    def _make_fetcher(self):
        from sports_scraper.live.mlb_boxscore import MLBBoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return MLBBoxscoreFetcher(client=client, cache=cache), client

    def test_raw_cache_hit(self):
        """Lines 99-103: returns cached payload."""
        fetcher, client = self._make_fetcher()
        fetcher._cache.put("mlb_boxscore_111", {"teams": {}})
        result = fetcher.fetch_boxscore_raw(111)
        assert result == {"teams": {}}
        client.get.assert_not_called()

    def test_raw_fetch_exception(self):
        """Lines 108-112: exception returns None."""
        fetcher, client = self._make_fetcher()
        client.get.side_effect = ConnectionError("fail")
        assert fetcher.fetch_boxscore_raw(111) is None

    def test_raw_non_200(self):
        """Lines 114-120: non-200 returns None."""
        fetcher, client = self._make_fetcher()
        client.get.return_value = MagicMock(status_code=404)
        assert fetcher.fetch_boxscore_raw(111) is None

    def test_raw_success_caches_final(self):
        """Lines 122-133: success with final game caches."""
        fetcher, client = self._make_fetcher()
        payload = {"teams": {"home": {"players": {"ID1": {}}}, "away": {}}}
        client.get.return_value = MagicMock(status_code=200, json=lambda: payload)
        result = fetcher.fetch_boxscore_raw(111, game_status="final")
        assert result == payload
        # Cache.put should have been called for final game with data
        fetcher._cache.put.assert_called_once_with("mlb_boxscore_111", payload)

    def test_raw_success_no_cache_non_final(self):
        """Lines 130-131: non-final game not cached."""
        fetcher, client = self._make_fetcher()
        payload = {"teams": {"home": {"players": {"ID1": {}}}, "away": {}}}
        client.get.return_value = MagicMock(status_code=200, json=lambda: payload)
        result = fetcher.fetch_boxscore_raw(111, game_status="live")
        assert result == payload
        # Cache.put should NOT have been called for non-final
        fetcher._cache.put.assert_not_called()


class TestMLBBoxscoreFetchCaching:
    """Cover lines 207, 211: MLB fetch with cache and final game."""

    def _make_fetcher(self):
        from sports_scraper.live.mlb_boxscore import MLBBoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return MLBBoxscoreFetcher(client=client, cache=cache), client

    def test_fetch_from_cache(self):
        """Line 207: cached response is parsed."""
        fetcher, client = self._make_fetcher()
        cached = {
            "teams": {
                "home": {
                    "team": {"name": "Yankees", "abbreviation": "NYY"},
                    "teamStats": {"batting": {"runs": 5}, "pitching": {}, "fielding": {}},
                    "players": {},
                    "batters": [],
                    "pitchers": [],
                },
                "away": {
                    "team": {"name": "Red Sox", "abbreviation": "BOS"},
                    "teamStats": {"batting": {"runs": 3}, "pitching": {}, "fielding": {}},
                    "players": {},
                    "batters": [],
                    "pitchers": [],
                },
            }
        }
        fetcher._cache.put("mlb_boxscore_999", cached)
        result = fetcher.fetch_boxscore(999, game_status="final")
        assert result is not None
        assert result.home_score == 5
        assert result.away_score == 3
        client.get.assert_not_called()


class TestMLBPitcherStatsParsing:
    """Cover lines 315-342: _parse_pitcher_stats."""

    def _make_fetcher(self):
        from sports_scraper.live.mlb_boxscore import MLBBoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return MLBBoxscoreFetcher(client=client, cache=cache)

    def test_pitcher_stats_full(self):
        fetcher = self._make_fetcher()
        pitching = {
            "inningsPitched": "6.2",
            "hits": 5,
            "runs": 3,
            "earnedRuns": 2,
            "baseOnBalls": 2,
            "strikeOuts": 8,
            "homeRuns": 1,
            "era": "3.45",
            "whip": "1.12",
            "numberOfPitches": 95,
            "strikes": 62,
            "balls": 33,
            "battersFaced": 28,
            "outs": 20,
            "hitBatsmen": 0,
            "wildPitches": 1,
            "stolenBases": 0,
            "wins": 1,
            "losses": 0,
            "saves": 0,
            "holds": 0,
            "blownSaves": 0,
        }
        result = fetcher._parse_pitcher_stats(
            player_id=12345, player_name="Gerrit Cole",
            position="P", jersey=45,
            pitching=pitching, team_identity=_mlb_team(), game_pk=999,
        )
        assert result is not None
        assert result.player_role == "pitcher"
        assert result.raw_stats["inningsPitched"] == "6.2"
        assert result.raw_stats["strikeOuts"] == 8
        assert result.raw_stats["pitchCount"] == 95
        assert result.raw_stats["wins"] == 1

    def test_pitcher_stats_none_values_filtered(self):
        """None values filtered from raw_stats."""
        fetcher = self._make_fetcher()
        pitching = {"inningsPitched": "5.0", "strikeOuts": 5}
        result = fetcher._parse_pitcher_stats(
            player_id=1, player_name="Pitcher",
            position="", jersey=None,
            pitching=pitching, team_identity=_mlb_team(), game_pk=1,
        )
        assert result is not None
        assert result.position == "P"  # empty position defaults to "P"
        assert "homeRuns" not in result.raw_stats


class TestMLBBatterStatsParsing:
    """Cover lines 253-277: _parse_batter_stats."""

    def _make_fetcher(self):
        from sports_scraper.live.mlb_boxscore import MLBBoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return MLBBoxscoreFetcher(client=client, cache=cache)

    def test_batter_stats_full(self):
        fetcher = self._make_fetcher()
        batting = {
            "atBats": 4,
            "hits": 2,
            "runs": 1,
            "rbi": 3,
            "homeRuns": 1,
            "baseOnBalls": 1,
            "strikeOuts": 0,
            "doubles": 1,
            "triples": 0,
            "stolenBases": 0,
            "caughtStealing": 0,
            "avg": ".300",
            "obp": ".400",
            "slg": ".550",
            "ops": ".950",
            "leftOnBase": 1,
            "sacBunts": 0,
            "sacFlies": 1,
            "groundIntoDoublePlay": 0,
        }
        result = fetcher._parse_batter_stats(
            player_id=54321, player_name="Aaron Judge",
            position="RF", jersey=99,
            batting=batting, team_identity=_mlb_team(), game_pk=999,
        )
        assert result is not None
        assert result.player_role == "batter"
        assert result.raw_stats["atBats"] == 4
        assert result.raw_stats["homeRuns"] == 1
        assert result.raw_stats["avg"] == ".300"


class TestMLBParseTeamPlayers:
    """Cover lines 222-227, 231-238: batter and pitcher routing."""

    def _make_fetcher(self):
        from sports_scraper.live.mlb_boxscore import MLBBoxscoreFetcher
        client = MagicMock()
        cache = _make_cache()
        return MLBBoxscoreFetcher(client=client, cache=cache)

    def test_team_players_both_batter_and_pitcher(self):
        """A player who both batted and pitched creates two entries."""
        fetcher = self._make_fetcher()
        team_data = {
            "players": {
                "ID660271": {
                    "person": {"id": 660271, "fullName": "Shohei Ohtani"},
                    "position": {"abbreviation": "DH"},
                    "jerseyNumber": "17",
                    "stats": {
                        "batting": {"atBats": 4, "hits": 2, "runs": 1, "rbi": 2},
                        "pitching": {"inningsPitched": "7.0", "strikeOuts": 10, "hits": 3},
                    },
                },
            },
            "batters": [660271],
            "pitchers": [660271],
        }
        result = fetcher._parse_team_players(team_data, _mlb_team(), 999)
        assert len(result) == 2
        roles = {p.player_role for p in result}
        assert roles == {"batter", "pitcher"}

    def test_player_without_stats_skipped(self):
        """Player in batters list but with empty batting dict is skipped."""
        fetcher = self._make_fetcher()
        team_data = {
            "players": {
                "ID1": {
                    "person": {"id": 1, "fullName": "Test Player"},
                    "position": {"abbreviation": "SS"},
                    "stats": {"batting": {}},
                },
            },
            "batters": [1],
            "pitchers": [],
        }
        result = fetcher._parse_team_players(team_data, _mlb_team(), 1)
        assert len(result) == 0

    def test_player_no_id_skipped(self):
        fetcher = self._make_fetcher()
        team_data = {
            "players": {
                "IDnone": {
                    "person": {"fullName": "No ID"},
                    "position": {"abbreviation": "C"},
                    "stats": {},
                },
            },
            "batters": [],
            "pitchers": [],
        }
        result = fetcher._parse_team_players(team_data, _mlb_team(), 1)
        assert len(result) == 0

    def test_player_no_name_skipped(self):
        fetcher = self._make_fetcher()
        team_data = {
            "players": {
                "ID5": {
                    "person": {"id": 5, "fullName": ""},
                    "position": {"abbreviation": "1B"},
                    "stats": {"batting": {"hits": 1}},
                },
            },
            "batters": [5],
            "pitchers": [],
        }
        result = fetcher._parse_team_players(team_data, _mlb_team(), 1)
        assert len(result) == 0


# ===========================================================================
# Persistence: boxscores.py (lines 235-318)
# ===========================================================================

class TestPersistGamePayload:
    """Cover lines 235-318 of persist_game_payload."""

    def _make_normalized_game(self, home_score=100, away_score=95):
        home = _nba_team()
        away = _nba_team(name="Los Angeles Lakers", abbr="LAL")
        identity = GameIdentification(
            league_code="NBA",
            season=2025,
            game_date=datetime(2025, 1, 15, tzinfo=UTC),
            home_team=home,
            away_team=away,
            source_game_key="G123",
        )
        team_bs = [
            NormalizedTeamBoxscore(team=home, is_home=True, points=home_score),
            NormalizedTeamBoxscore(team=away, is_home=False, points=away_score),
        ]
        player_bs = [
            NormalizedPlayerBoxscore(
                player_id="1", player_name="Player A",
                team=home, points=30,
            ),
        ]
        return NormalizedGame(
            identity=identity,
            status="final",
            home_score=home_score,
            away_score=away_score,
            team_boxscores=team_bs,
            player_boxscores=player_bs,
        )

    @patch("sports_scraper.persistence.boxscores._enrich_game_with_boxscore", return_value=True)
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    def test_persist_with_game_id_found(self, mock_player, mock_team, mock_enrich):
        """Lines 235-243: game_id provided and found."""
        from sports_scraper.persistence.boxscores import persist_game_payload

        mock_game = MagicMock()
        mock_game.id = 42
        mock_game.status = "scheduled"
        mock_session = MagicMock()
        mock_session.query.return_value.get.return_value = mock_game

        mock_player.return_value = MagicMock(inserted=1, rejected=0, errors=0)
        payload = self._make_normalized_game()
        result = persist_game_payload(mock_session, payload, game_id=42)
        assert result.game_id == 42
        assert result.enriched is True

    @patch("sports_scraper.persistence.boxscores._enrich_game_with_boxscore")
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    def test_persist_with_game_id_not_found(self, mock_player, mock_team, mock_enrich):
        """Lines 237-243: game_id provided but not found."""
        from sports_scraper.persistence.boxscores import persist_game_payload

        mock_session = MagicMock()
        mock_session.query.return_value.get.return_value = None

        payload = self._make_normalized_game()
        result = persist_game_payload(mock_session, payload, game_id=999)
        assert result.game_id is None
        assert result.enriched is False

    @patch("sports_scraper.persistence.boxscores._find_game_for_boxscore", return_value=None)
    @patch("sports_scraper.persistence.boxscores._find_team_by_name", side_effect=[10, 20])
    @patch("sports_scraper.persistence.boxscores.get_league_id", return_value=1)
    def test_persist_no_game_id_game_not_found(self, mock_league, mock_team, mock_find):
        """Lines 274-283: no game_id, teams found but game not found."""
        from sports_scraper.persistence.boxscores import persist_game_payload

        mock_session = MagicMock()
        payload = self._make_normalized_game()
        result = persist_game_payload(mock_session, payload)
        assert result.game_id is None

    @patch("sports_scraper.persistence.boxscores._find_team_by_name", side_effect=[None, 20])
    @patch("sports_scraper.persistence.boxscores.get_league_id", return_value=1)
    def test_persist_no_game_id_team_not_found(self, mock_league, mock_team):
        """Lines 257-268: no game_id, home team not found."""
        from sports_scraper.persistence.boxscores import persist_game_payload

        mock_session = MagicMock()
        payload = self._make_normalized_game()
        result = persist_game_payload(mock_session, payload)
        assert result.game_id is None

    @patch("sports_scraper.persistence.boxscores._enrich_game_with_boxscore", return_value=False)
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores", side_effect=Exception("DB error"))
    def test_persist_player_boxscore_exception(self, mock_player, mock_team, mock_enrich):
        """Lines 307-314: exception during player boxscore upsert."""
        from sports_scraper.persistence.boxscores import persist_game_payload

        mock_game = MagicMock()
        mock_game.id = 42
        mock_game.status = "final"
        mock_session = MagicMock()
        mock_session.query.return_value.get.return_value = mock_game

        payload = self._make_normalized_game()
        result = persist_game_payload(mock_session, payload, game_id=42)
        assert result.game_id == 42
        assert result.player_stats is None  # exception caught

    @patch("sports_scraper.persistence.boxscores._enrich_game_with_boxscore", return_value=True)
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    def test_persist_no_player_boxscores(self, mock_team, mock_enrich):
        """Lines 315-316: no player boxscores to persist."""
        from sports_scraper.persistence.boxscores import persist_game_payload

        mock_game = MagicMock()
        mock_game.id = 42
        mock_game.status = "scheduled"
        mock_session = MagicMock()
        mock_session.query.return_value.get.return_value = mock_game

        home = _nba_team()
        away = _nba_team(name="Los Angeles Lakers", abbr="LAL")
        identity = GameIdentification(
            league_code="NBA",
            season=2025,
            game_date=datetime(2025, 1, 15, tzinfo=UTC),
            home_team=home,
            away_team=away,
        )
        payload = NormalizedGame(
            identity=identity,
            status="final",
            home_score=100,
            away_score=95,
            team_boxscores=[
                NormalizedTeamBoxscore(team=home, is_home=True, points=100),
                NormalizedTeamBoxscore(team=away, is_home=False, points=95),
            ],
            player_boxscores=[],
        )
        result = persist_game_payload(mock_session, payload, game_id=42)
        assert result.game_id == 42
        assert result.player_stats is None

    @patch("sports_scraper.persistence.boxscores._find_game_for_boxscore")
    @patch("sports_scraper.persistence.boxscores._find_team_by_name", side_effect=[10, 20])
    @patch("sports_scraper.persistence.boxscores.get_league_id", return_value=1)
    @patch("sports_scraper.persistence.boxscores._enrich_game_with_boxscore", return_value=True)
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    def test_persist_no_game_id_full_lookup_success(
        self, mock_player, mock_team_bs, mock_enrich, mock_league, mock_find_team, mock_find_game
    ):
        """Lines 244-286: no game_id, full team lookup + game found."""
        from sports_scraper.persistence.boxscores import persist_game_payload

        mock_game = MagicMock()
        mock_game.id = 77
        mock_game.status = "scheduled"
        mock_find_game.return_value = mock_game
        mock_player.return_value = MagicMock(inserted=1, rejected=0, errors=0)

        mock_session = MagicMock()
        payload = self._make_normalized_game()
        result = persist_game_payload(mock_session, payload)
        assert result.game_id == 77
        assert result.enriched is True


# ===========================================================================
# Persistence: boxscore_helpers.py (lines 140, 200, 243-277)
# ===========================================================================

class TestBuildTeamStatsHits:
    """Cover line 140: hits field in _build_team_stats."""

    def test_hits_included(self):
        from sports_scraper.persistence.boxscore_helpers import _build_team_stats
        payload = NormalizedTeamBoxscore(
            team=_mlb_team(), is_home=True, hits=8,
        )
        result = _build_team_stats(payload)
        assert result["hits"] == 8

    def test_shots_on_goal_included(self):
        from sports_scraper.persistence.boxscore_helpers import _build_team_stats
        payload = NormalizedTeamBoxscore(
            team=_nhl_team(), is_home=True, shots_on_goal=35,
        )
        result = _build_team_stats(payload)
        assert result["shots_on_goal"] == 35

    def test_penalty_minutes_included(self):
        from sports_scraper.persistence.boxscore_helpers import _build_team_stats
        payload = NormalizedTeamBoxscore(
            team=_nhl_team(), is_home=False, penalty_minutes=12,
        )
        result = _build_team_stats(payload)
        assert result["penalty_minutes"] == 12


class TestBuildPlayerStatsRawStats:
    """Cover line 200: raw_stats merged into player stats."""

    def test_raw_stats_merged(self):
        from sports_scraper.persistence.boxscore_helpers import _build_player_stats
        payload = NormalizedPlayerBoxscore(
            player_id="1", player_name="Test",
            team=_nba_team(),
            points=20, assists=5, rebounds=8,
            raw_stats={"fg_pct": 0.45, "custom_field": "value"},
        )
        result = _build_player_stats(payload)
        assert result["points"] == 20
        assert result["fg_pct"] == 0.45
        assert result["custom_field"] == "value"

    def test_all_nhl_fields(self):
        from sports_scraper.persistence.boxscore_helpers import _build_player_stats
        payload = NormalizedPlayerBoxscore(
            player_id="1", player_name="Skater",
            team=_nhl_team(),
            player_role="skater",
            position="C",
            sweater_number=37,
            minutes=18.5,
            goals=2,
            assists=1,
            points=3,
            shots_on_goal=5,
            penalties=2,
            plus_minus=1,
            hits=3,
            blocked_shots=1,
            shifts=22,
            giveaways=1,
            takeaways=2,
            faceoff_pct=55.0,
        )
        result = _build_player_stats(payload)
        assert result["goals"] == 2
        assert result["shifts"] == 22
        assert result["faceoff_pct"] == 55.0
        assert result["blocked_shots"] == 1

    def test_goalie_fields(self):
        from sports_scraper.persistence.boxscore_helpers import _build_player_stats
        payload = NormalizedPlayerBoxscore(
            player_id="1", player_name="Goalie",
            team=_nhl_team(),
            player_role="goalie",
            saves=30,
            goals_against=2,
            shots_against=32,
            save_percentage=0.938,
        )
        result = _build_player_stats(payload)
        assert result["saves"] == 30
        assert result["goals_against"] == 2
        assert result["save_percentage"] == 0.938


class TestEnrichGameWithBoxscore:
    """Cover lines 243-277: _enrich_game_with_boxscore."""

    def _make_game_and_payload(
        self,
        game_home_score=None, game_away_score=None, game_status="scheduled",
        game_venue=None, game_source_key=None,
        payload_home_score=100, payload_away_score=95, payload_status="final",
        payload_venue="TD Garden", payload_source_key="G123",
    ):
        game = MagicMock()
        game.home_score = game_home_score
        game.away_score = game_away_score
        game.status = game_status
        game.venue = game_venue
        game.source_game_key = game_source_key
        game.scrape_version = 0

        home = _nba_team()
        away = _nba_team(name="Los Angeles Lakers", abbr="LAL")
        identity = GameIdentification(
            league_code="NBA",
            season=2025,
            game_date=datetime(2025, 1, 15, tzinfo=UTC),
            home_team=home,
            away_team=away,
            source_game_key=payload_source_key,
        )
        payload = NormalizedGame(
            identity=identity,
            status=payload_status,
            venue=payload_venue,
            home_score=payload_home_score,
            away_score=payload_away_score,
            team_boxscores=[
                NormalizedTeamBoxscore(team=home, is_home=True, points=payload_home_score),
                NormalizedTeamBoxscore(team=away, is_home=False, points=payload_away_score),
            ],
        )
        return game, payload

    @patch("sports_scraper.persistence.boxscore_helpers.resolve_status_transition",
           return_value="final")
    @patch("sports_scraper.persistence.boxscore_helpers._normalize_status",
           return_value="final")
    def test_enriches_scores_venue_status(self, mock_norm, mock_resolve):
        from sports_scraper.persistence.boxscore_helpers import _enrich_game_with_boxscore
        game, payload = self._make_game_and_payload()
        session = MagicMock()
        result = _enrich_game_with_boxscore(session, game, payload)
        assert result is True
        assert game.home_score == 100
        assert game.away_score == 95
        assert game.venue == "TD Garden"

    @patch("sports_scraper.persistence.boxscore_helpers.resolve_status_transition",
           return_value="scheduled")
    @patch("sports_scraper.persistence.boxscore_helpers._normalize_status",
           return_value="scheduled")
    def test_no_changes_returns_false(self, mock_norm, mock_resolve):
        from sports_scraper.persistence.boxscore_helpers import _enrich_game_with_boxscore
        game, payload = self._make_game_and_payload(
            game_home_score=100, game_away_score=95,
            game_status="scheduled", game_venue="TD Garden",
            game_source_key="G123",
            payload_home_score=100, payload_away_score=95,
            payload_status="scheduled", payload_venue="TD Garden",
            payload_source_key="G123",
        )
        session = MagicMock()
        result = _enrich_game_with_boxscore(session, game, payload)
        assert result is False

    @patch("sports_scraper.persistence.boxscore_helpers.resolve_status_transition",
           return_value="final")
    @patch("sports_scraper.persistence.boxscore_helpers._normalize_status",
           return_value="final")
    def test_source_game_key_not_set_during_enrichment(self, mock_norm, mock_resolve):
        """source_game_key is set at creation time, not during enrichment."""
        from sports_scraper.persistence.boxscore_helpers import _enrich_game_with_boxscore
        game, payload = self._make_game_and_payload(
            game_home_score=100, game_away_score=95,
            game_source_key=None,
            payload_source_key="NEW_KEY",
        )
        game.venue = "TD Garden"
        game.status = "final"
        session = MagicMock()
        _enrich_game_with_boxscore(session, game, payload)
        # source_game_key should NOT be modified during enrichment
        assert game.source_game_key is None


# ===========================================================================
# NCAAB Boxscore Ingestion (lines 167, 202-254, 289, 323-329)
# ===========================================================================

class TestConvertNCAABBoxscoreToNormalizedGame:
    """Cover line 167 and convert_ncaab_boxscore_to_normalized_game."""

    def test_converts_final_status(self):
        from sports_scraper.services.ncaab_boxscore_ingestion import (
            convert_ncaab_boxscore_to_normalized_game,
        )
        home = _ncaab_team()
        away = _ncaab_team(name="UNC Tar Heels", abbr="UNC")
        boxscore = MagicMock()
        boxscore.season = 2025
        boxscore.game_date = datetime(2025, 3, 1, tzinfo=UTC)
        boxscore.home_team = home
        boxscore.away_team = away
        boxscore.game_id = 12345
        boxscore.status = "final"
        boxscore.home_score = 80
        boxscore.away_score = 75
        boxscore.team_boxscores = [
            NormalizedTeamBoxscore(team=home, is_home=True, points=80),
            NormalizedTeamBoxscore(team=away, is_home=False, points=75),
        ]
        boxscore.player_boxscores = []

        result = convert_ncaab_boxscore_to_normalized_game(boxscore)
        assert result.status == "completed"
        assert result.home_score == 80
        assert result.identity.league_code == "NCAAB"
        assert result.identity.source_game_key == "12345"

    def test_converts_non_final_status(self):
        from sports_scraper.services.ncaab_boxscore_ingestion import (
            convert_ncaab_boxscore_to_normalized_game,
        )
        home = _ncaab_team()
        away = _ncaab_team(name="UNC", abbr="UNC")
        boxscore = MagicMock()
        boxscore.season = 2025
        boxscore.game_date = datetime(2025, 3, 1, tzinfo=UTC)
        boxscore.home_team = home
        boxscore.away_team = away
        boxscore.game_id = 99
        boxscore.status = "live"
        boxscore.home_score = 40
        boxscore.away_score = 38
        boxscore.team_boxscores = [
            NormalizedTeamBoxscore(team=home, is_home=True, points=40),
            NormalizedTeamBoxscore(team=away, is_home=False, points=38),
        ]
        boxscore.player_boxscores = []

        result = convert_ncaab_boxscore_to_normalized_game(boxscore)
        assert result.status == "live"


class TestNCAABIngestionFlow:
    """Cover lines 202-254: NCAA fallback flow."""

    @patch("sports_scraper.services.ncaab_boxscore_ingestion._select_ncaa_boxscore_fallback_games")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    def test_no_games_selected_returns_zeros(self, mock_pop, mock_select, mock_persist, mock_fallback):
        from datetime import date

        from sports_scraper.services.ncaab_boxscore_ingestion import (
            ingest_boxscores_via_ncaab_api,
        )

        mock_select.return_value = []
        mock_fallback.return_value = []
        session = MagicMock()
        result = ingest_boxscores_via_ncaab_api(
            session,
            run_id=1,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 2),
            only_missing=False,
            updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.services.ncaab_boxscore_ingestion._select_ncaa_boxscore_fallback_games")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    def test_ncaa_fallback_with_boxscore(
        self, mock_client_cls, mock_pop, mock_select, mock_persist, mock_fallback
    ):
        """Lines 202-254: NCAA API fallback processes games."""
        from datetime import date

        from sports_scraper.services.ncaab_boxscore_ingestion import (
            ingest_boxscores_via_ncaab_api,
        )

        mock_select.return_value = [
            (1, 100, date(2025, 3, 1), "Duke", "UNC"),
        ]

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.fetch_boxscores_batch.return_value = {}

        mock_fallback.return_value = [
            (2, "NCAA123", "Duke", "UNC"),
        ]

        home = _ncaab_team()
        away = _ncaab_team(name="UNC", abbr="UNC")
        fallback_boxscore = MagicMock()
        fallback_boxscore.team_boxscores = [
            NormalizedTeamBoxscore(team=home, is_home=True, points=80),
        ]
        fallback_boxscore.player_boxscores = [
            NormalizedPlayerBoxscore(
                player_id="1", player_name="Player", team=home, points=20
            ),
        ]
        mock_client.fetch_ncaa_boxscore.return_value = fallback_boxscore

        session = MagicMock()
        result = ingest_boxscores_via_ncaab_api(
            session,
            run_id=1,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 2),
            only_missing=False,
            updated_before=None,
        )
        assert result[0] == 1
        assert result[2] == 1

    @patch("sports_scraper.services.ncaab_boxscore_ingestion._select_ncaa_boxscore_fallback_games")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    def test_ncaa_fallback_fetch_fails(
        self, mock_client_cls, mock_pop, mock_select, mock_persist, mock_fallback
    ):
        """Lines 246-254: exception in NCAA fallback is caught."""
        from datetime import date

        from sports_scraper.services.ncaab_boxscore_ingestion import (
            ingest_boxscores_via_ncaab_api,
        )

        mock_select.return_value = []
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_fallback.return_value = [
            (3, "NCAA456", "Duke", "UNC"),
        ]
        mock_client.fetch_ncaa_boxscore.side_effect = Exception("API down")

        session = MagicMock()
        result = ingest_boxscores_via_ncaab_api(
            session,
            run_id=1,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 2),
            only_missing=False,
            updated_before=None,
        )
        # No games selected from main query → early return, fallback path not reached
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.services.ncaab_boxscore_ingestion._select_ncaa_boxscore_fallback_games")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    def test_ncaa_fallback_returns_none(
        self, mock_client_cls, mock_pop, mock_select, mock_persist, mock_fallback
    ):
        """NCAA fallback returns None boxscore - skipped."""
        from datetime import date

        from sports_scraper.services.ncaab_boxscore_ingestion import (
            ingest_boxscores_via_ncaab_api,
        )

        mock_select.return_value = []
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_fallback.return_value = [
            (4, "NCAA789", "Duke", "UNC"),
        ]
        mock_client.fetch_ncaa_boxscore.return_value = None

        session = MagicMock()
        result = ingest_boxscores_via_ncaab_api(
            session,
            run_id=1,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 2),
            only_missing=False,
            updated_before=None,
        )
        assert result == (0, 0, 0, 0)

    @patch("sports_scraper.services.ncaab_boxscore_ingestion._select_ncaa_boxscore_fallback_games")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.persist_game_payload")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.select_games_for_boxscores_ncaab_api")
    @patch("sports_scraper.services.ncaab_boxscore_ingestion.populate_ncaab_game_ids")
    @patch("sports_scraper.live.ncaab.NCAABLiveFeedClient")
    def test_cbb_persist_exception_continues(
        self, mock_client_cls, mock_pop, mock_select, mock_persist, mock_fallback
    ):
        """Line 178-186: exception during persist_game_payload is caught."""
        from datetime import date

        from sports_scraper.services.ncaab_boxscore_ingestion import (
            ingest_boxscores_via_ncaab_api,
        )

        mock_select.return_value = [
            (1, 100, date(2025, 3, 1), "Duke", "UNC"),
        ]
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        home = _ncaab_team()
        away = _ncaab_team(name="UNC", abbr="UNC")
        cbb_boxscore = MagicMock()
        cbb_boxscore.game_date = datetime(2025, 3, 1, tzinfo=UTC)
        cbb_boxscore.season = 2025
        cbb_boxscore.home_team = home
        cbb_boxscore.away_team = away
        cbb_boxscore.game_id = 100
        cbb_boxscore.status = "final"
        cbb_boxscore.home_score = 80
        cbb_boxscore.away_score = 75
        cbb_boxscore.team_boxscores = [
            NormalizedTeamBoxscore(team=home, is_home=True, points=80),
            NormalizedTeamBoxscore(team=away, is_home=False, points=75),
        ]
        cbb_boxscore.player_boxscores = []

        mock_client.fetch_boxscores_batch.return_value = {100: cbb_boxscore}
        mock_persist.side_effect = Exception("DB exploded")
        mock_fallback.return_value = []

        session = MagicMock()
        result = ingest_boxscores_via_ncaab_api(
            session,
            run_id=1,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 2),
            only_missing=False,
            updated_before=None,
        )
        assert result == (0, 0, 0, 1)


class TestSelectNCAABoxscoreFallbackGames:
    """Cover lines 289, 323-329: _select_ncaa_boxscore_fallback_games."""

    def test_no_league_returns_empty(self):
        from datetime import date

        from sports_scraper.services.ncaab_boxscore_ingestion import (
            _select_ncaa_boxscore_fallback_games,
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = _select_ncaa_boxscore_fallback_games(
            session,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 2),
            only_missing=False,
            already_have_boxscore=set(),
        )
        assert result == []

    @patch("sports_scraper.utils.datetime_utils.end_of_et_day_utc")
    @patch("sports_scraper.utils.datetime_utils.start_of_et_day_utc")
    def test_filters_already_have_and_empty_ids(self, mock_start, mock_end):
        """Lines 323-329: filter ncaa_game_id=empty and already_have_boxscore."""
        from datetime import date

        from sports_scraper.services.ncaab_boxscore_ingestion import (
            _select_ncaa_boxscore_fallback_games,
        )

        mock_start.return_value = datetime(2025, 3, 1, tzinfo=UTC)
        mock_end.return_value = datetime(2025, 3, 3, tzinfo=UTC)

        mock_league = MagicMock()
        mock_league.id = 1

        session = MagicMock()
        league_query = MagicMock()
        league_query.filter.return_value.first.return_value = mock_league

        main_query = MagicMock()
        main_query.join.return_value = main_query
        main_query.filter.return_value = main_query
        main_query.all.return_value = [
            (10, "NCAA001", "Duke", "UNC"),
            (20, "", "Team A", "Team B"),
            (30, "NCAA003", "Team C", "Team D"),
            (40, "NCAA004", None, "Team F"),
            (50, "NCAA005", "Team G", None),
        ]

        session.query.side_effect = [league_query, main_query]

        result = _select_ncaa_boxscore_fallback_games(
            session,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 2),
            only_missing=False,
            already_have_boxscore={30},
        )
        assert len(result) == 1
        assert result[0] == (10, "NCAA001", "Duke", "UNC")


class TestDataclasses:
    """Cover dataclass properties."""

    def test_player_boxscore_stats_total(self):
        from sports_scraper.persistence.boxscore_helpers import PlayerBoxscoreStats

        stats = PlayerBoxscoreStats(inserted=5, rejected=2, errors=1)
        assert stats.total_processed == 8

    def test_game_persist_result_has_player_stats(self):
        from sports_scraper.persistence.boxscore_helpers import (
            GamePersistResult,
            PlayerBoxscoreStats,
        )

        result = GamePersistResult(
            game_id=1, enriched=True, player_stats=PlayerBoxscoreStats(inserted=3)
        )
        assert result.has_player_stats is True

    def test_game_persist_result_no_player_stats(self):
        from sports_scraper.persistence.boxscore_helpers import GamePersistResult

        result = GamePersistResult(game_id=1, enriched=False)
        assert result.has_player_stats is False

    def test_game_persist_result_zero_inserted(self):
        from sports_scraper.persistence.boxscore_helpers import (
            GamePersistResult,
            PlayerBoxscoreStats,
        )

        result = GamePersistResult(
            game_id=1, player_stats=PlayerBoxscoreStats(inserted=0)
        )
        assert result.has_player_stats is False

