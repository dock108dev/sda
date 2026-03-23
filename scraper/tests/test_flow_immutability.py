"""Tests for game flow immutability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestFlowImmutability:
    """Tests for trigger_flow_for_game immutability guard."""

    @patch("sports_scraper.services.job_runs.complete_job_run")
    @patch("sports_scraper.services.job_runs.start_job_run", return_value=1)
    @patch("sports_scraper.utils.redis_lock.acquire_redis_lock", return_value="fake-token")
    @patch("sports_scraper.utils.redis_lock.release_redis_lock")
    @patch("sports_scraper.jobs.flow_trigger_tasks.get_session")
    def test_flow_not_regenerated_when_exists(
        self, mock_get_session, mock_release, mock_acquire, mock_start, mock_complete
    ):
        """Second call to trigger_flow_for_game returns 'immutable'."""
        from sports_scraper.jobs.flow_trigger_tasks import trigger_flow_for_game

        game = MagicMock()
        game.id = 1
        game.status = "final"
        game.league_id = 1

        session = MagicMock()
        session.query.return_value.get.return_value = game

        # has_pbp = True, has_artifacts = True
        session.query.return_value.scalar.side_effect = [True, True]
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = trigger_flow_for_game(1)

        assert result["status"] == "skipped"
        assert result["reason"] == "immutable"

    @patch("sports_scraper.services.job_runs.complete_job_run")
    @patch("sports_scraper.services.job_runs.start_job_run", return_value=1)
    @patch("sports_scraper.utils.redis_lock.acquire_redis_lock", return_value="fake-token")
    @patch("sports_scraper.utils.redis_lock.release_redis_lock")
    @patch("sports_scraper.jobs.flow_trigger_tasks._call_pipeline_api")
    @patch("sports_scraper.jobs.flow_trigger_tasks.get_session")
    def test_flow_generated_when_no_existing_artifacts(
        self, mock_get_session, mock_call_api, mock_release, mock_acquire, mock_start, mock_complete
    ):
        """First call generates the flow."""
        from sports_scraper.jobs.flow_trigger_tasks import trigger_flow_for_game

        game = MagicMock()
        game.id = 1
        game.status = "final"
        game.league_id = 1

        league = MagicMock()
        league.code = "NBA"

        session = MagicMock()
        session.query.return_value.get.side_effect = [game, league]

        # has_pbp = True, has_artifacts = False
        session.query.return_value.scalar.side_effect = [True, False]
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_call_api.return_value = {
            "game_id": 1,
            "league": "NBA",
            "status": "success",
        }

        result = trigger_flow_for_game(1)

        assert result["status"] == "success"
        mock_call_api.assert_called_once_with(1, "NBA")

    @patch("sports_scraper.jobs.flow_trigger_tasks.get_session")
    def test_flow_skips_non_final_game(self, mock_get_session):
        """Games not in FINAL status are skipped."""
        from sports_scraper.jobs.flow_trigger_tasks import trigger_flow_for_game

        game = MagicMock()
        game.id = 1
        game.status = "live"

        session = MagicMock()
        session.query.return_value.get.return_value = game
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = trigger_flow_for_game(1)

        assert result["status"] == "skipped"
        assert result["reason"] == "not_final"

    @patch("sports_scraper.jobs.flow_trigger_tasks.get_session")
    def test_flow_game_not_found(self, mock_get_session):
        """Missing game returns not_found."""
        from sports_scraper.jobs.flow_trigger_tasks import trigger_flow_for_game

        session = MagicMock()
        session.query.return_value.get.return_value = None
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = trigger_flow_for_game(999)

        assert result["status"] == "not_found"
