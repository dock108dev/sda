"""Targeted tests for low-coverage scraper files."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. NFL Advanced Stats Ingestion (lines 84-188)
# ---------------------------------------------------------------------------


class TestNFLAdvancedStatsIngestion:
    """Cover the team/player aggregation + upsert path."""

    def _make_game(self, status="final"):
        game = MagicMock()
        game.id = 42
        game.status = status
        game.league_id = 1
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20
        game.external_ids = {"espn_game_id": "401547890"}
        game.game_date = datetime(2025, 1, 5, 1, 0, tzinfo=timezone.utc)
        game.last_advanced_stats_at = None
        return game

    def _make_session(self, game):
        session = MagicMock()
        league = MagicMock()
        league.code = "NFL"
        home_team = MagicMock()
        home_team.abbreviation = "KC"
        away_team = MagicMock()
        away_team.abbreviation = "BUF"

        from sports_scraper.db import db_models

        def fake_query(*args, **kwargs):
            model = args[0] if args else None
            mock_q = MagicMock()

            def _get(pk):
                if model is db_models.SportsGame:
                    return game
                if model is db_models.SportsLeague:
                    return league
                if model is db_models.SportsTeam:
                    return home_team if pk == 10 else away_team
                return None

            mock_q.get = _get
            return mock_q

        session.query.side_effect = fake_query
        return session

    @patch("sports_scraper.services.nfl_advanced_stats_ingestion.to_et_date", return_value=date(2025, 1, 4))
    @patch("sports_scraper.services.nfl_advanced_stats_ingestion.pg_insert")
    def test_full_ingest_success(self, mock_pg_insert, mock_to_et):
        """Cover lines 84-188: team + player aggregation and upserts."""
        from sports_scraper.services.nfl_advanced_stats_ingestion import (
            ingest_advanced_stats_for_game,
        )

        game = self._make_game()
        session = self._make_session(game)

        mock_stmt = MagicMock()
        mock_stmt.excluded = MagicMock()
        mock_stmt.excluded.__getitem__ = lambda self, key: f"excluded_{key}"
        mock_stmt.on_conflict_do_update.return_value = mock_stmt
        mock_pg_insert.return_value = MagicMock()
        mock_pg_insert.return_value.values.return_value = mock_stmt

        fake_plays = [{"play_id": 1}]
        team_agg = {
            "home": {
                "total_epa": 5.0, "pass_epa": 3.0, "rush_epa": 2.0,
                "epa_per_play": 0.15, "total_wpa": 0.4, "success_rate": 0.5,
                "pass_success_rate": 0.55, "rush_success_rate": 0.45,
                "explosive_play_rate": 0.1, "avg_cpoe": 2.1,
                "avg_air_yards": 8.5, "avg_yac": 5.2, "total_plays": 60,
                "pass_plays": 35, "rush_plays": 25,
            },
            "away": {"total_epa": -2.0, "total_plays": 55},
        }
        player_agg = [
            {
                "player_external_ref": "00-1234", "player_name": "P. Mahomes",
                "player_role": "passer", "is_home": True,
                "total_epa": 4.0, "epa_per_play": 0.3, "pass_epa": 4.0,
                "rush_epa": 0.0, "receiving_epa": None, "cpoe": 3.5,
                "air_epa": 2.0, "yac_epa": 2.0, "air_yards": 300,
                "total_wpa": 0.3, "success_rate": 0.6, "plays": 35,
            },
            {
                "player_external_ref": "00-5678", "player_name": "J. Allen",
                "player_role": "passer", "is_home": False,
                "total_epa": -1.0, "plays": 30,
            },
        ]

        # NFLAdvancedStatsFetcher is imported locally inside the function,
        # so we patch at its source module.
        with patch(
            "sports_scraper.live.nfl_advanced.NFLAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher = MockFetcher.return_value
            fetcher.fetch_game_plays.return_value = fake_plays
            fetcher.aggregate_team_stats.return_value = team_agg
            fetcher.aggregate_player_stats.return_value = player_agg

            result = ingest_advanced_stats_for_game(session, 42)

        assert result["status"] == "success"
        assert result["rows_upserted"] == 2
        assert result["player_rows_upserted"] == 2
        assert session.execute.call_count == 4
        assert session.flush.called

    @patch("sports_scraper.services.nfl_advanced_stats_ingestion.to_et_date", return_value=date(2025, 1, 4))
    @patch("sports_scraper.services.nfl_advanced_stats_ingestion.pg_insert")
    def test_empty_side_skipped(self, mock_pg_insert, mock_to_et):
        """Cover the 'if not agg: continue' branch at line 96."""
        from sports_scraper.services.nfl_advanced_stats_ingestion import (
            ingest_advanced_stats_for_game,
        )

        game = self._make_game()
        session = self._make_session(game)

        mock_stmt = MagicMock()
        mock_stmt.excluded = MagicMock()
        mock_stmt.excluded.__getitem__ = lambda self, key: f"excluded_{key}"
        mock_stmt.on_conflict_do_update.return_value = mock_stmt
        mock_pg_insert.return_value = MagicMock()
        mock_pg_insert.return_value.values.return_value = mock_stmt

        team_agg = {"home": {"total_epa": 1.0, "total_plays": 10}, "away": {}}

        with patch(
            "sports_scraper.live.nfl_advanced.NFLAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher = MockFetcher.return_value
            fetcher.fetch_game_plays.return_value = [{"play_id": 1}]
            fetcher.aggregate_team_stats.return_value = team_agg
            fetcher.aggregate_player_stats.return_value = []

            result = ingest_advanced_stats_for_game(session, 42)

        assert result["rows_upserted"] == 1
        assert result["player_rows_upserted"] == 0


# ---------------------------------------------------------------------------
# 2. NBA PBP (lines 92-170, 250-333, 416)
# ---------------------------------------------------------------------------


class TestProbeHistoricalGameIds:
    """Cover _probe_historical_game_ids (lines 92-170)."""

    def test_probe_returns_cached(self):
        """Cover cached path (lines 106-112)."""
        from sports_scraper.services.pbp_nba import _probe_historical_game_ids

        cached_data = [
            {"home": "BOS", "away": "NYK", "date": "2024-11-01", "gid": "0022400001"},
        ]

        mock_cache = MagicMock()
        mock_cache.get.return_value = cached_data

        with (
            patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2024, 11, 1)),
            patch("sports_scraper.utils.cache.APICache", return_value=mock_cache),
            patch("sports_scraper.config.settings") as mock_settings,
            patch("sports_scraper.utils.date_utils.season_from_date", return_value=2024),
        ):
            mock_settings.scraper_config.html_cache_dir = "/tmp/cache"
            result = _probe_historical_game_ids(date(2024, 11, 1), date(2024, 11, 30))

        assert ("BOS", "NYK", date(2024, 11, 1)) in result
        assert result[("BOS", "NYK", date(2024, 11, 1))] == "0022400001"

    def test_probe_fetches_from_api(self):
        """Cover API fetch path (lines 120-170)."""
        from sports_scraper.services.pbp_nba import _probe_historical_game_ids

        success_resp = MagicMock(status_code=200)
        success_resp.json.return_value = {
            "game": {
                "gameTimeUTC": "2024-11-01T23:30:00Z",
                "homeTeam": {"teamTricode": "BOS"},
                "awayTeam": {"teamTricode": "NYK"},
            },
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

        with (
            patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2024, 11, 1)),
            patch("sports_scraper.utils.cache.APICache", return_value=mock_cache),
            patch("sports_scraper.config.settings") as mock_settings,
            patch("sports_scraper.utils.date_utils.season_from_date", return_value=2024),
            patch("httpx.Client") as MockHttpxClient,
        ):
            mock_settings.scraper_config.html_cache_dir = "/tmp/cache"
            mock_client = MagicMock()
            mock_client.get.side_effect = mock_get
            MockHttpxClient.return_value = mock_client

            result = _probe_historical_game_ids(date(2024, 11, 1), date(2024, 11, 30))

        assert ("BOS", "NYK", date(2024, 11, 1)) in result
        mock_cache.put.assert_called_once()

    def test_probe_exception_consecutive_misses(self):
        """Cover exception branch (lines 151-155)."""
        from sports_scraper.services.pbp_nba import _probe_historical_game_ids

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        with (
            patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2024, 11, 1)),
            patch("sports_scraper.utils.cache.APICache", return_value=mock_cache),
            patch("sports_scraper.config.settings") as mock_settings,
            patch("sports_scraper.utils.date_utils.season_from_date", return_value=2024),
            patch("httpx.Client") as MockHttpxClient,
        ):
            mock_settings.scraper_config.html_cache_dir = "/tmp/cache"
            mock_client = MagicMock()
            mock_client.get.side_effect = Exception("timeout")
            MockHttpxClient.return_value = mock_client

            result = _probe_historical_game_ids(date(2024, 11, 1), date(2024, 11, 30))

        assert result == {}
        mock_cache.put.assert_not_called()


class TestPopulateNbaGameIds:
    """Cover populate_nba_game_ids (lines 250-333)."""

    def test_no_league_returns_zero(self):
        from sports_scraper.services.pbp_nba import populate_nba_game_ids

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        result = populate_nba_game_ids(
            session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
        )
        assert result == 0

    def test_no_missing_games_returns_zero(self):
        from sports_scraper.services.pbp_nba import populate_nba_game_ids

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league
        session.query.return_value.filter.return_value.all.return_value = []

        with patch("sports_scraper.services.pbp_nba._is_current_nba_season", return_value=True):
            result = populate_nba_game_ids(
                session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
            )
        assert result == 0

    def test_current_season_scoreboard_match(self):
        """Cover lines 274-294, 296-333."""
        from sports_scraper.services.pbp_nba import populate_nba_game_ids

        session = MagicMock()
        league = MagicMock(id=1)

        game_row = (100, datetime(2025, 1, 1, 2, 0, tzinfo=timezone.utc), 10, 20)
        team_bos = MagicMock(id=10, abbreviation="BOS", league_id=1)
        team_nyk = MagicMock(id=20, abbreviation="NYK", league_id=1)
        game_obj = MagicMock()
        game_obj.external_ids = {}

        call_count = {"n": 0}

        def fake_query(*args, **kwargs):
            call_count["n"] += 1
            mock_q = MagicMock()
            if call_count["n"] == 1:
                mock_q.filter.return_value.first.return_value = league
            elif call_count["n"] == 2:
                mock_q.filter.return_value.all.return_value = [game_row]
            elif call_count["n"] == 3:
                mock_q.filter.return_value.all.return_value = [team_bos, team_nyk]
            else:
                mock_q.get.return_value = game_obj
            return mock_q

        session.query.side_effect = fake_query

        nba_game = SimpleNamespace(
            home_abbr="BOS", away_abbr="NYK", game_id="0022400100",
        )

        with (
            patch("sports_scraper.services.pbp_nba._is_current_nba_season", return_value=True),
            patch("sports_scraper.live.nba.NBALiveFeedClient") as MockClient,
            patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2025, 1, 1)),
        ):
            MockClient.return_value.fetch_scoreboard.return_value = [nba_game]
            result = populate_nba_game_ids(
                session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 1),
            )

        assert result == 1
        assert game_obj.external_ids["nba_game_id"] == "0022400100"

    def test_scoreboard_exception_handled(self):
        """Cover lines 287-293: exception during scoreboard fetch."""
        from sports_scraper.services.pbp_nba import populate_nba_game_ids

        session = MagicMock()
        league = MagicMock(id=1)

        game_row = (100, datetime(2025, 1, 1, 2, 0, tzinfo=timezone.utc), 10, 20)
        team_bos = MagicMock(id=10, abbreviation="BOS", league_id=1)

        call_count = {"n": 0}

        def fake_query(*args, **kwargs):
            call_count["n"] += 1
            mock_q = MagicMock()
            if call_count["n"] == 1:
                mock_q.filter.return_value.first.return_value = league
            elif call_count["n"] == 2:
                mock_q.filter.return_value.all.return_value = [game_row]
            elif call_count["n"] == 3:
                mock_q.filter.return_value.all.return_value = [team_bos]
            else:
                mock_q.get.return_value = None
            return mock_q

        session.query.side_effect = fake_query

        with (
            patch("sports_scraper.services.pbp_nba._is_current_nba_season", return_value=True),
            patch("sports_scraper.live.nba.NBALiveFeedClient") as MockClient,
            patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2025, 1, 1)),
        ):
            MockClient.return_value.fetch_scoreboard.side_effect = Exception("API down")
            result = populate_nba_game_ids(
                session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 1),
            )

        assert result == 0

    def test_historical_season_uses_probe(self):
        """Cover lines 267-272."""
        from sports_scraper.services.pbp_nba import populate_nba_game_ids

        session = MagicMock()
        league = MagicMock(id=1)
        game_row = (100, datetime(2023, 1, 1, 2, 0, tzinfo=timezone.utc), 10, 20)
        team_bos = MagicMock(id=10, abbreviation="BOS", league_id=1)
        team_nyk = MagicMock(id=20, abbreviation="NYK", league_id=1)
        game_obj = MagicMock()
        game_obj.external_ids = {}

        call_count = {"n": 0}

        def fake_query(*args, **kwargs):
            call_count["n"] += 1
            mock_q = MagicMock()
            if call_count["n"] == 1:
                mock_q.filter.return_value.first.return_value = league
            elif call_count["n"] == 2:
                mock_q.filter.return_value.all.return_value = [game_row]
            elif call_count["n"] == 3:
                mock_q.filter.return_value.all.return_value = [team_bos, team_nyk]
            else:
                mock_q.get.return_value = game_obj
            return mock_q

        session.query.side_effect = fake_query

        probe_result = {("BOS", "NYK", date(2023, 1, 1)): "0022200500"}

        with (
            patch("sports_scraper.services.pbp_nba._is_current_nba_season", return_value=False),
            patch("sports_scraper.services.pbp_nba._probe_historical_game_ids", return_value=probe_result),
            patch("sports_scraper.services.pbp_nba.to_et_date", return_value=date(2023, 1, 1)),
        ):
            result = populate_nba_game_ids(
                session, start_date=date(2023, 1, 1), end_date=date(2023, 1, 1),
            )

        assert result == 1


class TestIngestPbpViaNbaApi:
    """Cover ingest_pbp_via_nba_api line 416."""

    def test_game_not_found_continues(self):
        """Cover line 416: game is None -> continue."""
        from sports_scraper.services.pbp_nba import ingest_pbp_via_nba_api

        session = MagicMock()
        session.query.return_value.get.return_value = None

        with (
            patch("sports_scraper.services.pbp_nba.populate_nba_game_ids"),
            patch(
                "sports_scraper.services.pbp_nba.select_games_for_pbp_nba_api",
                return_value=[(1, "0022400001")],
            ),
        ):
            result = ingest_pbp_via_nba_api(
                session,
                run_id=1,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 2),
                only_missing=True,
                updated_before=None,
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

        with (
            patch("redis.from_url", return_value=mock_r),
            patch("sports_scraper.config.settings") as mock_settings,
        ):
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = acquire_redis_lock("lock:test")

        assert result is None

    def test_force_release_lock_deleted(self):
        """Cover lines 65-74: force_release_lock when key exists."""
        from sports_scraper.utils.redis_lock import force_release_lock

        mock_r = MagicMock()
        mock_r.delete.return_value = 1

        with (
            patch("redis.from_url", return_value=mock_r),
            patch("sports_scraper.config.settings") as mock_settings,
        ):
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = force_release_lock("lock:test")

        assert result is True

    def test_force_release_lock_not_found(self):
        """Cover force_release_lock when key does not exist."""
        from sports_scraper.utils.redis_lock import force_release_lock

        mock_r = MagicMock()
        mock_r.delete.return_value = 0

        with (
            patch("redis.from_url", return_value=mock_r),
            patch("sports_scraper.config.settings") as mock_settings,
        ):
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = force_release_lock("lock:test")

        assert result is False

    def test_force_release_lock_exception(self):
        """Cover lines 75-77: exception in force_release_lock."""
        from sports_scraper.utils.redis_lock import force_release_lock

        with (
            patch("redis.from_url", side_effect=Exception("connection refused")),
            patch("sports_scraper.config.settings") as mock_settings,
        ):
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = force_release_lock("lock:test")

        assert result is False


# ---------------------------------------------------------------------------
# 4. Commit Loop (lines 92-98, 119-132, 141)
# ---------------------------------------------------------------------------


class TestCommitLoop:
    """Cover circuit breaker, error-status, unknown-status, and final-commit."""

    def test_circuit_breaker_stops_iteration(self):
        """Cover lines 92-98."""
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
        """Cover lines 124-128."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(session, [1, 2], lambda s, i: "error", label="test_err")

        assert result.errors == 2
        assert result.success == 0

    def test_unknown_status_treated_as_skip(self):
        """Cover lines 130-132."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(session, [1], lambda s, i: "banana", label="test_unk")

        assert result.skipped == 1
        assert result.success == 0

    def test_skipped_with_reason(self):
        """Cover lines 119-123."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(
            session, [1, 2, 3], lambda s, i: "skipped:no_data", label="test_skip",
        )

        assert result.skipped == 3
        assert result.skipped_reasons == {"no_data": 3}

    def test_final_commit_for_pending(self):
        """Cover line 141."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(
            session, [1, 2, 3], lambda s, i: "success",
            batch_size=5, label="test_final",
        )

        assert result.success == 3
        assert session.commit.call_count == 1

    def test_batch_commit_triggers(self):
        """Cover line 136."""
        from sports_scraper.utils.commit_loop import commit_loop

        session = MagicMock()
        result = commit_loop(
            session, [1, 2, 3, 4], lambda s, i: "success",
            batch_size=2, label="test_batch",
        )

        assert result.success == 4
        assert session.commit.call_count == 2

    def test_circuit_breaker_with_mixed_errors_and_success(self):
        """Consecutive errors reset on success."""
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


class TestPopulateNhlGamesFromSchedule:
    """Cover populate_nhl_games_from_schedule (lines 50-83)."""

    def test_no_schedule_games(self):
        """Cover lines 56-58."""
        from sports_scraper.services.nhl_boxscore_ingestion import (
            populate_nhl_games_from_schedule,
        )

        session = MagicMock()

        with (
            patch("sports_scraper.live.nhl.NHLLiveFeedClient") as MockClient,
            patch("sports_scraper.persistence.games.upsert_game_stub"),
        ):
            MockClient.return_value.fetch_schedule.return_value = []
            result = populate_nhl_games_from_schedule(
                session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
            )

        assert result == 0

    def test_schedule_creates_games(self):
        """Cover lines 63-83."""
        from sports_scraper.services.nhl_boxscore_ingestion import (
            populate_nhl_games_from_schedule,
        )

        session = MagicMock()
        sched_game = SimpleNamespace(
            game_id=2025020001, game_date=date(2025, 1, 1),
            home_team="BOS", away_team="NYR", status="final",
            home_score=3, away_score=1,
        )

        with (
            patch("sports_scraper.live.nhl.NHLLiveFeedClient") as MockClient,
            patch("sports_scraper.persistence.games.upsert_game_stub") as mock_upsert,
        ):
            MockClient.return_value.fetch_schedule.return_value = [sched_game]
            mock_upsert.return_value = (1, True)

            result = populate_nhl_games_from_schedule(
                session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
            )

        assert result == 1

    def test_schedule_stub_exception(self):
        """Cover lines 78-79."""
        from sports_scraper.services.nhl_boxscore_ingestion import (
            populate_nhl_games_from_schedule,
        )

        session = MagicMock()
        sched_game = SimpleNamespace(
            game_id=2025020001, game_date=date(2025, 1, 1),
            home_team="BOS", away_team="NYR", status="final",
            home_score=3, away_score=1,
        )

        with (
            patch("sports_scraper.live.nhl.NHLLiveFeedClient") as MockClient,
            patch("sports_scraper.persistence.games.upsert_game_stub") as mock_upsert,
        ):
            MockClient.return_value.fetch_schedule.return_value = [sched_game]
            mock_upsert.side_effect = Exception("DB error")

            result = populate_nhl_games_from_schedule(
                session, start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
            )

        assert result == 0


class TestSelectGamesForBoxscoresNhlApi:
    """Cover invalid game_pk path (lines 148-155)."""

    def test_invalid_game_pk_logged_and_skipped(self):
        """Cover lines 154-159."""
        from sports_scraper.services.nhl_boxscore_ingestion import (
            select_games_for_boxscores_nhl_api,
        )

        session = MagicMock()
        league = MagicMock(id=1)
        session.query.return_value.filter.return_value.first.return_value = league

        row = (100, "not_a_number", datetime(2025, 1, 1, 2, 0, tzinfo=timezone.utc))
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = select_games_for_boxscores_nhl_api(
            session,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            only_missing=False,
            updated_before=None,
        )

        assert result == []


class TestIngestBoxscoresViaNhlApi:
    """Cover ingest_boxscores_via_nhl_api error paths (lines 261, 287-288)."""

    def test_boxscore_not_enriched(self):
        """Cover line 261: result.enriched is False."""
        from sports_scraper.services.nhl_boxscore_ingestion import (
            ingest_boxscores_via_nhl_api,
        )

        session = MagicMock()

        persist_result = SimpleNamespace(
            game_id=1, enriched=False, has_player_stats=False, player_stats=None,
        )

        boxscore = MagicMock()

        with (
            patch("sports_scraper.services.nhl_boxscore_ingestion.populate_nhl_game_ids"),
            patch(
                "sports_scraper.services.nhl_boxscore_ingestion.select_games_for_boxscores_nhl_api",
                return_value=[(1, 2025020001, date(2025, 1, 1))],
            ),
            patch("sports_scraper.live.nhl.NHLLiveFeedClient") as MockClient,
            patch(
                "sports_scraper.services.nhl_boxscore_ingestion.convert_nhl_boxscore_to_normalized_game",
            ) as mock_convert,
            patch(
                "sports_scraper.services.nhl_boxscore_ingestion.persist_game_payload",
            ) as mock_persist,
        ):
            MockClient.return_value.fetch_boxscore.return_value = boxscore
            mock_convert.return_value = MagicMock()
            mock_persist.return_value = persist_result

            result = ingest_boxscores_via_nhl_api(
                session, run_id=1,
                start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
                only_missing=True, updated_before=None,
            )

        games_processed, games_enriched, games_with_stats, errors = result
        assert games_processed == 1
        assert games_enriched == 0
        assert games_with_stats == 0
        assert errors == 0

    def test_fetch_exception_records_error(self):
        """Cover lines 287-288."""
        from sports_scraper.services.nhl_boxscore_ingestion import (
            ingest_boxscores_via_nhl_api,
        )

        session = MagicMock()

        with (
            patch("sports_scraper.services.nhl_boxscore_ingestion.populate_nhl_game_ids"),
            patch(
                "sports_scraper.services.nhl_boxscore_ingestion.select_games_for_boxscores_nhl_api",
                return_value=[(1, 2025020001, date(2025, 1, 1))],
            ),
            patch("sports_scraper.live.nhl.NHLLiveFeedClient") as MockClient,
            patch(
                "sports_scraper.services.game_selection.record_ingest_error",
            ) as mock_record,
        ):
            MockClient.return_value.fetch_boxscore.side_effect = Exception("API 500")
            result = ingest_boxscores_via_nhl_api(
                session, run_id=1,
                start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
                only_missing=True, updated_before=None,
            )

        _, _, _, errors = result
        assert errors == 1
        mock_record.assert_called_once()

    def test_fetch_exception_record_error_also_fails(self):
        """Cover lines 287-288: record_ingest_error itself raises."""
        from sports_scraper.services.nhl_boxscore_ingestion import (
            ingest_boxscores_via_nhl_api,
        )

        session = MagicMock()

        with (
            patch("sports_scraper.services.nhl_boxscore_ingestion.populate_nhl_game_ids"),
            patch(
                "sports_scraper.services.nhl_boxscore_ingestion.select_games_for_boxscores_nhl_api",
                return_value=[(1, 2025020001, date(2025, 1, 1))],
            ),
            patch("sports_scraper.live.nhl.NHLLiveFeedClient") as MockClient,
            patch(
                "sports_scraper.services.game_selection.record_ingest_error",
                side_effect=Exception("DB down too"),
            ),
        ):
            MockClient.return_value.fetch_boxscore.side_effect = Exception("API 500")
            result = ingest_boxscores_via_nhl_api(
                session, run_id=1,
                start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
                only_missing=True, updated_before=None,
            )

        _, _, _, errors = result
        assert errors == 1
        assert session.rollback.call_count == 2


class TestConvertNhlBoxscoreToNormalizedGame:
    """Cover convert_nhl_boxscore_to_normalized_game."""

    def _make_boxscore(self, status="final", home_score=4, away_score=2):
        from sports_scraper.models.schemas import (
            NormalizedPlayerBoxscore,
            NormalizedTeamBoxscore,
            TeamIdentity,
        )

        home = TeamIdentity(league_code="NHL", name="Boston Bruins", abbreviation="BOS")
        away = TeamIdentity(league_code="NHL", name="New York Rangers", abbreviation="NYR")

        team_box = [
            NormalizedTeamBoxscore(team=home, is_home=True, shots_on_goal=30),
            NormalizedTeamBoxscore(team=away, is_home=False, shots_on_goal=25),
        ]
        player_box = [
            NormalizedPlayerBoxscore(
                player_id="8480840", player_name="D. Pastrnak",
                team=home, goals=2,
            ),
        ]

        return SimpleNamespace(
            game_id=2025020001, home_team=home, away_team=away,
            status=status, home_score=home_score, away_score=away_score,
            team_boxscores=team_box, player_boxscores=player_box,
        )

    def test_basic_conversion(self):
        from sports_scraper.services.nhl_boxscore_ingestion import (
            convert_nhl_boxscore_to_normalized_game,
        )

        boxscore = self._make_boxscore(status="final")
        result = convert_nhl_boxscore_to_normalized_game(boxscore, date(2025, 1, 15))

        assert result.identity.league_code == "NHL"
        assert result.status == "completed"
        assert result.home_score == 4
        assert result.away_score == 2

    def test_non_final_status_preserved(self):
        from sports_scraper.services.nhl_boxscore_ingestion import (
            convert_nhl_boxscore_to_normalized_game,
        )

        boxscore = self._make_boxscore(status="in_progress", home_score=1, away_score=1)
        result = convert_nhl_boxscore_to_normalized_game(boxscore, date(2025, 1, 16))
        assert result.status == "in_progress"
