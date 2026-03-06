"""Tests for jobs/polling_helpers_ncaab.py — CBB API score update path."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.jobs.polling_helpers_ncaab import _update_ncaab_statuses


def _make_game(game_id, status="scheduled", external_ids=None):
    """Create a mock game object."""
    game = MagicMock()
    game.id = game_id
    game.status = status
    game.home_score = None
    game.away_score = None
    game.end_time = None
    game.updated_at = None
    game.external_ids = external_ids or {}
    game.game_date = datetime(2026, 3, 6, 5, 0, tzinfo=UTC)
    game.home_team_id = 100
    game.away_team_id = 200
    return game


def _make_cbb_game(game_id, status="final", home_score=72, away_score=65):
    """Create a mock CBB API game object."""
    cg = MagicMock()
    cg.game_id = game_id
    cg.status = status
    cg.home_score = home_score
    cg.away_score = away_score
    return cg


class TestUpdateNcaabStatusesCbbScores:
    """Test that CBB API path writes scores to game records."""

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    def test_cbb_path_updates_scores(self, mock_resolve):
        """Games going through CBB API path should get scores written."""
        mock_resolve.return_value = "final"

        game = _make_game(
            1001, status="live",
            external_ids={"cbb_game_id": 372174},
        )
        cbb_game = _make_cbb_game(372174, status="final", home_score=72, away_score=65)

        client = MagicMock()
        # NCAA scoreboard returns empty (forces CBB fallback)
        client.fetch_ncaa_scoreboard.return_value = []
        client.fetch_games.return_value = [cbb_game]

        session = MagicMock()

        transitions = _update_ncaab_statuses(session, [game], client)

        assert game.home_score == 72
        assert game.away_score == 65

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    def test_cbb_path_updates_scores_without_status_change(self, mock_resolve):
        """Scores should update even when status doesn't change."""
        mock_resolve.return_value = "final"  # same as current

        game = _make_game(
            1001, status="final",
            external_ids={"cbb_game_id": 372174},
        )
        cbb_game = _make_cbb_game(372174, status="final", home_score=81, away_score=59)

        client = MagicMock()
        client.fetch_ncaa_scoreboard.return_value = []
        client.fetch_games.return_value = [cbb_game]

        session = MagicMock()

        _update_ncaab_statuses(session, [game], client)

        assert game.home_score == 81
        assert game.away_score == 59

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    def test_cbb_path_skips_null_scores(self, mock_resolve):
        """Don't overwrite existing scores with None."""
        mock_resolve.return_value = "live"

        game = _make_game(
            1001, status="live",
            external_ids={"cbb_game_id": 372174},
        )
        game.home_score = 30  # already has partial scores
        cbb_game = _make_cbb_game(372174, status="live", home_score=None, away_score=None)

        client = MagicMock()
        client.fetch_ncaa_scoreboard.return_value = []
        client.fetch_games.return_value = [cbb_game]

        session = MagicMock()

        _update_ncaab_statuses(session, [game], client)

        assert game.home_score == 30  # preserved

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    def test_ncaa_path_still_updates_scores(self, mock_resolve):
        """Existing NCAA API score path should still work."""
        mock_resolve.return_value = "final"

        game = _make_game(
            1001, status="live",
            external_ids={"ncaa_game_id": "abc123"},
        )

        scoreboard_game = MagicMock()
        scoreboard_game.ncaa_game_id = "abc123"
        scoreboard_game.game_state = "final"
        scoreboard_game.home_score = 81
        scoreboard_game.away_score = 100
        scoreboard_game.home_team_short = "Belmont"
        scoreboard_game.away_team_short = "Drake"

        client = MagicMock()
        client.fetch_ncaa_scoreboard.return_value = [scoreboard_game]

        session = MagicMock()

        _update_ncaab_statuses(session, [game], client)

        assert game.home_score == 81
        assert game.away_score == 100
