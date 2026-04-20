"""Unit tests for Game.status ORM hooks.

Tests cover:
- after_flush adds game_id to pending on FINAL transition
- after_flush ignores non-FINAL transitions and non-SportsGame objects
- after_commit dispatches trigger_flow_for_game with correct queue and countdown
- after_commit is a no-op when pending is empty
- after_rollback clears the pending list
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.db.hooks as hooks
from app.db.sports import SportsGame


def _make_game(game_id: int, old_status: str, new_status: str):
    """Return (game_mock, inspected_mock) for a status transition."""
    game = MagicMock()
    game.id = game_id
    # Make isinstance(game, SportsGame) return True
    game.__class__ = SportsGame

    history = MagicMock()
    history.has_changes.return_value = True
    history.deleted = [old_status]
    history.added = [new_status]

    attr_state = MagicMock()
    attr_state.history = history

    inspected = MagicMock()
    inspected.attrs.status = attr_state

    return game, inspected


def _session_with(dirty_objs):
    session = MagicMock()
    session.dirty = dirty_objs
    return session


@pytest.fixture(autouse=True)
def clear_pending():
    """Ensure the per-thread pending list is empty before and after each test."""
    hooks._get_pending().clear()
    yield
    hooks._get_pending().clear()


class TestTrackFinalTransitions:
    def test_adds_game_id_on_live_to_final(self):
        game, inspected = _make_game(42, "live", "final")
        with patch("app.db.hooks.inspect", return_value=inspected):
            hooks._track_final_transitions(_session_with([game]), None)
        assert 42 in hooks._get_pending()

    def test_adds_game_id_on_scheduled_to_final(self):
        game, inspected = _make_game(7, "scheduled", "final")
        with patch("app.db.hooks.inspect", return_value=inspected):
            hooks._track_final_transitions(_session_with([game]), None)
        assert 7 in hooks._get_pending()

    def test_ignores_non_final_transition(self):
        game, inspected = _make_game(42, "scheduled", "live")
        with patch("app.db.hooks.inspect", return_value=inspected):
            hooks._track_final_transitions(_session_with([game]), None)
        assert hooks._get_pending() == []

    def test_ignores_final_to_final(self):
        """Re-saving an already-final game must not re-enqueue."""
        game, inspected = _make_game(42, "final", "final")
        with patch("app.db.hooks.inspect", return_value=inspected):
            hooks._track_final_transitions(_session_with([game]), None)
        assert hooks._get_pending() == []

    def test_ignores_non_game_objects(self):
        other = MagicMock()  # plain mock, not a SportsGame
        hooks._track_final_transitions(_session_with([other]), None)
        assert hooks._get_pending() == []

    def test_ignores_no_history_changes(self):
        game = MagicMock()
        game.__class__ = SportsGame

        history = MagicMock()
        history.has_changes.return_value = False

        attr_state = MagicMock()
        attr_state.history = history
        inspected = MagicMock()
        inspected.attrs.status = attr_state

        with patch("app.db.hooks.inspect", return_value=inspected):
            hooks._track_final_transitions(_session_with([game]), None)
        assert hooks._get_pending() == []

    def test_multiple_games_in_one_flush(self):
        game1, insp1 = _make_game(1, "live", "final")
        game2, insp2 = _make_game(2, "pregame", "live")
        game3, insp3 = _make_game(3, "live", "final")

        def side_effect(obj):
            if obj is game1:
                return insp1
            if obj is game2:
                return insp2
            return insp3

        with patch("app.db.hooks.inspect", side_effect=side_effect):
            hooks._track_final_transitions(_session_with([game1, game2, game3]), None)

        assert hooks._get_pending() == [1, 3]


class TestDispatchFinalGameTasks:
    def test_dispatches_with_correct_args(self):
        hooks._get_pending().append(99)
        mock_celery = MagicMock()

        with patch("app.celery_client.get_celery_app", return_value=mock_celery):
            hooks._dispatch_final_game_tasks(MagicMock())

        mock_celery.send_task.assert_called_once_with(
            "trigger_flow_for_game",
            args=[99],
            queue="sports-scraper",
            routing_key="sports-scraper",
            countdown=300,
            expires=3600,
        )

    def test_clears_pending_after_dispatch(self):
        hooks._get_pending().extend([1, 2])
        mock_celery = MagicMock()

        with patch("app.celery_client.get_celery_app", return_value=mock_celery):
            hooks._dispatch_final_game_tasks(MagicMock())

        assert hooks._get_pending() == []

    def test_dispatches_multiple_games(self):
        hooks._get_pending().extend([10, 20, 30])
        mock_celery = MagicMock()

        with patch("app.celery_client.get_celery_app", return_value=mock_celery):
            hooks._dispatch_final_game_tasks(MagicMock())

        assert mock_celery.send_task.call_count == 3
        calls_args = [c.args[0] for c in mock_celery.send_task.call_args_list]
        assert calls_args == ["trigger_flow_for_game"] * 3
        dispatched_ids = [c.kwargs["args"][0] for c in mock_celery.send_task.call_args_list]
        assert dispatched_ids == [10, 20, 30]

    def test_no_dispatch_when_empty(self):
        mock_celery = MagicMock()

        with patch("app.celery_client.get_celery_app", return_value=mock_celery):
            hooks._dispatch_final_game_tasks(MagicMock())

        mock_celery.send_task.assert_not_called()

    def test_countdown_is_five_minutes(self):
        hooks._get_pending().append(55)
        mock_celery = MagicMock()

        with patch("app.celery_client.get_celery_app", return_value=mock_celery):
            hooks._dispatch_final_game_tasks(MagicMock())

        _, kwargs = mock_celery.send_task.call_args
        assert kwargs["countdown"] == 300

    def test_expires_is_set(self):
        """Task must have an explicit expires to prevent zombie tasks in the queue."""
        hooks._get_pending().append(55)
        mock_celery = MagicMock()

        with patch("app.celery_client.get_celery_app", return_value=mock_celery):
            hooks._dispatch_final_game_tasks(MagicMock())

        _, kwargs = mock_celery.send_task.call_args
        assert "expires" in kwargs, "send_task must include expires"
        assert kwargs["expires"] > 0


class TestClearPendingOnRollback:
    def test_clears_populated_list(self):
        hooks._get_pending().extend([5, 10, 15])
        hooks._clear_pending_on_rollback(MagicMock())
        assert hooks._get_pending() == []

    def test_no_error_on_empty_list(self):
        hooks._clear_pending_on_rollback(MagicMock())
        assert hooks._get_pending() == []
