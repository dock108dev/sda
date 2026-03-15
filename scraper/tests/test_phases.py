"""Tests for services/phases/ extracted phase modules."""

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

from sports_scraper.services.phases.advanced_stats_phase import ingest_advanced_stats
from sports_scraper.services.phases.boxscore_phase import ingest_boxscores
from sports_scraper.services.phases.pbp_phase import ingest_pbp
from sports_scraper.services.phases.social_phase import dispatch_social


# ===========================================================================
# advanced_stats_phase
# ===========================================================================

class TestIngestAdvancedStats:
    def _make_config(self, league="MLB", only_missing=False):
        cfg = MagicMock()
        cfg.league_code = league
        cfg.only_missing = only_missing
        return cfg

    def test_skips_non_mlb(self):
        summary = {"advanced_stats": 0}
        mock_start = MagicMock()
        mock_complete = MagicMock()
        ingest_advanced_stats(
            1, self._make_config("NBA"), summary,
            date(2025, 1, 1), date(2025, 1, 2), None,
            get_session=MagicMock(), start_job_run=mock_start, complete_job_run=mock_complete,
        )
        mock_start.assert_not_called()
        assert summary["advanced_stats"] == 0

    @patch("sports_scraper.services.mlb_advanced_stats_ingestion.ingest_advanced_stats_for_game")
    def test_ingests_mlb_games(self, mock_ingest_fn):
        summary = {"advanced_stats": 0}
        mock_session = MagicMock()
        mock_game = MagicMock()
        mock_game.id = 42
        mock_session.query.return_value.join.return_value.filter.return_value.all.return_value = [mock_game]
        mock_get_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        ingest_advanced_stats(
            1, self._make_config("MLB"), summary,
            date(2025, 6, 1), date(2025, 6, 2), None,
            get_session=mock_get_session, start_job_run=MagicMock(return_value=10),
            complete_job_run=MagicMock(),
        )
        mock_ingest_fn.assert_called_once_with(mock_session, 42)
        assert summary["advanced_stats"] == 1

    @patch("sports_scraper.services.mlb_advanced_stats_ingestion.ingest_advanced_stats_for_game")
    def test_handles_per_game_failure(self, mock_ingest_fn):
        mock_ingest_fn.side_effect = Exception("stat error")
        summary = {"advanced_stats": 0}
        mock_session = MagicMock()
        mock_game = MagicMock()
        mock_game.id = 99
        mock_session.query.return_value.join.return_value.filter.return_value.all.return_value = [mock_game]
        mock_get_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        ingest_advanced_stats(
            1, self._make_config("MLB"), summary,
            date(2025, 6, 1), date(2025, 6, 2), None,
            get_session=mock_get_session, start_job_run=MagicMock(return_value=10),
            complete_job_run=MagicMock(),
        )
        assert summary["advanced_stats"] == 0

    def test_handles_complete_failure(self):
        summary = {"advanced_stats": 0}
        mock_get_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(side_effect=Exception("db down"))
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_complete = MagicMock()

        ingest_advanced_stats(
            1, self._make_config("MLB"), summary,
            date(2025, 6, 1), date(2025, 6, 2), None,
            get_session=mock_get_session, start_job_run=MagicMock(return_value=10),
            complete_job_run=mock_complete,
        )
        mock_complete.assert_called_with(10, "error", "db down")

    @patch("sports_scraper.services.mlb_advanced_stats_ingestion.ingest_advanced_stats_for_game")
    def test_only_missing_filter(self, mock_ingest_fn):
        summary = {"advanced_stats": 0}
        mock_session = MagicMock()
        # Chain the filter calls
        mock_query = mock_session.query.return_value.join.return_value.filter.return_value
        mock_query.filter.return_value.all.return_value = []
        mock_get_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        ingest_advanced_stats(
            1, self._make_config("MLB", only_missing=True), summary,
            date(2025, 6, 1), date(2025, 6, 2), None,
            get_session=mock_get_session, start_job_run=MagicMock(return_value=10),
            complete_job_run=MagicMock(),
        )
        # The filter for only_missing should have been called
        mock_query.filter.assert_called()

    @patch("sports_scraper.services.mlb_advanced_stats_ingestion.ingest_advanced_stats_for_game")
    def test_updated_before_filter(self, mock_ingest_fn):
        summary = {"advanced_stats": 0}
        mock_session = MagicMock()
        mock_query = mock_session.query.return_value.join.return_value.filter.return_value
        mock_query.filter.return_value.all.return_value = []
        mock_get_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        updated_before = datetime(2025, 1, 1, tzinfo=UTC)
        ingest_advanced_stats(
            1, self._make_config("MLB"), summary,
            date(2025, 6, 1), date(2025, 6, 2), updated_before,
            get_session=mock_get_session, start_job_run=MagicMock(return_value=10),
            complete_job_run=MagicMock(),
        )
        mock_query.filter.assert_called()


# ===========================================================================
# pbp_phase
# ===========================================================================

