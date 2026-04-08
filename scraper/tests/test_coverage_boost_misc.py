"""Targeted tests for low-coverage scraper files."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. NFL Advanced Stats Ingestion (lines 84-188)
# ---------------------------------------------------------------------------


class TestProbeHistoricalGameIds:
    """Cover _probe_historical_game_ids (lines 92-170)."""

    def test_probe_returns_cached(self):
        """Cover cached path (lines 106-112)."""
        from sports_scraper.services.pbp_nba import _probe_historical_game_ids

        cached_data = [{"home": "BOS", "away": "NYK", "date": "2024-11-01", "gid": "0022400001"}]

        mock_cache = MagicMock()
        mock_cache.get.return_value = cached_data

        with patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2024, 11, 1)), \
             patch("sports_scraper.utils.cache.APICache", return_value=mock_cache), \
             patch("sports_scraper.config.settings") as mock_settings, \
             patch("sports_scraper.utils.date_utils.season_from_date", return_value=2024):
            mock_settings.scraper_config.html_cache_dir = "/tmp/cache"
            result = _probe_historical_game_ids(date(2024, 11, 1), date(2024, 11, 30))

        assert ("BOS", "NYK", date(2024, 11, 1)) in result
        assert result[("BOS", "NYK", date(2024, 11, 1))] == "0022400001"

    def test_probe_fetches_from_api(self):
        """Cover API fetch path (lines 120-170) including 200, non-200, and break."""
        from sports_scraper.services.pbp_nba import _probe_historical_game_ids

        success_resp = MagicMock(status_code=200)
        success_resp.json.return_value = {
            "game": {
                "gameTimeUTC": "2024-11-01T23:30:00Z",
                "homeTeam": {"teamTricode": "BOS"},
                "awayTeam": {"teamTricode": "NYK"},
            }
        }
        miss_resp = MagicMock(status_code=404)

        call_count = {"n": 0}
        def mock_get(url):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return success_resp
            return miss_resp

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        with patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2024, 11, 1)), \
             patch("sports_scraper.utils.cache.APICache", return_value=mock_cache), \
             patch("sports_scraper.config.settings") as mock_settings, \
             patch("sports_scraper.utils.date_utils.season_from_date", return_value=2024), \
             patch("httpx.Client") as MockHttpxClient:
            mock_settings.scraper_config.html_cache_dir = "/tmp/cache"
            mock_client = MagicMock()
            mock_client.get.side_effect = mock_get
            MockHttpxClient.return_value = mock_client

            result = _probe_historical_game_ids(date(2024, 11, 1), date(2024, 11, 30))

        assert ("BOS", "NYK", date(2024, 11, 1)) in result
        mock_cache.put.assert_called_once()

    def test_probe_exception_consecutive_misses(self):
        """Cover exception branch (lines 151-155): consecutive exceptions trigger break."""
        from sports_scraper.services.pbp_nba import _probe_historical_game_ids

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        with patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2024, 11, 1)), \
             patch("sports_scraper.utils.cache.APICache", return_value=mock_cache), \
             patch("sports_scraper.config.settings") as mock_settings, \
             patch("sports_scraper.utils.date_utils.season_from_date", return_value=2024), \
             patch("httpx.Client") as MockHttpxClient:
            mock_settings.scraper_config.html_cache_dir = "/tmp/cache"
            mock_client = MagicMock()
            mock_client.get.side_effect = Exception("timeout")
            MockHttpxClient.return_value = mock_client

            result = _probe_historical_game_ids(date(2024, 11, 1), date(2024, 11, 30))

        assert result == {}
        mock_cache.put.assert_not_called()


class TestIngestPbpViaNbaApi:
    """Cover ingest_pbp_via_nba_api line 416 and game loop."""

    def test_game_not_found_continues(self):
        """Cover line 416: game is None -> continue."""
        from sports_scraper.services.pbp_nba import ingest_pbp_via_nba_api

        session = MagicMock()
        session.query.return_value.get.return_value = None

        with patch("sports_scraper.services.pbp_nba.populate_nba_game_ids"), \
             patch("sports_scraper.services.pbp_nba.select_games_for_pbp_nba_api", return_value=[(1, "0022400001")]):
            result = ingest_pbp_via_nba_api(
                session, run_id=1,
                start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
                only_missing=True, updated_before=None,
            )

        assert result == (0, 0)


# ---------------------------------------------------------------------------
# 3. Redis Lock (lines 39, 65-77)
# ---------------------------------------------------------------------------

class TestRedisLock:
    """Cover force_release_lock and edge cases."""

    def test_acquire_lock_redis_set_returns_false(self):
        """Cover line 39: set returns False -> return None."""
        from sports_scraper.utils.redis_lock import acquire_redis_lock

        mock_r = MagicMock()
        mock_r.set.return_value = False

        with patch("redis.from_url", return_value=mock_r), \
             patch("sports_scraper.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = acquire_redis_lock("lock:test")

        assert result is None

    def test_force_release_lock_deleted(self):
        """Cover lines 65-74: force_release_lock when key exists."""
        from sports_scraper.utils.redis_lock import force_release_lock

        mock_r = MagicMock()
        mock_r.delete.return_value = 1

        with patch("redis.from_url", return_value=mock_r), \
             patch("sports_scraper.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = force_release_lock("lock:test")

        assert result is True

    def test_force_release_lock_not_found(self):
        """Cover force_release_lock when key does not exist."""
        from sports_scraper.utils.redis_lock import force_release_lock

        mock_r = MagicMock()
        mock_r.delete.return_value = 0

        with patch("redis.from_url", return_value=mock_r), \
             patch("sports_scraper.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = force_release_lock("lock:test")

        assert result is False

    def test_force_release_lock_exception(self):
        """Cover lines 75-77: exception in force_release_lock."""
        from sports_scraper.utils.redis_lock import force_release_lock

        with patch("redis.from_url", side_effect=Exception("connection refused")), \
             patch("sports_scraper.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = force_release_lock("lock:test")

        assert result is False


# ---------------------------------------------------------------------------
# 4. Commit Loop (lines 92-98, 119-132, 141)
# ---------------------------------------------------------------------------

class TestCommitLoop:
    """Cover circuit breaker, error-status, unknown-status, and final-commit paths."""

    def test_circuit_breaker_stops_iteration(self):
        """Cover lines 92-98: max_consecutive_errors triggers break."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()

        def always_fail(s, item):
            raise ValueError("boom")

        result = commit_loop(
            session, [1, 2, 3, 4, 5], always_fail,
            max_consecutive_errors=2, label="test_cb",
        )

        assert result.errors == 2
        assert result.total == 2

    def test_error_status_returned(self):
        """Cover lines 124-128: process_fn returns 'error' string."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(session, [1, 2], lambda s, i: "error", label="test_err")

        assert result.errors == 2
        assert result.success == 0

    def test_unknown_status_treated_as_skip(self):
        """Cover lines 130-132: unrecognized status string."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(session, [1], lambda s, i: "banana", label="test_unk")

        assert result.skipped == 1
        assert result.success == 0

    def test_skipped_with_reason(self):
        """Cover lines 119-123: 'skipped:reason' status."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(session, [1, 2, 3], lambda s, i: "skipped:no_data", label="test_skip")

        assert result.skipped == 3
        assert result.skipped_reasons == {"no_data": 3}

    def test_final_commit_for_pending(self):
        """Cover line 141: final commit when pending > 0 at end of loop."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(session, [1, 2, 3], lambda s, i: "success", batch_size=5, label="test_final")

        assert result.success == 3
        assert session.commit.call_count == 1

    def test_batch_commit_triggers(self):
        """Cover line 136: batch commit when pending >= batch_size."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(session, [1, 2, 3, 4], lambda s, i: "success", batch_size=2, label="test_batch")

        assert result.success == 4
        assert session.commit.call_count == 2

    def test_circuit_breaker_with_mixed_errors_and_success(self):
        """Consecutive errors reset on success, CB only fires on consecutive."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        call_count = {"n": 0}
        def mixed_fn(s, item):
            call_count["n"] += 1
            if call_count["n"] in (1, 3, 4):
                raise ValueError("fail")
            return "success"

        result = commit_loop(
            session, [1, 2, 3, 4, 5, 6], mixed_fn,
            max_consecutive_errors=2, label="test_mixed",
        )

        assert result.errors == 3
        assert result.success == 1


# ---------------------------------------------------------------------------
# 5. NHL Boxscore Ingestion (lines 50-83, 148-155, 261, 287-288)
# ---------------------------------------------------------------------------


class TestSelectGamesForBoxscoresNhlApi:
    """Cover select_games_for_boxscores_nhl_api invalid game_pk (lines 148-155)."""

    def test_invalid_game_pk_logged_and_skipped(self):
        """Cover lines 154-159: ValueError/TypeError when parsing nhl_game_pk."""
        from sports_scraper.services.nhl_boxscore_ingestion import select_games_for_boxscores_nhl_api

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "not_a_number", datetime(2025, 1, 1, 2, 0, tzinfo=timezone.utc))
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nhl_api(
            session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
            only_missing=False, updated_before=None,
        )

        assert result == []


