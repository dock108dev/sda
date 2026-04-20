"""Tests for the weekly Odds API credit quota guard."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sports_scraper.utils.odds_quota import (
    _week_key,
    get_weekly_usage,
    is_quota_exceeded,
    quota_status,
    record_usage,
)


@pytest.fixture(autouse=True)
def _mock_settings():
    """Provide a default weekly cap for all tests."""
    cfg = MagicMock()
    cfg.weekly_credit_cap = 1_250_000
    with patch("sports_scraper.utils.odds_quota.get_weekly_cap", return_value=1_250_000):
        yield


class TestWeekKey:
    def test_format(self):
        key = _week_key()
        assert key.startswith("odds_api:weekly_credits:")
        parts = key.split(":")
        assert len(parts) == 4
        # year and week are numeric
        assert parts[2].isdigit()
        assert parts[3].isdigit()


class TestRecordUsage:
    def test_increments_counter(self):
        mock_redis = MagicMock()
        mock_redis.incrby.return_value = 500
        mock_redis.ttl.return_value = 600_000

        with patch("sports_scraper.utils.odds_quota._get_redis", return_value=mock_redis):
            result = record_usage(500)

        assert result == 500
        mock_redis.incrby.assert_any_call(_week_key(), 500)

    def test_sets_ttl_on_new_key(self):
        mock_redis = MagicMock()
        mock_redis.incrby.return_value = 100
        mock_redis.ttl.return_value = -1  # No TTL set yet

        with patch("sports_scraper.utils.odds_quota._get_redis", return_value=mock_redis):
            record_usage(100)

        assert mock_redis.expire.called

    def test_skips_zero_credits(self):
        mock_redis = MagicMock()
        with patch("sports_scraper.utils.odds_quota._get_redis", return_value=mock_redis):
            record_usage(0)

        mock_redis.incrby.assert_not_called()

    def test_redis_failure_returns_zero(self):
        with patch("sports_scraper.utils.odds_quota._get_redis", side_effect=Exception("down")):
            result = record_usage(100)

        assert result == 0


class TestIsQuotaExceeded:
    def test_under_cap(self):
        with patch("sports_scraper.utils.odds_quota.get_weekly_usage", return_value=500_000):
            assert is_quota_exceeded() is False

    def test_at_cap(self):
        with patch("sports_scraper.utils.odds_quota.get_weekly_usage", return_value=1_250_000):
            assert is_quota_exceeded() is True

    def test_over_cap(self):
        with patch("sports_scraper.utils.odds_quota.get_weekly_usage", return_value=2_000_000):
            assert is_quota_exceeded() is True


class TestQuotaStatus:
    def test_returns_dict(self):
        with patch("sports_scraper.utils.odds_quota.get_weekly_usage", return_value=300_000):
            status = quota_status()

        assert status["weekly_cap"] == 1_250_000
        assert status["weekly_used"] == 300_000
        assert status["weekly_remaining"] == 950_000
        assert status["exceeded"] is False

    def test_exceeded_status(self):
        with patch("sports_scraper.utils.odds_quota.get_weekly_usage", return_value=1_500_000):
            status = quota_status()

        assert status["exceeded"] is True
        assert status["weekly_remaining"] == 0


class TestQuotaExceededInClient:
    """Test that QuotaExceededError is raised by the client."""

    @pytest.fixture()
    def _blocked_client(self):
        """Patch quota check to always block and settings for client init."""
        mock_cfg = MagicMock()
        mock_cfg.base_url = "https://api.the-odds-api.com/v4"
        mock_cfg.request_timeout_seconds = 15

        with patch("sports_scraper.odds.client.is_quota_exceeded", return_value=True), \
             patch("sports_scraper.odds.client.settings") as s:
            s.odds_api_key = "test-key"
            s.odds_config = mock_cfg
            s.scraper_config.html_cache_dir = "/tmp/test_cache"
            yield

    def test_fetch_mainlines_blocked(self, _blocked_client):
        from sports_scraper.odds.client import OddsAPIClient, QuotaExceededError

        client = OddsAPIClient()
        with pytest.raises(QuotaExceededError):
            client.fetch_mainlines("NBA", MagicMock(), MagicMock())

    def test_fetch_historical_blocked(self, _blocked_client):
        from sports_scraper.odds.client import OddsAPIClient, QuotaExceededError

        client = OddsAPIClient()
        with pytest.raises(QuotaExceededError):
            client.fetch_historical_odds("NBA", MagicMock())

    def test_fetch_props_blocked(self, _blocked_client):
        from sports_scraper.odds.client import OddsAPIClient, QuotaExceededError

        client = OddsAPIClient()
        with pytest.raises(QuotaExceededError):
            client.fetch_event_props("NBA", "event-123")