class TestIngestPBP:
    def _make_config(self, league="NHL", only_missing=False, batch_live_feed=False):
        cfg = MagicMock()
        cfg.league_code = league
        cfg.only_missing = only_missing
        cfg.batch_live_feed = batch_live_feed
        return cfg

    def _common_deps(self, **overrides):
        mock_session = MagicMock()
        mock_get_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        deps = {
            "get_session": mock_get_session,
            "start_job_run": MagicMock(return_value=10),
            "complete_job_run": MagicMock(),
            "ingest_pbp_via_nhl_api": MagicMock(return_value=(3, 100)),
            "ingest_pbp_via_ncaab_api": MagicMock(return_value=(0, 0)),
            "ingest_pbp_via_nba_api": MagicMock(return_value=(0, 0)),
            "ingest_pbp_via_mlb_api": MagicMock(return_value=(0, 0)),
            "ingest_pbp_via_sportsref": MagicMock(return_value=(2, 50)),
        }
        deps.update(overrides)
        return deps, mock_session

    @patch("sports_scraper.services.phases.pbp_phase.sports_today_et")
    def test_nhl_dispatch(self, mock_today):
        mock_today.return_value = date(2025, 3, 5)
        summary = {"pbp_games": 0}
        deps, _ = self._common_deps()

        ingest_pbp(
            1, self._make_config("NHL"), summary,
            date(2025, 3, 1), date(2025, 3, 4), None,
            MagicMock(), ("NBA", "NHL", "NCAAB", "MLB"), {},
            **deps,
        )
        deps["ingest_pbp_via_nhl_api"].assert_called_once()
        assert summary["pbp_games"] == 3

    @patch("sports_scraper.services.phases.pbp_phase.sports_today_et")
    def test_sportsref_fallback(self, mock_today):
        mock_today.return_value = date(2025, 3, 5)
        summary = {"pbp_games": 0}
        deps, _ = self._common_deps()

        ingest_pbp(
            1, self._make_config("WNBA"), summary,
            date(2025, 3, 1), date(2025, 3, 4), None,
            MagicMock(), ("NBA", "NHL", "NCAAB", "MLB"), {"WNBA": MagicMock()},
            **deps,
        )
        deps["ingest_pbp_via_sportsref"].assert_called_once()

    @patch("sports_scraper.services.phases.pbp_phase.sports_today_et")
    def test_skips_future_dates(self, mock_today):
        mock_today.return_value = date(2025, 3, 1)
        summary = {"pbp_games": 0}
        deps, _ = self._common_deps()

        ingest_pbp(
            1, self._make_config("NHL"), summary,
            date(2025, 3, 5), date(2025, 3, 6), None,
            MagicMock(), ("NBA", "NHL", "NCAAB", "MLB"), {},
            **deps,
        )
        deps["complete_job_run"].assert_called_with(10, "success", "skipped_future_dates")

    def test_batch_live_feed_unsupported_league(self):
        summary = {"pbp_games": 0}
        deps, _ = self._common_deps()

        ingest_pbp(
            1, self._make_config("WNBA", batch_live_feed=True), summary,
            date(2025, 3, 1), date(2025, 3, 4), None,
            MagicMock(), ("NBA", "NHL", "NCAAB", "MLB"), {},
            **deps,
        )
        deps["complete_job_run"].assert_called_with(10, "success", "pbp_not_implemented")

    def test_batch_live_feed_success(self):
        summary = {"pbp_games": 0}
        mock_lfm = MagicMock()
        mock_lfm.ingest_live_data.return_value.pbp_games = 5
        deps, _ = self._common_deps()

        ingest_pbp(
            1, self._make_config("NBA", batch_live_feed=True), summary,
            date(2025, 3, 1), date(2025, 3, 4), None,
            mock_lfm, ("NBA", "NHL", "NCAAB", "MLB"), {},
            **deps,
        )
        assert summary["pbp_games"] == 5

    def test_batch_live_feed_failure(self):
        summary = {"pbp_games": 0}
        mock_lfm = MagicMock()
        mock_get_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(
            side_effect=Exception("feed error")
        )
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        deps, _ = self._common_deps(get_session=mock_get_session)

        ingest_pbp(
            1, self._make_config("NBA", batch_live_feed=True), summary,
            date(2025, 3, 1), date(2025, 3, 4), None,
            mock_lfm, ("NBA", "NHL", "NCAAB", "MLB"), {},
            **deps,
        )
        deps["complete_job_run"].assert_called_with(10, "error", "feed error")

    @patch("sports_scraper.services.phases.pbp_phase.sports_today_et")
    def test_pbp_dispatch_error(self, mock_today):
        mock_today.return_value = date(2025, 3, 5)
        summary = {"pbp_games": 0}
        deps, _ = self._common_deps(
            ingest_pbp_via_nhl_api=MagicMock(side_effect=Exception("api fail")),
        )

        ingest_pbp(
            1, self._make_config("NHL"), summary,
            date(2025, 3, 1), date(2025, 3, 4), None,
            MagicMock(), ("NBA", "NHL", "NCAAB", "MLB"), {},
            **deps,
        )
        deps["complete_job_run"].assert_called_with(10, "error", "api fail")


