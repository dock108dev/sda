"""Comprehensive tests for services modules with mocked DB sessions."""

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


# ============================================================================
# Tests for services/game_selection.py
# ============================================================================

from sports_scraper.services.game_selection import (
    select_games_for_boxscores,
    select_games_for_pbp_sportsref,
)


class TestSelectGamesForBoxscores:
    """Tests for select_games_for_boxscores function."""

    def test_no_league_returns_empty(self):
        """Returns empty list when league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_boxscores(
            mock_session, "INVALID", date(2024, 1, 15), date(2024, 1, 15)
        )

        assert result == []

    def test_returns_game_tuples(self):
        """Returns list of (game_id, source_key, game_date) tuples."""
        mock_session = MagicMock()

        # Mock league query
        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock games query
        mock_game = MagicMock()
        mock_game.id = 100
        mock_game.source_game_key = "ABC123"
        mock_game.game_date = datetime(2024, 1, 15, 19, 0, tzinfo=UTC)
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_game]

        result = select_games_for_boxscores(
            mock_session, "NBA", date(2024, 1, 15), date(2024, 1, 15)
        )

        assert len(result) == 1
        assert result[0][0] == 100
        assert result[0][1] == "ABC123"
        assert result[0][2] == date(2024, 1, 15)

    def test_only_missing_filter(self):
        """Tests only_missing filter is applied."""
        mock_session = MagicMock()
        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        result = select_games_for_boxscores(
            mock_session, "NBA", date(2024, 1, 15), date(2024, 1, 15),
            only_missing=True
        )

        assert result == []

    def test_updated_before_filter(self):
        """Tests updated_before filter is applied."""
        mock_session = MagicMock()
        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league
        mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        cutoff = datetime(2024, 1, 14, tzinfo=UTC)
        result = select_games_for_boxscores(
            mock_session, "NBA", date(2024, 1, 15), date(2024, 1, 15),
            updated_before=cutoff
        )

        assert result == []



class TestSelectGamesForPbpSportsref:
    """Tests for select_games_for_pbp_sportsref function."""

    def test_no_league_returns_empty(self):
        """Returns empty list when league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = select_games_for_pbp_sportsref(
            mock_session,
            league_code="INVALID",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            only_missing=False,
            updated_before=None,
        )

        assert result == []

    def test_returns_game_tuples(self):
        """Returns list of (game_id, source_key, game_date) tuples."""
        mock_session = MagicMock()

        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_session.query.return_value.filter.return_value.all.return_value = [
            (100, "202401150BOS", datetime(2024, 1, 15, 19, 0, tzinfo=UTC))
        ]

        result = select_games_for_pbp_sportsref(
            mock_session,
            league_code="NBA",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            only_missing=False,
            updated_before=None,
        )

        assert len(result) == 1
        assert result[0][0] == 100
        assert result[0][1] == "202401150BOS"
        assert result[0][2] == date(2024, 1, 15)

    def test_filters_none_source_keys(self):
        """Filters out entries with None source_key."""
        mock_session = MagicMock()

        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        mock_session.query.return_value.filter.return_value.all.return_value = [
            (100, "202401150BOS", datetime(2024, 1, 15, tzinfo=UTC)),
            (101, None, datetime(2024, 1, 15, tzinfo=UTC)),
        ]

        result = select_games_for_pbp_sportsref(
            mock_session,
            league_code="NBA",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            only_missing=False,
            updated_before=None,
        )

        assert len(result) == 1
        assert result[0][0] == 100


# ============================================================================
# Tests for services/diagnostics.py
# ============================================================================

from sports_scraper.services.diagnostics import (
    EXTERNAL_ID_KEYS,
    PBP_MIN_PLAY_COUNT,
    PBP_SUPPORTED_LEAGUES,
    detect_external_id_conflicts,
    detect_missing_pbp,
)


class TestDiagnosticsConstants:
    """Tests for diagnostics constants."""

    def test_pbp_supported_leagues(self):
        assert "NBA" in PBP_SUPPORTED_LEAGUES
        assert "NHL" in PBP_SUPPORTED_LEAGUES

    def test_pbp_min_play_count(self):
        assert PBP_MIN_PLAY_COUNT >= 1

    def test_external_id_keys(self):
        assert "NBA" in EXTERNAL_ID_KEYS
        assert "NHL" in EXTERNAL_ID_KEYS
        assert EXTERNAL_ID_KEYS["NBA"] == "nba_game_id"
        assert EXTERNAL_ID_KEYS["NHL"] == "nhl_game_pk"


