"""Tests for services/run_manager.py module."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from sports_scraper.models import IngestionConfig
from sports_scraper.services.run_manager import ScrapeRunManager


class TestScrapeRunManagerImports:
    """Tests for ScrapeRunManager module imports."""

    def test_class_exists(self):
        """ScrapeRunManager class exists."""
        assert ScrapeRunManager is not None

    def test_class_is_callable(self):
        """ScrapeRunManager can be instantiated."""
        # Note: Full instantiation requires scrapers to be available
        # Just verify it's a class
        assert callable(ScrapeRunManager)


class TestScrapeRunManagerAttributes:
    """Tests for ScrapeRunManager class attributes."""

    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    def test_init_creates_scrapers(self, mock_live, mock_scrapers):
        """Initializes with scrapers."""
        mock_scrapers.return_value = {}
        manager = ScrapeRunManager()
        assert mock_scrapers.called

    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    def test_has_supported_leagues(self, mock_live, mock_scrapers):
        """Has supported league lists."""
        mock_scrapers.return_value = {}
        manager = ScrapeRunManager()
        assert hasattr(manager, "_supported_social_leagues")
        assert hasattr(manager, "_supported_live_pbp_leagues")

    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    def test_supported_social_leagues(self, mock_live, mock_scrapers):
        """Social is supported for NBA and NHL."""
        mock_scrapers.return_value = {}
        manager = ScrapeRunManager()
        assert "NBA" in manager._supported_social_leagues
        assert "NHL" in manager._supported_social_leagues

    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    def test_supported_live_pbp_leagues(self, mock_live, mock_scrapers):
        """Live PBP is supported for NBA, NHL, and NCAAB."""
        mock_scrapers.return_value = {}
        manager = ScrapeRunManager()
        assert "NBA" in manager._supported_live_pbp_leagues
        assert "NHL" in manager._supported_live_pbp_leagues
        assert "NCAAB" in manager._supported_live_pbp_leagues


class TestScrapeRunManagerUpdateRun:
    """Tests for _update_run method."""

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_updates_run_attributes(self, mock_scrapers, mock_live, mock_get_session):
        """Updates run attributes successfully."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        manager._update_run(1, status="running", started_at=datetime.now(UTC))

        assert mock_run.status == "running"
        mock_session.flush.assert_called()
        mock_session.commit.assert_called()

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_handles_run_not_found(self, mock_scrapers, mock_live, mock_get_session):
        """Handles case when run is not found."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_session.query.return_value.limit.return_value.all.return_value = []
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        # Should not raise, just logs error
        manager._update_run(999, status="running")

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_raises_on_db_error(self, mock_scrapers, mock_live, mock_get_session):
        """Raises exception on database error."""
        mock_scrapers.return_value = {}
        mock_get_session.return_value.__enter__ = MagicMock(side_effect=Exception("DB error"))
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()

        with pytest.raises(Exception):
            manager._update_run(1, status="running")


class TestScrapeRunManagerRun:
    """Tests for run method."""

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_raises_when_no_scraper_for_non_api_league(
        self, mock_scrapers, mock_live, mock_conflicts,
        mock_missing, mock_complete, mock_start, mock_get_session
    ):
        """Raises RuntimeError when no scraper for non-API league."""
        mock_scrapers.return_value = {}  # No scrapers
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        # Use a non-API league (NBA, NHL, NCAAB, MLB all use API paths now)
        config = IngestionConfig(
            league_code="NCAAF",
            boxscores=True,
        )

        with pytest.raises(RuntimeError, match="No scraper implemented"):
            manager.run(1, config)

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_allows_nhl_without_scraper(
        self, mock_scrapers, mock_live, mock_conflicts,
        mock_missing, mock_complete, mock_start, mock_get_session
    ):
        """NHL can run boxscores without scraper (uses API)."""
        mock_scrapers.return_value = {}  # No scrapers
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        config = IngestionConfig(
            league_code="NHL",
            boxscores=False,
            odds=False,
            social=False,
            pbp=False,
        )

        # Should not raise
        result = manager.run(1, config)
        assert isinstance(result, dict)


class TestScrapeRunManagerBoxscores:
    """Tests for boxscore scraping in run method."""

    @patch("sports_scraper.services.nhl_boxscore_ingestion.ingest_boxscores_via_nhl_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_nhl_uses_api_for_boxscores(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NHL uses API for boxscores."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.return_value = (5, 3, 2, 0)  # (games, enriched, with_stats, errors)

        manager = ScrapeRunManager()
        # Use a date in the past to avoid "future dates" skip
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NHL",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
        )

        result = manager.run(1, config)

        assert result["games"] == 5
        assert result["games_enriched"] == 3
        assert result["games_with_stats"] == 2

    @patch("sports_scraper.services.nhl_boxscore_ingestion.ingest_boxscores_via_nhl_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_nhl_boxscore_handles_api_error(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NHL boxscore handles API errors gracefully."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.side_effect = Exception("NHL API error")

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NHL",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
        )

        # Should not raise, handles exception internally
        result = manager.run(1, config)
        assert result["games"] == 0

    @patch("sports_scraper.services.ncaab_boxscore_ingestion.ingest_boxscores_via_ncaab_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_ncaab_boxscore_handles_api_error(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NCAAB boxscore handles API errors gracefully."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.side_effect = Exception("NCAAB API error")

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NCAAB",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
        )

        # Should not raise, handles exception internally
        result = manager.run(1, config)
        assert result["games"] == 0

    @patch("sports_scraper.services.ncaab_boxscore_ingestion.ingest_boxscores_via_ncaab_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_ncaab_uses_api_for_boxscores(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NCAAB uses API for boxscores."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.return_value = (10, 8, 5, 0)  # (games, enriched, with_stats, errors)

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NCAAB",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
        )

        result = manager.run(1, config)

        assert result["games"] == 10
        assert result["games_enriched"] == 8
        assert result["games_with_stats"] == 5

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_skips_future_dates_for_boxscores(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session
    ):
        """Skips boxscores for future dates."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        future_date = date.today() + timedelta(days=5)
        config = IngestionConfig(
            league_code="NHL",
            start_date=future_date,
            end_date=future_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
        )

        result = manager.run(1, config)

        # No games processed because dates are in future
        assert result["games"] == 0

    @patch("sports_scraper.services.run_manager.select_games_for_boxscores")
    @patch("sports_scraper.services.run_manager.persist_game_payload")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_scraper_boxscores_with_only_missing(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_persist, mock_select
    ):
        """Uses Sports Reference scraper for boxscores with only_missing."""
        mock_scraper = MagicMock()
        mock_payload = MagicMock()
        mock_scraper.fetch_single_boxscore.return_value = mock_payload
        # Use a non-API league so the SR scraper path is taken
        # (NFL now has its own API path, use NCAAF as the SR-only league)
        mock_scrapers.return_value = {"NCAAF": mock_scraper}

        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        # Mock persist result
        mock_result = MagicMock()
        mock_result.game_id = 1
        mock_result.enriched = True
        mock_result.has_player_stats = True
        mock_persist.return_value = mock_result

        # Return games to scrape
        mock_select.return_value = [(1, "BOS202401150", date(2024, 1, 15))]

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NCAAF",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
            only_missing=True,
        )

        result = manager.run(1, config)

        assert result["games"] == 1
        assert result["games_enriched"] == 1
        assert result["games_with_stats"] == 1
        mock_scraper.fetch_single_boxscore.assert_called()

    @patch("sports_scraper.services.run_manager.select_games_for_boxscores")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_scraper_boxscores_skips_missing_source_key(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_select
    ):
        """Skips games with missing source key."""
        mock_scraper = MagicMock()
        mock_scrapers.return_value = {"NBA": mock_scraper}

        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        # Return game with missing source key
        mock_select.return_value = [(1, None, date(2024, 1, 15))]

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NBA",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
            only_missing=True,
        )

        result = manager.run(1, config)

        # Game skipped due to missing source key
        assert result["games"] == 0
        mock_scraper.fetch_single_boxscore.assert_not_called()

    @patch("sports_scraper.services.run_manager.select_games_for_boxscores")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_scraper_boxscores_handles_fetch_error(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_select
    ):
        """Handles boxscore fetch errors gracefully."""
        mock_scraper = MagicMock()
        mock_scraper.fetch_single_boxscore.side_effect = Exception("Scrape error")
        mock_scrapers.return_value = {"NBA": mock_scraper}

        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_select.return_value = [(1, "BOS202401150", date(2024, 1, 15))]

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NBA",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
            only_missing=True,
        )

        # Should not raise, logs warning
        result = manager.run(1, config)
        assert result["games"] == 0

    @patch("sports_scraper.services.run_manager.persist_game_payload")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_scraper_boxscores_without_only_missing(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_persist
    ):
        """Uses Sports Reference scraper for full date range."""
        mock_scraper = MagicMock()
        mock_payload = MagicMock()
        mock_payload.identity.source_game_key = "BOS202401150"
        mock_payload.identity.game_date = date(2024, 1, 15)
        mock_scraper.fetch_date_range.return_value = [mock_payload]
        # Use a non-API league so the SR scraper path is taken
        mock_scrapers.return_value = {"NCAAF": mock_scraper}

        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result.game_id = 1
        mock_result.enriched = True
        mock_result.has_player_stats = False
        mock_persist.return_value = mock_result

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NCAAF",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
            only_missing=False,
        )

        result = manager.run(1, config)

        assert result["games"] == 1
        mock_scraper.fetch_date_range.assert_called()

    @patch("sports_scraper.services.run_manager.persist_game_payload")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_scraper_boxscores_skips_missing_source_key_in_range(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_persist
    ):
        """Skips games with missing source_game_key in date range."""
        mock_scraper = MagicMock()
        mock_payload = MagicMock()
        mock_payload.identity.source_game_key = None  # Missing key
        mock_payload.identity.game_date = date(2024, 1, 15)
        mock_scraper.fetch_date_range.return_value = [mock_payload]
        mock_scrapers.return_value = {"NBA": mock_scraper}

        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NBA",
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
            only_missing=False,
        )

        result = manager.run(1, config)

        # Game skipped due to missing source key
        assert result["games"] == 0
        mock_persist.assert_not_called()

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_boxscore_raises_for_unknown_league_without_scraper(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session
    ):
        """Raises error when no scraper available for unsupported league."""
        mock_scrapers.return_value = {}  # No scrapers

        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NCAAF",  # Unsupported league without API fallback
            start_date=past_date,
            end_date=past_date,
            boxscores=True,
            odds=False,
            social=False,
            pbp=False,
        )

        # Should raise RuntimeError for unsupported league
        with pytest.raises(RuntimeError, match="No scraper implemented"):
            manager.run(1, config)