# ===========================================================================
# social_phase
# ===========================================================================

class TestDispatchSocial:
    def _make_config(self, league="NBA"):
        cfg = MagicMock()
        cfg.league_code = league
        return cfg

    def test_skips_unsupported_league(self):
        summary = {"social_posts": 0}
        dispatch_social(
            1, self._make_config("WNBA"), summary,
            date(2025, 3, 1), date(2025, 3, 2),
            ("NBA", "NHL"),
            get_session=MagicMock(),
            social_task_exists_fn=MagicMock(),
            queue_job_run=MagicMock(),
            enforce_social_queue_limit=MagicMock(),
        )
        assert summary["social_posts"] == 0

    @patch("sports_scraper.services.phases.social_phase.cap_social_date_range")
    def test_skips_empty_range(self, mock_cap):
        mock_cap.return_value = (date(2025, 3, 5), date(2025, 3, 2))
        summary = {"social_posts": 0}
        dispatch_social(
            1, self._make_config("NBA"), summary,
            date(2025, 3, 1), date(2025, 3, 2),
            ("NBA", "NHL"),
            get_session=MagicMock(),
            social_task_exists_fn=MagicMock(),
            queue_job_run=MagicMock(),
            enforce_social_queue_limit=MagicMock(),
        )
        assert summary["social_posts"] == 0

    @patch("sports_scraper.services.phases.social_phase.cap_social_date_range")
    def test_skips_duplicate(self, mock_cap):
        mock_cap.return_value = (date(2025, 3, 1), date(2025, 3, 2))
        summary = {"social_posts": 0}
        dispatch_social(
            1, self._make_config("NBA"), summary,
            date(2025, 3, 1), date(2025, 3, 2),
            ("NBA", "NHL"),
            get_session=MagicMock(),
            social_task_exists_fn=MagicMock(return_value=True),
            queue_job_run=MagicMock(),
            enforce_social_queue_limit=MagicMock(),
        )
        assert summary["social_posts"] == "skipped (already queued)"

    @patch("sports_scraper.jobs.social_tasks.collect_team_social")
    @patch("sports_scraper.jobs.social_tasks.handle_social_task_failure")
    @patch("sports_scraper.services.phases.social_phase.cap_social_date_range")
    def test_dispatches_single_task_per_league(self, mock_cap, mock_fail, mock_collect):
        mock_cap.return_value = (date(2025, 3, 1), date(2025, 3, 3))
        mock_collect.apply_async = MagicMock()
        mock_fail.s = MagicMock()
        summary = {"social_posts": 0}
        mock_queue = MagicMock(return_value=42)

        dispatch_social(
            1, self._make_config("NBA"), summary,
            date(2025, 3, 1), date(2025, 3, 3),
            ("NBA", "NHL"),
            get_session=MagicMock(),
            social_task_exists_fn=MagicMock(return_value=False),
            queue_job_run=mock_queue,
            enforce_social_queue_limit=MagicMock(),
        )
        # Single task per league covering full date range
        assert mock_collect.apply_async.call_count == 1
        assert mock_queue.call_count == 1
        call_args = mock_collect.apply_async.call_args
        assert call_args[1]["args"] == ["NBA", "2025-03-01", "2025-03-03"]
        assert summary["social_posts"] == "dispatched to worker"


# ===========================================================================
# boxscore_phase — targeted tests for uncovered branches
# ===========================================================================

class TestIngestBoxscores:
    def _make_config(self, league="NHL", only_missing=False):
        cfg = MagicMock()
        cfg.league_code = league
        cfg.only_missing = only_missing
        return cfg

    @patch("sports_scraper.services.phases.boxscore_phase.sports_today_et")
    def test_skips_future_dates(self, mock_today):
        mock_today.return_value = date(2025, 3, 1)
        summary = {"games": 0, "games_enriched": 0, "games_with_stats": 0}
        mock_get_session = MagicMock()

        ingest_boxscores(
            1, self._make_config("NHL"), summary,
            date(2025, 3, 5), date(2025, 3, 6), None, None,
            get_session=mock_get_session,
            persist_game_payload=MagicMock(),
            select_games_for_boxscores=MagicMock(),
        )
        assert summary["games"] == 0

    @patch("sports_scraper.services.phases.boxscore_phase.sports_today_et")
    def test_no_source_warning(self, mock_today):
        mock_today.return_value = date(2025, 3, 5)
        summary = {"games": 0, "games_enriched": 0, "games_with_stats": 0}
        mock_get_session = MagicMock()
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.join.return_value.filter.return_value.count.return_value = 0

        ingest_boxscores(
            1, self._make_config("WNBA"), summary,
            date(2025, 3, 1), date(2025, 3, 4), None, None,
            get_session=mock_get_session,
            persist_game_payload=MagicMock(),
            select_games_for_boxscores=MagicMock(),
        )
        assert summary["games"] == 0
