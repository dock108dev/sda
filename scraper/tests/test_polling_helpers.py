"""Tests for jobs/polling_helpers.py — _should_fetch_pbp and final-transition PBP fetch."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.jobs.polling_helpers import (
    _is_transient_db_error,
    _poll_boxscore_with_db_recovery,
    _should_fetch_pbp,
)
from sports_scraper.services.game_processors import GameProcessResult


def _make_game(status="live"):
    game = MagicMock()
    game.status = status
    return game


class TestShouldFetchPbp:
    """Tests for _should_fetch_pbp helper."""

    def test_live_game_returns_true(self):
        game = _make_game(status="live")
        assert _should_fetch_pbp(game, None) is True

    def test_pregame_returns_true(self):
        game = _make_game(status="pregame")
        assert _should_fetch_pbp(game, None) is True

    def test_final_without_transition_returns_false(self):
        game = _make_game(status="final")
        assert _should_fetch_pbp(game, None) is False

    def test_final_with_unrelated_transition_returns_false(self):
        game = _make_game(status="final")
        status_result = GameProcessResult(
            transition={"game_id": 1, "from": "pregame", "to": "live"}
        )
        assert _should_fetch_pbp(game, status_result) is False

    def test_final_with_transition_to_final_returns_true(self):
        """The critical fix: when game just transitioned to final, do one last PBP fetch."""
        game = _make_game(status="final")
        status_result = GameProcessResult(
            transition={"game_id": 1, "from": "live", "to": "final"}
        )
        assert _should_fetch_pbp(game, status_result) is True

    def test_final_no_transition_field_returns_false(self):
        game = _make_game(status="final")
        status_result = GameProcessResult(transition=None)
        assert _should_fetch_pbp(game, status_result) is False

    def test_status_result_none_live_game(self):
        """If status check failed (exception), still fetch PBP for live games."""
        game = _make_game(status="live")
        assert _should_fetch_pbp(game, None) is True

    def test_status_result_none_final_game(self):
        """If status check failed and game is already final, skip PBP."""
        game = _make_game(status="final")
        assert _should_fetch_pbp(game, None) is False


def _db_error(sqlstate: str, message: str = "db error") -> Exception:
    exc = Exception(message)
    exc.orig = SimpleNamespace(sqlstate=sqlstate)
    return exc


class TestBoxscoreDbRecovery:
    def test_deadlock_rolls_back_and_retries_once(self):
        session = MagicMock()
        game = SimpleNamespace(id=190063)
        calls = {"count": 0}

        def processor(_session, _game):
            calls["count"] += 1
            if calls["count"] == 1:
                raise _db_error("40P01", "deadlock detected")
            return GameProcessResult(api_calls=1, boxscore_updated=True)

        result = _poll_boxscore_with_db_recovery(
            session,
            game,
            processor,
            "poll_mlb_boxscore_error",
        )

        assert result == {"api_calls": 1, "boxscore_updated": True}
        assert calls["count"] == 2
        session.rollback.assert_called_once()

    def test_non_transient_db_error_rolls_back_without_retry(self):
        session = MagicMock()
        game = SimpleNamespace(id=190064)

        def processor(_session, _game):
            raise _db_error("23505", "unique violation")

        result = _poll_boxscore_with_db_recovery(
            session,
            game,
            processor,
            "poll_mlb_boxscore_error",
        )

        assert result == {"api_calls": 0, "boxscore_updated": False}
        session.rollback.assert_called_once()

    def test_transient_db_error_detection_by_sqlstate(self):
        assert _is_transient_db_error(_db_error("40P01", "deadlock detected")) is True
        assert _is_transient_db_error(_db_error("23505", "unique violation")) is False
