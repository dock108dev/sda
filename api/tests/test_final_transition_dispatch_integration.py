"""Integration test: FINAL status transition → exactly one task enqueued.

Exercises the full hook chain (after_flush + after_commit) in sequence and
asserts that trigger_flow_for_game is dispatched to the sports-scraper queue
exactly once per game_id on a FINAL transition.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import app.db.hooks as hooks
from app.db.sports import GameStatus, SportsGame


# ---------------------------------------------------------------------------
# Helpers shared by all tests in this module
# ---------------------------------------------------------------------------

def _make_game(game_id: int, old_status: str, new_status: str):
    """Build a SportsGame-like mock with the given status history."""
    game = MagicMock()
    game.id = game_id
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


def _run_full_transition(game_id: int, old_status: str, new_status: str):
    """Simulate flush + commit for a single game status change.

    Returns the mock Celery app so callers can assert on send_task calls.
    """
    game, inspected = _make_game(game_id, old_status, new_status)
    session = MagicMock()
    session.dirty = [game]

    mock_celery = MagicMock()
    with (
        patch("app.db.hooks.inspect", return_value=inspected),
        patch("app.celery_client.get_celery_app", return_value=mock_celery),
    ):
        hooks._track_final_transitions(session, None)
        hooks._dispatch_final_game_tasks(session)

    return mock_celery


@pytest.fixture(autouse=True)
def _clear_pending():
    hooks._get_pending().clear()
    yield
    hooks._get_pending().clear()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestFinalTransitionDispatch:
    def test_exactly_one_task_enqueued_on_final_transition(self):
        """Core acceptance criterion: FINAL transition → exactly one task dispatched."""
        mock_celery = _run_full_transition(game_id=101, old_status="live", new_status="final")

        mock_celery.send_task.assert_called_once()
        name, kwargs = mock_celery.send_task.call_args.args[0], mock_celery.send_task.call_args.kwargs
        assert name == "trigger_flow_for_game"
        assert kwargs["args"] == [101]
        assert kwargs["queue"] == "sports-scraper"

    def test_no_task_for_non_final_transition(self):
        """Scheduled→live must NOT dispatch a flow task."""
        mock_celery = _run_full_transition(game_id=202, old_status="scheduled", new_status="live")
        mock_celery.send_task.assert_not_called()

    def test_no_task_on_final_to_final_resave(self):
        """Re-persisting an already-final game must not re-enqueue."""
        mock_celery = _run_full_transition(game_id=303, old_status="final", new_status="final")
        mock_celery.send_task.assert_not_called()

    def test_pending_cleared_after_commit(self):
        """Pending list must be empty after after_commit fires."""
        _run_full_transition(game_id=404, old_status="live", new_status="final")
        assert hooks._get_pending() == []

    def test_rollback_after_flush_cancels_dispatch(self):
        """after_rollback between flush and commit must cancel dispatch."""
        game, inspected = _make_game(505, "live", "final")
        session = MagicMock()
        session.dirty = [game]

        mock_celery = MagicMock()
        with (
            patch("app.db.hooks.inspect", return_value=inspected),
            patch("app.celery_client.get_celery_app", return_value=mock_celery),
        ):
            hooks._track_final_transitions(session, None)
            assert 505 in hooks._get_pending()
            hooks._clear_pending_on_rollback(session)
            hooks._dispatch_final_game_tasks(session)

        mock_celery.send_task.assert_not_called()

    def test_two_games_final_in_one_commit_dispatches_two_tasks(self):
        """Multiple FINAL games in one flush/commit cycle each get a task."""
        game1, insp1 = _make_game(601, "live", "final")
        game2, insp2 = _make_game(602, "live", "final")
        session = MagicMock()
        session.dirty = [game1, game2]

        def _inspect(obj):
            return insp1 if obj is game1 else insp2

        mock_celery = MagicMock()
        with (
            patch("app.db.hooks.inspect", side_effect=_inspect),
            patch("app.celery_client.get_celery_app", return_value=mock_celery),
        ):
            hooks._track_final_transitions(session, None)
            hooks._dispatch_final_game_tasks(session)

        assert mock_celery.send_task.call_count == 2
        dispatched_ids = [c.kwargs["args"][0] for c in mock_celery.send_task.call_args_list]
        assert sorted(dispatched_ids) == [601, 602]

    def test_task_has_expires_set(self):
        """Dispatched task must include an expires value to prevent zombie tasks."""
        mock_celery = _run_full_transition(game_id=707, old_status="live", new_status="final")
        _, kwargs = mock_celery.send_task.call_args.args[0], mock_celery.send_task.call_args.kwargs
        assert "expires" in kwargs, "Task must set expires to avoid zombie tasks in the queue"
        assert kwargs["expires"] > 0
