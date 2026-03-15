"""Tests for odds/synchronizer.py module."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


from sports_scraper.odds.synchronizer import OddsSynchronizer
from sports_scraper.persistence.odds import OddsUpsertResult


class TestOddsSynchronizerInit:
    """Tests for OddsSynchronizer initialization."""

    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_creates_client(self, mock_client_cls):
        """Initializes with OddsAPIClient."""
        sync = OddsSynchronizer()
        mock_client_cls.assert_called_once()
        assert sync.client is not None


class TestOddsSynchronizerSync:
    """Tests for sync method."""

    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_skips_when_odds_disabled(self, mock_client_cls):
        """Skips sync when odds is disabled in config."""
        from sports_scraper.models import IngestionConfig

        config = IngestionConfig(
            league_code="NBA",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            odds=False,
        )

        sync = OddsSynchronizer()
        result = sync.sync(config)

        assert result == 0

    @patch("sports_scraper.odds.synchronizer.today_et")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_uses_historical_for_past_dates(self, mock_client_cls, mock_today):
        """Uses historical API for past dates."""
        from sports_scraper.models import IngestionConfig

        mock_today.return_value = date(2024, 1, 20)  # Today is Jan 20

        config = IngestionConfig(
            league_code="NBA",
            start_date=date(2024, 1, 15),  # All dates are in the past
            end_date=date(2024, 1, 17),
            odds=True,
        )

        mock_client = MagicMock()
        mock_client.fetch_historical_odds.return_value = []
        mock_client_cls.return_value = mock_client

        sync = OddsSynchronizer()
        result = sync.sync(config)

        # Should have called historical API
        mock_client.fetch_historical_odds.assert_called()
        mock_client.fetch_mainlines.assert_not_called()

    @patch("sports_scraper.odds.synchronizer.today_et")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_uses_live_for_future_dates(self, mock_client_cls, mock_today):
        """Uses live API for future dates."""
        from sports_scraper.models import IngestionConfig

        mock_today.return_value = date(2024, 1, 10)  # Today is Jan 10

        config = IngestionConfig(
            league_code="NBA",
            start_date=date(2024, 1, 15),  # All dates are in the future
            end_date=date(2024, 1, 17),
            odds=True,
        )

        mock_client = MagicMock()
        mock_client.fetch_mainlines.return_value = []
        mock_client_cls.return_value = mock_client

        sync = OddsSynchronizer()
        result = sync.sync(config)

        # Should have called live API
        mock_client.fetch_mainlines.assert_called()
        mock_client.fetch_historical_odds.assert_not_called()

    @patch("sports_scraper.odds.synchronizer.today_et")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_uses_both_for_mixed_dates(self, mock_client_cls, mock_today):
        """Uses both APIs for mixed date range."""
        from sports_scraper.models import IngestionConfig

        mock_today.return_value = date(2024, 1, 16)  # Today is Jan 16

        config = IngestionConfig(
            league_code="NBA",
            start_date=date(2024, 1, 14),  # Spans past and future
            end_date=date(2024, 1, 18),
            odds=True,
        )

        mock_client = MagicMock()
        mock_client.fetch_historical_odds.return_value = []
        mock_client.fetch_mainlines.return_value = []
        mock_client_cls.return_value = mock_client

        sync = OddsSynchronizer()
        result = sync.sync(config)

        # Should have called both APIs
        mock_client.fetch_historical_odds.assert_called()
        mock_client.fetch_mainlines.assert_called()


class TestOddsSynchronizerSyncLive:
    """Tests for _sync_live method."""

    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_returns_zero_when_no_snapshots(self, mock_client_cls):
        """Returns 0 when no odds found."""
        mock_client = MagicMock()
        mock_client.fetch_mainlines.return_value = []
        mock_client_cls.return_value = mock_client

        sync = OddsSynchronizer()
        result = sync._sync_live("NBA", date(2024, 1, 15), date(2024, 1, 15), None)

        assert result == 0

    @patch("sports_scraper.odds.synchronizer.get_session")
    @patch("sports_scraper.odds.synchronizer.upsert_odds")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_persists_snapshots(self, mock_client_cls, mock_upsert, mock_get_session):
        """Persists fetched snapshots."""
        mock_snapshot = MagicMock()
        mock_client = MagicMock()
        mock_client.fetch_mainlines.return_value = [mock_snapshot]
        mock_client_cls.return_value = mock_client

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_upsert.return_value = OddsUpsertResult.PERSISTED

        sync = OddsSynchronizer()
        result = sync._sync_live("NBA", date(2024, 1, 15), date(2024, 1, 15), None)

        assert result == 1
        mock_upsert.assert_called_once()


class TestOddsSynchronizerSyncHistorical:
    """Tests for _sync_historical method."""

    @patch("sports_scraper.odds.synchronizer.get_session")
    @patch("sports_scraper.odds.synchronizer.upsert_odds")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_iterates_through_days(self, mock_client_cls, mock_upsert, mock_get_session):
        """Iterates through each day in range."""
        mock_snapshot = MagicMock()
        mock_client = MagicMock()
        mock_client.fetch_historical_odds.return_value = [mock_snapshot]
        mock_client_cls.return_value = mock_client

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_upsert.return_value = OddsUpsertResult.PERSISTED

        sync = OddsSynchronizer()
        result = sync._sync_historical(
            "NBA", date(2024, 1, 15), date(2024, 1, 17), None
        )

        # Should have called fetch for each of 3 days
        assert mock_client.fetch_historical_odds.call_count == 3
        assert result == 3  # 1 per day


class TestOddsSynchronizerSyncSingleDate:
    """Tests for sync_single_date method."""

    @patch("sports_scraper.odds.synchronizer.today_et")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_uses_historical_for_past_date(self, mock_client_cls, mock_today):
        """Uses historical API for past date."""
        mock_today.return_value = date(2024, 1, 20)

        mock_client = MagicMock()
        mock_client.fetch_historical_odds.return_value = []
        mock_client_cls.return_value = mock_client

        sync = OddsSynchronizer()
        result = sync.sync_single_date("NBA", date(2024, 1, 15))

        mock_client.fetch_historical_odds.assert_called()
        mock_client.fetch_mainlines.assert_not_called()

    @patch("sports_scraper.odds.synchronizer.today_et")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_uses_live_for_today(self, mock_client_cls, mock_today):
        """Uses live API for today."""
        mock_today.return_value = date(2024, 1, 15)

        mock_client = MagicMock()
        mock_client.fetch_mainlines.return_value = []
        mock_client_cls.return_value = mock_client

        sync = OddsSynchronizer()
        result = sync.sync_single_date("NBA", date(2024, 1, 15))

        mock_client.fetch_mainlines.assert_called()
        mock_client.fetch_historical_odds.assert_not_called()


class TestOddsSynchronizerPersistSnapshots:
    """Tests for _persist_snapshots method."""

    @patch("sports_scraper.odds.synchronizer.get_session")
    @patch("sports_scraper.odds.synchronizer.upsert_odds")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_counts_inserted(self, mock_client_cls, mock_upsert, mock_get_session):
        """Counts successfully inserted odds."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_upsert.return_value = OddsUpsertResult.PERSISTED

        mock_snapshot = MagicMock()
        snapshots = [mock_snapshot, mock_snapshot, mock_snapshot]

        sync = OddsSynchronizer()
        result = sync._persist_snapshots(snapshots, "NBA")

        assert result == 3

    @patch("sports_scraper.odds.synchronizer.get_session")
    @patch("sports_scraper.odds.synchronizer.upsert_odds")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_counts_skipped(self, mock_client_cls, mock_upsert, mock_get_session):
        """Counts skipped odds."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_upsert.return_value = OddsUpsertResult.SKIPPED_NO_MATCH  # All skipped

        mock_snapshot = MagicMock()
        snapshots = [mock_snapshot, mock_snapshot]

        sync = OddsSynchronizer()
        result = sync._persist_snapshots(snapshots, "NBA")

        assert result == 0

    @patch("sports_scraper.odds.synchronizer.get_session")
    @patch("sports_scraper.odds.synchronizer.upsert_odds")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_handles_exceptions(self, mock_client_cls, mock_upsert, mock_get_session):
        """Handles exceptions during upsert."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_upsert.side_effect = Exception("Database error")

        mock_snapshot = MagicMock()
        mock_snapshot.game_date = date(2024, 1, 15)
        mock_snapshot.home_team.name = "Team A"
        mock_snapshot.away_team.name = "Team B"
        snapshots = [mock_snapshot]

        sync = OddsSynchronizer()
        result = sync._persist_snapshots(snapshots, "NBA")

        # Should have rolled back and continued
        mock_session.rollback.assert_called()
        assert result == 0

    @patch("sports_scraper.odds.synchronizer.delete_stale_fairbet_odds")
    @patch("sports_scraper.odds.synchronizer.now_utc")
    @patch("sports_scraper.odds.synchronizer.get_session")
    @patch("sports_scraper.odds.synchronizer.upsert_odds")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_calls_delete_stale_after_upserts(
        self, mock_client_cls, mock_upsert, mock_get_session, mock_now, mock_delete_stale
    ):
        """Calls delete_stale_fairbet_odds after upserts with batch timestamp."""
        batch_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_now.return_value = batch_ts

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_upsert.return_value = OddsUpsertResult.PERSISTED
        mock_delete_stale.return_value = 3

        mock_snapshot = MagicMock()
        snapshots = [mock_snapshot]

        sync = OddsSynchronizer()
        result = sync._persist_snapshots(snapshots, "NBA")

        assert result == 1
        mock_delete_stale.assert_called_once_with(mock_session, batch_ts)

    @patch("sports_scraper.odds.synchronizer.delete_stale_fairbet_odds")
    @patch("sports_scraper.odds.synchronizer.now_utc")
    @patch("sports_scraper.odds.synchronizer.get_session")
    @patch("sports_scraper.odds.synchronizer.upsert_odds")
    @patch("sports_scraper.odds.synchronizer.OddsAPIClient")
    def test_skips_delete_stale_when_no_inserts(
        self, mock_client_cls, mock_upsert, mock_get_session, mock_now, mock_delete_stale
    ):
        """Skips delete_stale_fairbet_odds when no rows were inserted."""
        mock_now.return_value = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_upsert.return_value = OddsUpsertResult.SKIPPED_NO_MATCH

        mock_snapshot = MagicMock()
        snapshots = [mock_snapshot]

        sync = OddsSynchronizer()
        result = sync._persist_snapshots(snapshots, "NBA")

        assert result == 0
        mock_delete_stale.assert_not_called()
