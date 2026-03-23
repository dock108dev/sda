"""Tests for services/pbp_nfl.py — NFL play-by-play ingestion."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

_MOD = "sports_scraper.services.pbp_nfl"


# ---------------------------------------------------------------------------
# select_games_for_pbp_nfl_api
# ---------------------------------------------------------------------------

class TestSelectGamesForPbpNflApi:
    def test_no_league_returns_empty(self):
        from sports_scraper.services.pbp_nfl import select_games_for_pbp_nfl_api

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_pbp_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_returns_valid_games(self):
        from sports_scraper.services.pbp_nfl import select_games_for_pbp_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "401671234")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_pbp_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert len(result) == 1
        assert result[0] == (100, 401671234)

    def test_skips_none_espn_game_id(self):
        from sports_scraper.services.pbp_nfl import select_games_for_pbp_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, None)
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_pbp_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_skips_invalid_espn_game_id(self):
        from sports_scraper.services.pbp_nfl import select_games_for_pbp_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "bad-id")
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_pbp_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == []

    def test_only_missing_applies_filter(self):
        from sports_scraper.services.pbp_nfl import select_games_for_pbp_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_pbp_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=True, updated_before=None,
        )
        assert result == []

    def test_updated_before_applies_filter(self):
        from sports_scraper.services.pbp_nfl import select_games_for_pbp_nfl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_pbp_nfl_api(
            session, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=datetime(2024, 11, 9, tzinfo=UTC),
        )
        assert result == []


# ---------------------------------------------------------------------------
# ingest_pbp_via_nfl_api
# ---------------------------------------------------------------------------

class TestIngestPbpViaNflApi:
    @patch(f"{_MOD}.select_games_for_pbp_nfl_api", return_value=[])
    @patch("sports_scraper.services.nfl_boxscore_ingestion.populate_nfl_game_ids")
    def test_no_games_returns_zeros(self, mock_pop_ids, mock_select):
        from sports_scraper.services.pbp_nfl import ingest_pbp_via_nfl_api

        session = MagicMock()
        result = ingest_pbp_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )
        assert result == (0, 0)

    @patch(f"{_MOD}.now_utc")
    @patch(f"{_MOD}.upsert_plays", return_value=42)
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_pbp_nfl_api")
    @patch("sports_scraper.services.nfl_boxscore_ingestion.populate_nfl_game_ids")
    def test_processes_game_successfully(
        self, mock_pop_ids, mock_select, mock_client_cls, mock_upsert, mock_now,
    ):
        from sports_scraper.services.pbp_nfl import ingest_pbp_via_nfl_api

        mock_select.return_value = [(100, 401671234)]

        payload = MagicMock()
        play1 = MagicMock()
        play2 = MagicMock()
        payload.plays = [play1, play2]
        mock_client_cls.return_value.fetch_play_by_play.return_value = payload

        game = MagicMock(id=100)
        session = MagicMock()
        session.get.return_value = game

        mock_now.return_value = datetime(2024, 11, 10, 23, 0, tzinfo=UTC)

        result = ingest_pbp_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 42)
        mock_upsert.assert_called_once()
        session.commit.assert_called()

    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_pbp_nfl_api")
    @patch("sports_scraper.services.nfl_boxscore_ingestion.populate_nfl_game_ids")
    def test_skips_game_with_no_plays(self, mock_pop_ids, mock_select, mock_client_cls):
        from sports_scraper.services.pbp_nfl import ingest_pbp_via_nfl_api

        mock_select.return_value = [(100, 401671234)]

        payload = MagicMock()
        payload.plays = []
        mock_client_cls.return_value.fetch_play_by_play.return_value = payload

        session = MagicMock()
        result = ingest_pbp_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (0, 0)

    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_pbp_nfl_api")
    @patch("sports_scraper.services.nfl_boxscore_ingestion.populate_nfl_game_ids")
    def test_handles_fetch_exception(self, mock_pop_ids, mock_select, mock_client_cls):
        from sports_scraper.services.pbp_nfl import ingest_pbp_via_nfl_api

        mock_select.return_value = [(100, 401671234)]
        mock_client_cls.return_value.fetch_play_by_play.side_effect = Exception("API error")

        session = MagicMock()
        result = ingest_pbp_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (0, 0)
        session.rollback.assert_called()

    @patch(f"{_MOD}.now_utc")
    @patch(f"{_MOD}.upsert_plays", return_value=None)
    @patch("sports_scraper.live.nfl.NFLLiveFeedClient")
    @patch(f"{_MOD}.select_games_for_pbp_nfl_api")
    @patch("sports_scraper.services.nfl_boxscore_ingestion.populate_nfl_game_ids")
    def test_handles_none_upsert_return(
        self, mock_pop_ids, mock_select, mock_client_cls, mock_upsert, mock_now,
    ):
        """When upsert_plays returns None, total_events should count 0."""
        from sports_scraper.services.pbp_nfl import ingest_pbp_via_nfl_api

        mock_select.return_value = [(100, 401671234)]

        payload = MagicMock()
        payload.plays = [MagicMock()]
        mock_client_cls.return_value.fetch_play_by_play.return_value = payload

        session = MagicMock()
        session.get.return_value = MagicMock(id=100)
        mock_now.return_value = datetime(2024, 11, 10, 23, 0, tzinfo=UTC)

        result = ingest_pbp_via_nfl_api(
            session, run_id=1, start_date=date(2024, 11, 10), end_date=date(2024, 11, 11),
            only_missing=False, updated_before=None,
        )

        assert result == (1, 0)
