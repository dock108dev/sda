"""Tests for services/run_manager.py module."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.services.run_manager import ScrapeRunManager


class TestScrapeRunManagerInit:
    """Tests for ScrapeRunManager initialization."""

    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_init_creates_components(
        self, mock_get_scrapers, mock_live
    ):
        """Initializes with all required components."""
        mock_get_scrapers.return_value = {}

        manager = ScrapeRunManager()

        assert manager.scrapers == {}
        mock_live.assert_called_once()

    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_supported_leagues(
        self, mock_get_scrapers, mock_live
    ):
        """Manager has supported league lists."""
        mock_get_scrapers.return_value = {}

        manager = ScrapeRunManager()

        assert "NBA" in manager._supported_social_leagues
        assert "NHL" in manager._supported_social_leagues
        assert "NBA" in manager._supported_live_pbp_leagues
        assert "NHL" in manager._supported_live_pbp_leagues
        assert "NCAAB" in manager._supported_live_pbp_leagues

class TestScrapeRunManagerUpdateRun:
    """Tests for _update_run method."""

    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.get_session")
    def test_update_run_sets_attributes(
        self, mock_get_session, mock_get_scrapers, mock_live
    ):
        """Updates run record with provided attributes."""
        mock_get_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        manager = ScrapeRunManager()
        manager._update_run(123, status="running", started_at=datetime.now(UTC))

        assert mock_run.status == "running"
        mock_session.flush.assert_called_once()

    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.get_session")
    def test_update_run_handles_missing(
        self, mock_get_session, mock_get_scrapers, mock_live
    ):
        """Handles missing run record gracefully."""
        mock_get_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_get_session.return_value.__enter__.return_value = mock_session

        manager = ScrapeRunManager()
        # Should not raise
        manager._update_run(999, status="running")

class TestScrapeRunManagerRun:
    """Tests for run method."""

    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_run_requires_scraper_for_boxscores(
        self, mock_get_scrapers, mock_live
    ):
        """Raises error when no scraper for boxscore league."""
        mock_get_scrapers.return_value = {}  # No scrapers

        from sports_scraper.models import IngestionConfig
        config = IngestionConfig(
            league_code="NCAAF",  # NCAAF not in API dispatch
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            boxscores=True,
        )

        manager = ScrapeRunManager()
        with pytest.raises(RuntimeError, match="No scraper implemented"):
            manager.run(123, config)

    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_run_returns_summary(
        self,
        mock_get_scrapers,
        mock_live,
        mock_get_session,
        mock_detect_missing,
        mock_detect_conflicts,
    ):
        """Returns summary dict with counts."""
        mock_get_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        from sports_scraper.models import IngestionConfig
        config = IngestionConfig(
            league_code="NHL",  # NHL can run without scraper for boxscores
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            boxscores=False,
            odds=False,
            social=False,
            pbp=False,
        )

        manager = ScrapeRunManager()
        result = manager.run(123, config)

        assert isinstance(result, dict)
        assert "games" in result
        assert "social_posts" in result
        assert "pbp_games" in result

    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    @patch("sports_scraper.services.run_manager.dispatch_social")
    @patch("sports_scraper.services.run_manager._social_task_exists_for_league", return_value=False)
    def test_run_skips_unsupported_social_leagues(
        self,
        mock_social_exists,
        mock_dispatch_social,
        mock_get_scrapers,
        mock_live,
        mock_get_session,
        mock_detect_missing,
        mock_detect_conflicts,
        mock_complete_job,
        mock_start_job,
    ):
        """Social dispatch for NFL uses mock session (no real DB needed)."""
        mock_get_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        mock_start_job.return_value = 1

        from sports_scraper.models import IngestionConfig
        config = IngestionConfig(
            league_code="NFL",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            boxscores=False,
            odds=False,
            social=True,
            pbp=False,
        )

        manager = ScrapeRunManager()
        result = manager.run(123, config)

        assert result["social_posts"] == 0

class TestScrapeRunManagerIntegration:
    """Integration-style tests for run manager."""

    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_run_with_no_phases_enabled(
        self,
        mock_get_scrapers,
        mock_live,
        mock_get_session,
        mock_detect_missing,
        mock_detect_conflicts,
    ):
        """Run with no phases enabled still completes."""
        mock_get_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        from sports_scraper.models import IngestionConfig
        config = IngestionConfig(
            league_code="NHL",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            boxscores=False,
            odds=False,
            social=False,
            pbp=False,
        )

        manager = ScrapeRunManager()
        result = manager.run(123, config)

        assert result["games"] == 0
        assert result["social_posts"] == 0
        assert result["pbp_games"] == 0

    @patch("sports_scraper.services.run_manager.start_job_run")
    @patch("sports_scraper.services.run_manager.complete_job_run")
    @patch("sports_scraper.services.run_manager.detect_external_id_conflicts")
    @patch("sports_scraper.services.run_manager.detect_missing_pbp")
    @patch("sports_scraper.services.run_manager.get_session")
    @patch("sports_scraper.services.run_manager.LiveFeedManager")
    @patch("sports_scraper.services.run_manager.get_all_scrapers")
    def test_run_handles_updated_before(
        self,
        mock_get_scrapers,
        mock_live,
        mock_get_session,
        mock_detect_missing,
        mock_detect_conflicts,
        mock_complete_job,
        mock_start_job,
    ):
        """Run handles updated_before filter."""
        mock_get_scrapers.return_value = {}
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        mock_start_job.return_value = 1

        from sports_scraper.models import IngestionConfig
        config = IngestionConfig(
            league_code="NHL",
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 15),
            updated_before=date(2024, 1, 12),
            boxscores=False,
            odds=False,
            social=False,
            pbp=False,
        )

        manager = ScrapeRunManager()
        result = manager.run(123, config)

        # Should complete without error
        assert isinstance(result, dict)
