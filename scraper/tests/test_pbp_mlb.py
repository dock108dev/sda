"""Tests for services/pbp_mlb.py — targeting ≥80% coverage."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.live.mlb_pbp import MLBPbpFetcher
from sports_scraper.services.pbp_mlb import (
    ingest_pbp_via_mlb_api,
    select_games_for_pbp_mlb_api,
)


# ---------------------------------------------------------------------------
# select_games_for_pbp_mlb_api
# ---------------------------------------------------------------------------

class TestSelectGamesForPbpMlbApi:
    def test_no_league_returns_empty(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_pbp_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 2),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_returns_valid_games(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "717001", "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_pbp_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert len(result) == 1
        assert result[0] == (100, 717001, "final")

    def test_skips_none_game_pk(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, None, "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_pbp_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_skips_invalid_game_pk(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "not-a-number", "final")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_pbp_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_only_missing_applies_filter(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_pbp_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=True, updated_before=None,
        )
        assert result == []

    def test_updated_before_applies_filter(self):
        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_pbp_mlb_api(
            session, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=datetime(2024, 7, 10, tzinfo=UTC),
        )
        assert result == []


# ---------------------------------------------------------------------------
# ingest_pbp_via_mlb_api
# ---------------------------------------------------------------------------

def _make_game(*, status="final", mlb_game_pk="717001"):
    """Create a game mock with proper external_ids for game_processors."""
    game = MagicMock()
    game.status = status
    game.external_ids = {"mlb_game_pk": str(mlb_game_pk)}
    game.id = 100
    return game


class TestIngestPbpViaMlbApi:
    @patch("sports_scraper.services.pbp_mlb.select_games_for_pbp_mlb_api", return_value=[])
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_no_games_returns_zeros(self, mock_populate, mock_select):
        session = MagicMock()
        result = ingest_pbp_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 2),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays", return_value=25)
    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.pbp_mlb.select_games_for_pbp_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_processes_games(self, mock_populate, mock_select, mock_client_cls, mock_upsert):
        mock_select.return_value = [(100, 717001, "final")]

        payload = MagicMock()
        payload.plays = [MagicMock() for _ in range(60)]
        mock_client_cls.return_value.fetch_play_by_play.return_value = payload

        game = _make_game()
        session = MagicMock()
        session.query.return_value.get.return_value = game

        result = ingest_pbp_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 25)
        mock_upsert.assert_called_once()

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.pbp_mlb.select_games_for_pbp_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_skips_empty_plays(self, mock_populate, mock_select, mock_client_cls):
        mock_select.return_value = [(100, 717001, "final")]

        payload = MagicMock()
        payload.plays = []
        mock_client_cls.return_value.fetch_play_by_play.return_value = payload

        game = _make_game()
        session = MagicMock()
        session.query.return_value.get.return_value = game

        result = ingest_pbp_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0)

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.pbp_mlb.select_games_for_pbp_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_handles_fetch_exception(self, mock_populate, mock_select, mock_client_cls):
        mock_select.return_value = [(100, 717001, "final")]
        mock_client_cls.return_value.fetch_play_by_play.side_effect = Exception("timeout")

        game = _make_game()
        session = MagicMock()
        session.query.return_value.get.return_value = game

        result = ingest_pbp_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays", return_value=0)
    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.pbp_mlb.select_games_for_pbp_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_zero_inserted_not_counted(self, mock_populate, mock_select, mock_client_cls, mock_upsert):
        mock_select.return_value = [(100, 717001, "final")]

        payload = MagicMock()
        payload.plays = [MagicMock() for _ in range(60)]
        mock_client_cls.return_value.fetch_play_by_play.return_value = payload

        game = _make_game()
        session = MagicMock()
        session.query.return_value.get.return_value = game

        result = ingest_pbp_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0)

    @patch("sports_scraper.persistence.plays.upsert_plays", return_value=10)
    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.pbp_mlb.select_games_for_pbp_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_warns_on_low_play_count_for_final(self, mock_populate, mock_select, mock_client_cls, mock_upsert):
        """When a final game has fewer plays than MLB_MIN_EXPECTED_PLAYS, still persists but logs warning."""
        mock_select.return_value = [(100, 717001, "final")]

        payload = MagicMock()
        payload.plays = [MagicMock() for _ in range(10)]  # below threshold
        mock_client_cls.return_value.fetch_play_by_play.return_value = payload

        game = _make_game()
        session = MagicMock()
        session.query.return_value.get.return_value = game

        result = ingest_pbp_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        # Still persists despite warning
        assert result == (1, 10)

    @patch("sports_scraper.live.mlb.MLBLiveFeedClient")
    @patch("sports_scraper.services.pbp_mlb.select_games_for_pbp_mlb_api")
    @patch("sports_scraper.services.mlb_boxscore_ingestion.populate_mlb_game_ids")
    def test_game_not_found_skips(self, mock_populate, mock_select, mock_client_cls):
        """If game lookup returns None, the game is skipped."""
        mock_select.return_value = [(100, 717001, "final")]

        session = MagicMock()
        session.query.return_value.get.return_value = None  # game not found

        result = ingest_pbp_via_mlb_api(
            session, run_id=1, start_date=date(2024, 7, 1), end_date=date(2024, 7, 31),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0)


# ---------------------------------------------------------------------------
# MLBPbpFetcher._normalize_play — is_home_team derivation
# ---------------------------------------------------------------------------


class TestMLBNormalizePlayIsHomeTeam:
    """Verify is_home_team is derived from half-inning in raw_data."""

    def _make_fetcher(self):
        client = MagicMock()
        cache = MagicMock()
        cache.get.return_value = None
        return MLBPbpFetcher(client, cache)

    def _make_play(self, *, is_top_inning=True, inning=1, at_bat_index=0):
        return {
            "about": {
                "inning": inning,
                "isTopInning": is_top_inning,
                "atBatIndex": at_bat_index,
                "halfInning": "top" if is_top_inning else "bottom",
            },
            "result": {
                "eventType": "single",
                "event": "Single",
                "description": "Player singles.",
                "homeScore": 0,
                "awayScore": 0,
            },
            "matchup": {
                "batter": {"id": 123, "fullName": "Test Player"},
                "pitcher": {"id": 456, "fullName": "Test Pitcher"},
            },
            "runners": [],
            "count": {},
        }

    def test_top_inning_sets_is_home_team_false(self):
        """Top of inning = away team batting, so is_home_team should be False."""
        fetcher = self._make_fetcher()
        play = self._make_play(is_top_inning=True)
        result = fetcher._normalize_play(play, game_pk=123)

        assert result is not None
        assert result.raw_data["is_home_team"] is False
        assert result.raw_data["is_top_inning"] is True

    def test_bottom_inning_sets_is_home_team_true(self):
        """Bottom of inning = home team batting, so is_home_team should be True."""
        fetcher = self._make_fetcher()
        play = self._make_play(is_top_inning=False)
        result = fetcher._normalize_play(play, game_pk=123)

        assert result is not None
        assert result.raw_data["is_home_team"] is True
        assert result.raw_data["is_top_inning"] is False
