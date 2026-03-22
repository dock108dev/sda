"""Tests for NBA advanced stats (derived from boxscore data)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.live.nba_advanced import (
    NBAAdvancedStatsFetcher,
    _compute_possessions,
    _extract_stat,
)

HOME_BOX = {
    "fg_made": 40, "fg_attempted": 85,
    "three_made": 12, "three_attempted": 30,
    "ft_made": 18, "ft_attempted": 22,
    "offensive_rebounds": 10, "defensive_rebounds": 32,
    "turnovers": 14, "assists": 25,
    "points_in_paint": 48, "fast_break_points": 14,
    "second_chance_points": 12, "points_off_turnovers": 18,
    "bench_points": 35,
}

AWAY_BOX = {
    "fg_made": 38, "fg_attempted": 88,
    "three_made": 10, "three_attempted": 28,
    "ft_made": 15, "ft_attempted": 20,
    "offensive_rebounds": 8, "defensive_rebounds": 30,
    "turnovers": 16, "assists": 22,
    "points_in_paint": 42, "fast_break_points": 10,
}


class TestExtractStat:
    def test_existing_key(self):
        assert _extract_stat({"fg_made": 40}, "fg_made") == 40

    def test_missing_key(self):
        assert _extract_stat({}, "fg_made") == 0

    def test_none_value(self):
        assert _extract_stat({"fg_made": None}, "fg_made") == 0


class TestComputePossessions:
    def test_basic(self):
        result = _compute_possessions(85, 10, 14, 22)
        assert abs(result - 98.68) < 0.01


class TestComputeTeamAdvancedStats:
    def test_returns_both_teams(self):
        fetcher = NBAAdvancedStatsFetcher()
        result = fetcher.compute_team_advanced_stats(HOME_BOX, AWAY_BOX, 110, 101)
        assert "home" in result and "away" in result

    def test_off_rating_reasonable(self):
        fetcher = NBAAdvancedStatsFetcher()
        result = fetcher.compute_team_advanced_stats(HOME_BOX, AWAY_BOX, 110, 101)
        assert result["home"]["off_rating"] is not None
        assert result["home"]["off_rating"] > 100

    def test_efg_pct(self):
        fetcher = NBAAdvancedStatsFetcher()
        result = fetcher.compute_team_advanced_stats(HOME_BOX, AWAY_BOX, 110, 101)
        assert abs(result["home"]["efg_pct"] - 0.541) < 0.01

    def test_paint_points(self):
        fetcher = NBAAdvancedStatsFetcher()
        result = fetcher.compute_team_advanced_stats(HOME_BOX, AWAY_BOX, 110, 101)
        assert result["home"]["paint_points"] == 48

    def test_hustle_is_none(self):
        fetcher = NBAAdvancedStatsFetcher()
        result = fetcher.compute_team_advanced_stats(HOME_BOX, AWAY_BOX, 110, 101)
        assert result["home"]["contested_shots"] is None
        assert result["home"]["deflections"] is None


class TestComputePlayerAdvancedStats:
    def test_basic(self):
        fetcher = NBAAdvancedStatsFetcher()
        players = [{
            "player_id": "123", "player_name": "Test", "is_home": True,
            "stats": {
                "minutes": 35.0, "fg_made": 10, "fg_attempted": 20,
                "three_made": 3, "three_attempted": 8, "ft_made": 5, "ft_attempted": 6,
                "points": 28, "offensive_rebounds": 2, "defensive_rebounds": 5,
                "assists": 6, "steals": 2, "blocks": 1, "turnovers": 3, "personal_fouls": 2,
            },
        }]
        result = fetcher.compute_player_advanced_stats(players, 100, 240)
        assert len(result) == 1
        assert result[0]["ts_pct"] is not None
        assert result[0]["usg_pct"] is not None

    def test_skips_zero_minutes(self):
        fetcher = NBAAdvancedStatsFetcher()
        result = fetcher.compute_player_advanced_stats(
            [{"player_id": "1", "player_name": "DNP", "is_home": True, "stats": {"minutes": 0}}],
            100, 240,
        )
        assert len(result) == 0


class TestNBAIngestSkipConditions:
    def test_not_found(self):
        from sports_scraper.services.nba_advanced_stats_ingestion import ingest_advanced_stats_for_game
        session = MagicMock()
        session.query.return_value.get.return_value = None
        assert ingest_advanced_stats_for_game(session, 999)["status"] == "not_found"

    def test_not_final(self):
        from sports_scraper.services.nba_advanced_stats_ingestion import ingest_advanced_stats_for_game
        session = MagicMock()
        game = MagicMock(id=42, status="live", league_id=1)
        league = MagicMock(code="NBA")
        session.query.return_value.get.side_effect = [game, league]
        assert ingest_advanced_stats_for_game(session, 42)["reason"] == "not_final"

    def test_not_nba(self):
        from sports_scraper.services.nba_advanced_stats_ingestion import ingest_advanced_stats_for_game
        session = MagicMock()
        game = MagicMock(id=42, status="final", league_id=1)
        league = MagicMock(code="NHL")
        session.query.return_value.get.side_effect = [game, league]
        assert ingest_advanced_stats_for_game(session, 42)["reason"] == "not_nba"

    def test_missing_boxscores(self):
        from sports_scraper.services.nba_advanced_stats_ingestion import ingest_advanced_stats_for_game
        session = MagicMock()
        game = MagicMock(id=42, status="final", league_id=1)
        league = MagicMock(code="NBA")
        session.query.return_value.get.side_effect = [game, league]
        session.query.return_value.filter.return_value.all.return_value = []
        assert ingest_advanced_stats_for_game(session, 42)["reason"] == "missing_boxscores"