class TestDetectMissingPbp:
    """Tests for detect_missing_pbp function."""

    def test_no_league_returns_empty(self):
        """Returns empty list when league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = detect_missing_pbp(mock_session, league_code="INVALID")

        assert result == []

    def test_returns_missing_game_ids(self):
        """Returns list of game IDs missing PBP."""
        mock_session = MagicMock()

        mock_league = MagicMock()
        mock_league.id = 1
        mock_league.code = "NBA"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock query results - games with no plays
        mock_session.query.return_value.outerjoin.return_value.filter.return_value.filter.return_value.group_by.return_value.having.return_value.all.return_value = [
            (100, "live", 0, "12345"),
            (101, "final", 0, "12346"),
        ]

        # Mock execute for insert
        mock_session.execute.return_value = MagicMock()

        result = detect_missing_pbp(mock_session, league_code="NBA")

        assert len(result) == 2
        assert 100 in result
        assert 101 in result


class TestDetectExternalIdConflicts:
    """Tests for detect_external_id_conflicts function."""

    def test_no_league_returns_zero(self):
        """Returns 0 when league not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        result = detect_external_id_conflicts(mock_session, league_code="INVALID")

        assert result == 0

    def test_no_external_key_returns_zero(self):
        """Returns 0 when no external key defined for league."""
        mock_session = MagicMock()
        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # MLB has no external_id_key defined
        result = detect_external_id_conflicts(mock_session, league_code="MLB")

        assert result == 0

    def test_no_duplicates_returns_zero(self):
        """Returns 0 when no duplicate external IDs found."""
        mock_session = MagicMock()
        mock_league = MagicMock()
        mock_league.id = 1
        mock_session.query.return_value.filter.return_value.first.return_value = mock_league

        # Mock duplicate query - no results
        mock_session.query.return_value.filter.return_value.filter.return_value.group_by.return_value.having.return_value.all.return_value = []

        result = detect_external_id_conflicts(mock_session, league_code="NBA")

        assert result == 0


# ============================================================================
# Tests for services/job_runs.py
# ============================================================================

from sports_scraper.services.job_runs import (
    activate_queued_job_run,
    complete_job_run,
    start_job_run,
)


class TestStartJobRun:
    """Tests for start_job_run function."""

    @patch("sports_scraper.services.job_runs.get_session")
    def test_creates_run_record(self, mock_get_session):
        """Creates a job run record and returns ID."""
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.id = 123

        # Mock context manager
        mock_get_session.return_value.__enter__.return_value = mock_session

        with patch("sports_scraper.services.job_runs.db_models") as mock_db:
            mock_db.SportsJobRun.return_value = mock_run

            result = start_job_run(
                phase="boxscore_ingestion",
                leagues=["NBA", "NHL"],
            )

            assert result == 123
            mock_session.add.assert_called_once()
            mock_session.flush.assert_called_once()


class TestCompleteJobRun:
    """Tests for complete_job_run function."""

    @patch("sports_scraper.services.job_runs.get_session")
    def test_updates_run_record(self, mock_get_session):
        """Updates job run with completion data."""
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.started_at = datetime.now(UTC)
        mock_session.get.return_value = mock_run

        mock_get_session.return_value.__enter__.return_value = mock_session

        complete_job_run(
            run_id=123,
            status="completed",
        )

        assert mock_run.status == "completed"
        mock_session.flush.assert_called_once()

    @patch("sports_scraper.services.job_runs.get_session")
    def test_handles_missing_run(self, mock_get_session):
        """Handles case when run not found."""
        mock_session = MagicMock()
        mock_session.get.return_value = None

        mock_get_session.return_value.__enter__.return_value = mock_session

        # Should not raise
        complete_job_run(
            run_id=999,
            status="completed",
        )

    @patch("sports_scraper.services.job_runs.get_session")
    def test_updates_with_error(self, mock_get_session):
        """Updates job run with error summary."""
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.started_at = datetime.now(UTC)
        mock_session.get.return_value = mock_run

        mock_get_session.return_value.__enter__.return_value = mock_session

        complete_job_run(
            run_id=123,
            status="failed",
            error_summary="Connection timeout",
        )

        assert mock_run.status == "failed"
        assert mock_run.error_summary == "Connection timeout"

    @patch("sports_scraper.services.job_runs.get_session")
    def test_does_not_overwrite_canceled_status(self, mock_get_session):
        """Keeps canceled runs canceled even when completion handler runs."""
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.status = "canceled"
        mock_run.started_at = datetime.now(UTC)
        mock_session.get.return_value = mock_run

        mock_get_session.return_value.__enter__.return_value = mock_session

        complete_job_run(
            run_id=123,
            status="success",
        )

        assert mock_run.status == "canceled"
        mock_session.flush.assert_not_called()


class TestActivateQueuedJobRun:
    """Tests for activate_queued_job_run behavior."""

    @patch("sports_scraper.services.job_runs.get_session")
    def test_raises_when_run_was_canceled(self, mock_get_session):
        """Canceled queued runs should not be reactivated."""
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.id = 42
        mock_run.phase = "social"
        mock_run.status = "canceled"
        mock_run.leagues = ["MLB"]
        mock_session.get.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        with pytest.raises(RuntimeError, match="canceled before pickup"):
            activate_queued_job_run(42)


# ============================================================================
# Tests for services/ingestion.py
# ============================================================================

from sports_scraper.services.ingestion import run_ingestion


class TestRunIngestion:
    """Tests for run_ingestion function."""

    @patch("sports_scraper.services.ingestion.ScrapeRunManager")
    @patch("sports_scraper.services.ingestion.IngestionConfig")
    def test_creates_manager_and_runs(self, mock_config_cls, mock_manager_cls):
        """Creates manager and calls run method."""
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config

        mock_manager = MagicMock()
        mock_manager.run.return_value = {"status": "completed", "records": 50}
        mock_manager_cls.return_value = mock_manager

        config_payload = {
            "league_code": "NBA",
            "start_date": "2024-01-15",
            "end_date": "2024-01-15",
            "phases": ["boxscore"],
        }

        result = run_ingestion(run_id=123, config_payload=config_payload)

        mock_config_cls.assert_called_once_with(**config_payload)
        mock_manager.run.assert_called_once_with(123, mock_config)
        assert result == {"status": "completed", "records": 50}
