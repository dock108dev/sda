"""Tests for live/nfl_advanced.py and services/nfl_advanced_stats_ingestion.py."""

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

from sports_scraper.live.nfl_advanced import NFLAdvancedStatsFetcher
from sports_scraper.services.nfl_advanced_stats_ingestion import (
    ingest_advanced_stats_for_game,
)

# ---------------------------------------------------------------------------
# Sample play data used across tests
# ---------------------------------------------------------------------------

SAMPLE_PLAYS = [
    {
        "posteam": "KC",
        "home_team": "KC",
        "away_team": "DET",
        "epa": 0.5,
        "wpa": 0.02,
        "pass_attempt": 1,
        "rush_attempt": 0,
        "success": 1,
        "cpoe": 5.0,
        "air_yards": 15,
        "yards_after_catch": 10,
        "yards_gained": 25,
        "air_epa": 0.3,
        "yac_epa": 0.2,
        "passer_player_id": "P1",
        "passer_player_name": "Mahomes",
        "receiver_player_id": "WR1",
        "receiver_player_name": "Kelce",
        "old_game_id": "401547417",
    },
    {
        "posteam": "KC",
        "home_team": "KC",
        "away_team": "DET",
        "epa": -0.3,
        "wpa": -0.01,
        "pass_attempt": 0,
        "rush_attempt": 1,
        "success": 0,
        "cpoe": None,
        "air_yards": None,
        "yards_after_catch": None,
        "yards_gained": 3,
        "rusher_player_id": "R1",
        "rusher_player_name": "Pacheco",
        "old_game_id": "401547417",
    },
    {
        "posteam": "DET",
        "home_team": "KC",
        "away_team": "DET",
        "epa": 1.2,
        "wpa": 0.05,
        "pass_attempt": 1,
        "rush_attempt": 0,
        "success": 1,
        "cpoe": 8.0,
        "air_yards": 30,
        "yards_after_catch": 15,
        "yards_gained": 45,
        "air_epa": 0.8,
        "yac_epa": 0.4,
        "passer_player_id": "P2",
        "passer_player_name": "Goff",
        "receiver_player_id": "WR2",
        "receiver_player_name": "St. Brown",
        "old_game_id": "401547417",
    },
    {
        "posteam": "KC",
        "home_team": "KC",
        "away_team": "DET",
        "epa": 0.8,
        "wpa": 0.03,
        "pass_attempt": 0,
        "rush_attempt": 1,
        "success": 1,
        "cpoe": None,
        "air_yards": None,
        "yards_after_catch": None,
        "yards_gained": 22,
        "rusher_player_id": "R1",
        "rusher_player_name": "Pacheco",
        "old_game_id": "401547417",
    },
]


# ---------------------------------------------------------------------------
# NFLAdvancedStatsFetcher.aggregate_team_stats
# Returns {"home": {...}, "away": {...}} with home_team/away_team from plays
# ---------------------------------------------------------------------------


class TestAggregateTeamStats:
    def test_epa_sums(self):
        """Verify EPA totals are summed correctly per team."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_team_stats(SAMPLE_PLAYS)

        assert "home" in result
        assert "away" in result

        home = result["home"]  # KC is home_team
        # KC plays: epa 0.5 + (-0.3) + 0.8 = 1.0
        assert abs(home["total_epa"] - 1.0) < 0.001

        away = result["away"]  # DET is away_team
        # DET plays: epa 1.2
        assert abs(away["total_epa"] - 1.2) < 0.001

    def test_success_rate(self):
        """Verify success rate computation (plays with epa > 0 / total plays)."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_team_stats(SAMPLE_PLAYS)

        home = result["home"]
        # KC: 3 plays, 2 with epa > 0 (0.5, 0.8)
        assert abs(home["success_rate"] - (2 / 3)) < 0.01

        away = result["away"]
        # DET: 1 play, 1 with epa > 0
        assert abs(away["success_rate"] - 1.0) < 0.01

    def test_pass_rush_epa_split(self):
        """Verify EPA is split correctly between pass and rush plays."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_team_stats(SAMPLE_PLAYS)

        home = result["home"]
        # KC pass: 0.5, KC rush: -0.3 + 0.8 = 0.5
        assert abs(home["pass_epa"] - 0.5) < 0.001
        assert abs(home["rush_epa"] - 0.5) < 0.001

    def test_explosive_play_rate(self):
        """Explosive plays: pass >= 20 yards or rush >= 12 yards."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_team_stats(SAMPLE_PLAYS)

        home = result["home"]
        # KC: pass 25 yards (explosive), rush 3 yards (not), rush 22 yards (explosive)
        # explosive_play_rate = explosive_count / (pass_plays + rush_plays) = 2/3
        assert home["explosive_play_rate"] is not None
        assert abs(home["explosive_play_rate"] - (2 / 3)) < 0.01

        away = result["away"]
        # DET: pass 45 yards (explosive) = 1/1
        assert away["explosive_play_rate"] is not None
        assert abs(away["explosive_play_rate"] - 1.0) < 0.01

    def test_empty_plays(self):
        """Empty play list returns home/away with empty dicts."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_team_stats([])
        assert result == {"home": {}, "away": {}}

    def test_wpa_sums(self):
        """Verify WPA totals are summed correctly per team."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_team_stats(SAMPLE_PLAYS)

        home = result["home"]
        # KC WPA: 0.02 + (-0.01) + 0.03 = 0.04
        assert abs(home["total_wpa"] - 0.04) < 0.001