class TestScrapeRunManagerPbp:
    """Tests for PBP scraping in run method."""

    @patch("sports_scraper.services.run_manager.ingest_pbp_via_nhl_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_nhl_pbp_uses_api(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NHL PBP uses dedicated API."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.return_value = (5, 250)

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NHL",
            start_date=past_date,
            end_date=past_date,
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=False,
        )

        result = manager.run(1, config)

        assert result["pbp_games"] == 5

    @patch("sports_scraper.services.run_manager.ingest_pbp_via_ncaab_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_ncaab_pbp_uses_api(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NCAAB PBP uses dedicated API."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.return_value = (10, 500)

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NCAAB",
            start_date=past_date,
            end_date=past_date,
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=False,
        )

        result = manager.run(1, config)

        assert result["pbp_games"] == 10

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_live_pbp_uses_live_manager(
        self, mock_scrapers, mock_live_class,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session
    ):
        """Live PBP uses LiveFeedManager."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_live = MagicMock()
        mock_live.ingest_live_data.return_value = MagicMock(pbp_games=3)
        mock_live_class.return_value = mock_live

        manager = ScrapeRunManager()
        config = IngestionConfig(
            league_code="NHL",
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=True,
        )

        result = manager.run(1, config)

        assert result["pbp_games"] == 3
        mock_live.ingest_live_data.assert_called()

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_live_pbp_skipped_for_unsupported_league(
        self, mock_scrapers, mock_live_class,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session
    ):
        """Live PBP skipped for unsupported leagues."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_live = MagicMock()
        mock_live_class.return_value = mock_live

        manager = ScrapeRunManager()
        # Override supported leagues to exclude test league
        manager._supported_live_pbp_leagues = ("NBA", "NHL")

        config = IngestionConfig(
            league_code="NCAAF",  # Not in supported list
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=True,
        )

        result = manager.run(1, config)

        # Live PBP should not have been called
        mock_live.ingest_live_data.assert_not_called()

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_live_pbp_handles_exception(
        self, mock_scrapers, mock_live_class,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session
    ):
        """Live PBP handles exceptions gracefully."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_live = MagicMock()
        mock_live.ingest_live_data.side_effect = Exception("Live feed error")
        mock_live_class.return_value = mock_live

        manager = ScrapeRunManager()
        config = IngestionConfig(
            league_code="NHL",
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=True,
        )

        # Should not raise, handles exception internally
        result = manager.run(1, config)
        assert result["pbp_games"] == 0
        mock_complete.assert_called()  # Job run should be completed with error

    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_pbp_skips_future_dates(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session
    ):
        """PBP skips when all dates are in the future."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        future_date = date.today() + timedelta(days=5)
        config = IngestionConfig(
            league_code="NHL",
            start_date=future_date,
            end_date=future_date,
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=False,
        )

        result = manager.run(1, config)

        assert result["pbp_games"] == 0

    @patch("sports_scraper.services.run_manager.ingest_pbp_via_nhl_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_nhl_pbp_handles_api_error(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NHL PBP handles API errors gracefully."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.side_effect = Exception("NHL API error")

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NHL",
            start_date=past_date,
            end_date=past_date,
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=False,
        )

        # Should not raise
        result = manager.run(1, config)
        assert result["pbp_games"] == 0

    @patch("sports_scraper.services.run_manager.ingest_pbp_via_ncaab_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_ncaab_pbp_handles_api_error(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """NCAAB PBP handles API errors gracefully."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.side_effect = Exception("NCAAB API error")

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NCAAB",
            start_date=past_date,
            end_date=past_date,
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=False,
        )

        # Should not raise
        result = manager.run(1, config)
        assert result["pbp_games"] == 0

    @patch("sports_scraper.services.run_manager.ingest_pbp_via_nba_api")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_nba_api_pbp_used_for_nba(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """Official NBA API used for NBA PBP."""
        mock_scraper = MagicMock()
        mock_scrapers.return_value = {"NBA": mock_scraper}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.return_value = (3, 150)

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NBA",
            start_date=past_date,
            end_date=past_date,
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=False,
        )

        result = manager.run(1, config)

        assert result["pbp_games"] == 3
        mock_ingest.assert_called()

    @patch("sports_scraper.services.run_manager.ingest_pbp_via_sportsref")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_sportsref_pbp_handles_error(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_ingest
    ):
        """Sports Reference PBP handles errors gracefully."""
        mock_scraper = MagicMock()
        mock_scrapers.return_value = {"NBA": mock_scraper}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ingest.side_effect = Exception("Sportsref error")

        manager = ScrapeRunManager()
        past_date = date.today() - timedelta(days=5)
        config = IngestionConfig(
            league_code="NBA",
            start_date=past_date,
            end_date=past_date,
            boxscores=False,
            odds=False,
            social=False,
            pbp=True,
            batch_live_feed=False,
        )

        # Should not raise
        result = manager.run(1, config)
        assert result["pbp_games"] == 0


