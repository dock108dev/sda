"""Tests for services/mlb_advanced_stats_ingestion.py."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.live.mlb_statcast import TeamStatcastAggregates
from sports_scraper.services.mlb_advanced_stats_ingestion import (
    _safe_div,
    ingest_advanced_stats_for_game,
)


# ---------------------------------------------------------------------------
# _safe_div
# ---------------------------------------------------------------------------


class TestSafeDiv:
    def test_normal_division(self):
        assert _safe_div(10, 5) == 2.0

    def test_zero_denominator_returns_none(self):
        assert _safe_div(10, 0) is None

    def test_zero_numerator(self):
        assert _safe_div(0, 5) == 0.0

    def test_float_division(self):
        result = _safe_div(1, 3)
        assert result is not None
        assert abs(result - 0.3333) < 0.01


# ---------------------------------------------------------------------------
# ingest_advanced_stats_for_game
# ---------------------------------------------------------------------------


class TestIngestAdvancedStatsForGame:
    @staticmethod
    def _make_game(
        status="final",
        league_code="MLB",
        external_ids=None,
        home_team_id=1,
        away_team_id=2,
    ):
        """Create a mock game object."""
        game = MagicMock()
        game.status = status
        game.league_id = 10
        game.home_team_id = home_team_id
        game.away_team_id = away_team_id
        game.external_ids = external_ids if external_ids is not None else {"mlb_game_pk": 12345}
        game.last_advanced_stats_at = None
        return game

    @staticmethod
    def _make_league(code="MLB"):
        league = MagicMock()
        league.code = code
        return league

    @staticmethod
    def _make_session(game=None, league=None):
        session = MagicMock()

        def get_side_effect(model_id):
            # Route based on call order: first call gets game, second gets league
            return get_side_effect._results.pop(0)

        results = []
        if game is not None:
            results.append(game)
        if league is not None:
            results.append(league)
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

    def test_game_not_mlb(self):
        game = self._make_game()
        league = self._make_league(code="NBA")
        session = self._make_session(game, league)

        result = ingest_advanced_stats_for_game(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_mlb"

    def test_no_game_pk(self):
        game = self._make_game(external_ids={})
        league = self._make_league(code="MLB")
        session = self._make_session(game, league)

        result = ingest_advanced_stats_for_game(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_game_pk"

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    def test_successful_ingestion(self, MockClient):
        game = self._make_game()
        league = self._make_league(code="MLB")
        session = self._make_session(game, league)

        # Mock statcast aggregates
        home_agg = TeamStatcastAggregates(
            total_pitches=100,
            zone_pitches=50,
            zone_swings=30,
            zone_contact=25,
            outside_pitches=40,
            outside_swings=10,
            outside_contact=5,
            balls_in_play=20,
            total_exit_velo=1800.0,
            hard_hit_count=8,
            barrel_count=3,
        )
        away_agg = TeamStatcastAggregates(
            total_pitches=95,
            zone_pitches=45,
            zone_swings=25,
            zone_contact=20,
            outside_pitches=38,
            outside_swings=12,
            outside_contact=4,
            balls_in_play=18,
            total_exit_velo=1600.0,
            hard_hit_count=6,
            barrel_count=2,
        )

        mock_client = MagicMock()
        mock_client.fetch_statcast_aggregates.return_value = {
            "home": home_agg,
            "away": away_agg,
        }
        MockClient.return_value = mock_client

        result = ingest_advanced_stats_for_game(session, 1)

        assert result["status"] == "success"
        assert result["rows_upserted"] == 2

        # Verify the client was called with the right game_pk
        mock_client.fetch_statcast_aggregates.assert_called_once_with(12345, game_status="final")

        # Verify session.execute was called twice (once per team)
        assert session.execute.call_count == 2

        # Verify game timestamp was updated
        assert game.last_advanced_stats_at is not None

        # Verify flush was called
        session.flush.assert_called_once()