# ---------------------------------------------------------------------------
# NFLAdvancedStatsFetcher.aggregate_player_stats
# Returns list[dict] with player_role, player_external_ref, etc.
# ---------------------------------------------------------------------------


class TestAggregatePlayerStats:
    def test_passer_grouping(self):
        """Verify passer stats are grouped by player ID."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_player_stats(SAMPLE_PLAYS)

        assert isinstance(result, list)
        passers = [p for p in result if p["player_role"] == "passer"]

        p1 = [p for p in passers if p["player_external_ref"] == "P1"]
        assert len(p1) == 1
        assert p1[0]["player_name"] == "Mahomes"
        assert p1[0]["plays"] == 1
        assert abs(p1[0]["total_epa"] - 0.5) < 0.001
        assert p1[0]["cpoe"] is not None
        assert abs(p1[0]["cpoe"] - 5.0) < 0.001

        p2 = [p for p in passers if p["player_external_ref"] == "P2"]
        assert len(p2) == 1
        assert p2[0]["player_name"] == "Goff"
        assert p2[0]["plays"] == 1
        assert abs(p2[0]["total_epa"] - 1.2) < 0.001

    def test_rusher_grouping(self):
        """Verify rusher stats are grouped by player ID."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_player_stats(SAMPLE_PLAYS)

        rushers = [p for p in result if p["player_role"] == "rusher"]
        r1 = [p for p in rushers if p["player_external_ref"] == "R1"]
        assert len(r1) == 1
        assert r1[0]["player_name"] == "Pacheco"
        assert r1[0]["plays"] == 2
        # Rush EPA: -0.3 + 0.8 = 0.5
        assert abs(r1[0]["total_epa"] - 0.5) < 0.001

    def test_receiver_grouping(self):
        """Verify receiver stats are grouped by player ID."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_player_stats(SAMPLE_PLAYS)

        receivers = [p for p in result if p["player_role"] == "receiver"]
        wr1 = [p for p in receivers if p["player_external_ref"] == "WR1"]
        assert len(wr1) == 1
        assert wr1[0]["player_name"] == "Kelce"
        assert wr1[0]["plays"] == 1

    def test_empty_plays(self):
        """Empty play list returns empty list."""
        fetcher = NFLAdvancedStatsFetcher.__new__(NFLAdvancedStatsFetcher)
        result = fetcher.aggregate_player_stats([])
        assert result == []


# ---------------------------------------------------------------------------
# ingest_advanced_stats_for_game (NFL)
# ---------------------------------------------------------------------------


class TestNFLIngestAdvancedStats:
    @staticmethod
    def _make_game(
        status="final",
        external_ids=None,
        home_team_id=1,
        away_team_id=2,
    ):
        game = MagicMock()
        game.status = status
        game.league_id = 40
        game.home_team_id = home_team_id
        game.away_team_id = away_team_id
        game.external_ids = external_ids if external_ids is not None else {"espn_game_id": "401547417"}
        game.last_advanced_stats_at = None
        return game

    @staticmethod
    def _make_league(code="NFL"):
        league = MagicMock()
        league.code = code
        return league

    @staticmethod
    def _make_team(abbr="KC"):
        team = MagicMock()
        team.abbreviation = abbr
        return team

    @staticmethod
    def _make_session(game=None, league=None):
        session = MagicMock()

        def get_side_effect(model_id):
            if not get_side_effect._results:
                return None
            return get_side_effect._results.pop(0)

        results = []
        if game is not None:
            results.append(game)
        if league is not None:
            results.append(league)
        # Add home/away team lookups (called by ingest_advanced_stats_for_game)
        home_team = MagicMock()
        home_team.abbreviation = "KC"
        away_team = MagicMock()
        away_team.abbreviation = "DET"
        results.extend([home_team, away_team])
        get_side_effect._results = results

        session.query.return_value.get = MagicMock(side_effect=get_side_effect)
        return session

    def test_game_not_found(self):
        session = MagicMock()
        session.query.return_value.get.return_value = None

        result = ingest_advanced_stats_for_game(session, 999)
        assert result["status"] == "not_found"

    def test_game_not_final(self):
        game = self._make_game(status="live")
        session = MagicMock()
        session.query.return_value.get.return_value = game

        result = ingest_advanced_stats_for_game(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_final"

    def test_game_not_nfl(self):
        game = self._make_game()
        league = self._make_league(code="NBA")
        session = self._make_session(game, league)

        result = ingest_advanced_stats_for_game(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_nfl"

    def test_no_espn_game_id_still_attempts_match(self):
        """Games without ESPN ID still attempt matching by date + teams."""
        game = self._make_game(external_ids={})
        league = self._make_league(code="NFL")
        session = self._make_session(game, league)

        result = ingest_advanced_stats_for_game(session, 1)
        # Without team data in the mock, nflverse matching returns no plays
        assert result["status"] == "skipped"
        assert result["reason"] == "no_plays"