class TestScrapeRunManagerSocial:
    """Tests for social scraping in run method."""

    @patch("sports_scraper.services.run_manager.dispatch_social")
    @patch("sports_scraper.services.run_manager._social_task_exists_for_league", return_value=False)
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_social_skipped_for_unsupported_league(
        self, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_social_exists, mock_dispatch_social,
    ):
        """Social dispatch for NFL uses mock (no real DB needed)."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        config = IngestionConfig(
            league_code="NCAAF",
            boxscores=False,
            odds=False,
            social=True,
            pbp=False,
        )

        result = manager.run(1, config)

        assert result["social_posts"] == 0

    @patch("sports_scraper.jobs.social_tasks.map_social_to_games")
    @patch("sports_scraper.jobs.social_tasks.collect_team_social")
    @patch("celery.chain")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.queue_job_run", return_value=42)
    @patch("sports_scraper.services.run_manager.enforce_social_queue_limit", return_value=[])
    @patch("sports_scraper.services.run_manager._social_task_exists_for_league", return_value=False)
    def test_social_collects_posts(
        self, mock_exists, mock_enforce, mock_queue, mock_scrapers, mock_live,
        mock_conflicts, mock_missing, mock_complete, mock_start,
        mock_get_session, mock_chain, mock_collect, mock_map
    ):
        """Social dispatches per-day tasks for supported leagues."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        manager = ScrapeRunManager()
        config = IngestionConfig(
            league_code="NBA",
            boxscores=False,
            odds=False,
            social=True,
            pbp=False,
        )

        result = manager.run(1, config)

        assert "dispatched" in result["social_posts"]


class TestScrapeRunManagerErrorHandling:
    """Tests for error handling in run method."""

    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_updates_run_on_error(
        self, mock_scrapers, mock_live,
        mock_complete, mock_start, mock_get_session,
        mock_detect_missing, mock_detect_conflicts,
    ):
        """Updates run status to error on failure."""
        mock_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        # Make detect_external_id_conflicts raise to trigger error path
        # (detect_missing_pbp only runs when config.pbp=True)
        mock_detect_conflicts.side_effect = Exception("DB connection failed")

        manager = ScrapeRunManager()
        config = IngestionConfig(
            league_code="NHL",
            boxscores=False,
            odds=False,
            social=False,
            pbp=False,
        )

        with pytest.raises(Exception):
            manager.run(1, config)


class TestModuleImports:
    """Tests for module imports."""

    def test_has_scrape_run_manager(self):
        """Module has ScrapeRunManager class."""
        from sports_scraper.services import run_manager
        assert hasattr(run_manager, 'ScrapeRunManager')


class TestSocialTaskExistsForLeague:
    """Tests for _social_task_exists_for_league helper."""

    @patch("sports_scraper.services.run_manager.get_session")
    def test_returns_true_when_exists(self, mock_get_session):
        from sports_scraper.services.run_manager import _social_task_exists_for_league

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.first.return_value = MagicMock()

        assert _social_task_exists_for_league("NBA") is True

    @patch("sports_scraper.services.run_manager.get_session")
    def test_returns_false_when_not_exists(self, mock_get_session):
        from sports_scraper.services.run_manager import _social_task_exists_for_league

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.first.return_value = None

        assert _social_task_exists_for_league("NBA") is False

    @patch("sports_scraper.services.run_manager.get_session")
    def test_returns_true_on_exception(self, mock_get_session):
        """On DB failure, assume task exists (fail-closed) to prevent duplicate dispatch."""
        from sports_scraper.services.run_manager import _social_task_exists_for_league

        mock_get_session.return_value.__enter__ = MagicMock(side_effect=Exception("db err"))
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        assert _social_task_exists_for_league("NBA") is True


class TestSyncOdds:
    """Tests for _sync_odds method."""

    @patch("sports_scraper.odds.synchronizer.OddsSynchronizer")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.start_job_run", return_value=5)
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_sync_odds_success(self, mock_scrapers, mock_live, mock_gs, mock_start, mock_complete, mock_sync_cls):
        mock_scrapers.return_value = {}
        mock_sync = MagicMock()
        mock_sync.sync.return_value = 42
        mock_sync_cls.return_value = mock_sync

        manager = ScrapeRunManager()
        config = MagicMock()
        config.league_code = "NBA"
        summary = {"odds": 0}

        manager._sync_odds(1, config, summary, MagicMock(), MagicMock())
        assert summary["odds"] == 42
        mock_complete.assert_called_with(5, "success")

    @patch("sports_scraper.odds.synchronizer.OddsSynchronizer")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.start_job_run", return_value=5)
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_sync_odds_failure(self, mock_scrapers, mock_live, mock_gs, mock_start, mock_complete, mock_sync_cls):
        mock_scrapers.return_value = {}
        mock_sync = MagicMock()
        mock_sync.sync.side_effect = Exception("api down")
        mock_sync_cls.return_value = mock_sync

        manager = ScrapeRunManager()
        config = MagicMock()
        config.league_code = "NBA"
        summary = {"odds": 0}

        manager._sync_odds(1, config, summary, MagicMock(), MagicMock())
        mock_complete.assert_called_with(5, "error", "api down")
