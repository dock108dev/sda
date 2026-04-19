"""Tests for game state updater: promote games through lifecycle states."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from sports_scraper.services.game_state_updater import (
    _ARCHIVE_AFTER_DAYS,
    _cancel_phantom_finals,
    _has_recent_data,
    _is_phantom_game,
    _promote_final_to_archived,
    _promote_pregame_to_live,
    _promote_scheduled_to_pregame,
    _promote_stale_to_final,
    update_game_states,
)

_MOD = "sports_scraper.services.game_state_updater"
_MOCK_LEAGUE_ID = 10
_PREGAME_WINDOW_HOURS = 6


def _utc_now() -> datetime:
    return datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _make_game(**kwargs) -> MagicMock:
    game = MagicMock()
    game.id = kwargs.get("id", 1)
    game.status = kwargs.get("status", "scheduled")
    game.game_date = kwargs.get("game_date")
    game.end_time = kwargs.get("end_time")
    game.updated_at = kwargs.get("updated_at")
    game.closed_at = kwargs.get("closed_at")
    game.league_id = kwargs.get("league_id", _MOCK_LEAGUE_ID)
    game.social_scrape_2_at = kwargs.get("social_scrape_2_at")
    game.home_score = kwargs.get("home_score")
    game.away_score = kwargs.get("away_score")
    game.last_pbp_at = kwargs.get("last_pbp_at")
    game.last_boxscore_at = kwargs.get("last_boxscore_at")
    game.last_scraped_at = kwargs.get("last_scraped_at")
    return game


# ---------------------------------------------------------------------------
# update_game_states
# ---------------------------------------------------------------------------
class TestUpdateGameStates:
    @patch(f"{_MOD}._promote_final_to_archived", return_value=0)
    @patch(f"{_MOD}._cancel_phantom_finals", return_value=0)
    @patch(f"{_MOD}._promote_stale_to_final", return_value=0)
    @patch(f"{_MOD}._promote_pregame_to_live", return_value=0)
    @patch(f"{_MOD}._promote_scheduled_to_pregame", return_value=0)
    def test_returns_counts_dict(self, mock_sched, mock_pregame, mock_stale, mock_phantom, mock_final):
        session = MagicMock()
        result = update_game_states(session)
        assert result == {
            "scheduled_to_pregame": 0,
            "pregame_to_live": 0,
            "stale_to_final": 0,
            "phantom_canceled": 0,
            "final_to_archived": 0,
        }

    @patch(f"{_MOD}.logger")
    @patch(f"{_MOD}._promote_final_to_archived", return_value=1)
    @patch(f"{_MOD}._cancel_phantom_finals", return_value=0)
    @patch(f"{_MOD}._promote_stale_to_final", return_value=0)
    @patch(f"{_MOD}._promote_pregame_to_live", return_value=0)
    @patch(f"{_MOD}._promote_scheduled_to_pregame", return_value=2)
    def test_logs_info_when_transitions(
        self, mock_sched, mock_pregame, mock_stale, mock_phantom, mock_final, mock_logger
    ):
        session = MagicMock()
        result = update_game_states(session)
        assert result["scheduled_to_pregame"] == 2
        assert result["final_to_archived"] == 1
        mock_logger.info.assert_called_once()

    @patch(f"{_MOD}.logger")
    @patch(f"{_MOD}._promote_final_to_archived", return_value=0)
    @patch(f"{_MOD}._cancel_phantom_finals", return_value=0)
    @patch(f"{_MOD}._promote_stale_to_final", return_value=0)
    @patch(f"{_MOD}._promote_pregame_to_live", return_value=0)
    @patch(f"{_MOD}._promote_scheduled_to_pregame", return_value=0)
    def test_logs_debug_when_no_transitions(
        self, mock_sched, mock_pregame, mock_stale, mock_phantom, mock_final, mock_logger
    ):
        session = MagicMock()
        update_game_states(session)
        mock_logger.debug.assert_called_once_with("game_state_updater_no_transitions")


# ---------------------------------------------------------------------------
# _promote_scheduled_to_pregame
# ---------------------------------------------------------------------------
class TestPromoteScheduledToPregame:
    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_promotes_game_within_window(self, mock_now, mock_config):
        now = _utc_now()
        config = MagicMock()
        config.pregame_window_hours = _PREGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            game_date=now + timedelta(hours=3),  # within 6-hour window
            status="scheduled",
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = 10
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_scheduled_to_pregame(session)
        assert result == 1
        assert game.status == "pregame"
        assert game.updated_at == now

    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_skips_league_not_in_db(self, mock_now, mock_config):
        config = MagicMock()
        config.pregame_window_hours = _PREGAME_WINDOW_HOURS
        mock_config.items.return_value = [("FAKE", config)]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = None

        result = _promote_scheduled_to_pregame(session)
        assert result == 0

    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_multiple_games(self, mock_now, mock_config):
        now = _utc_now()
        config = MagicMock()
        config.pregame_window_hours = _PREGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        games = [
            _make_game(id=1, game_date=now + timedelta(hours=2)),
            _make_game(id=2, game_date=now + timedelta(hours=4)),
        ]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = 10
        session.query.return_value.filter.return_value.all.return_value = games

        result = _promote_scheduled_to_pregame(session)
        assert result == 2

    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_no_eligible_games(self, mock_now, mock_config):
        config = MagicMock()
        config.pregame_window_hours = _PREGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = 10
        session.query.return_value.filter.return_value.all.return_value = []

        result = _promote_scheduled_to_pregame(session)
        assert result == 0


# ---------------------------------------------------------------------------
# _promote_pregame_to_live
# ---------------------------------------------------------------------------
_ESTIMATED_GAME_DURATION_HOURS = 3.0


class TestPromotePregameToLive:
    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_promotes_game_past_game_date(self, mock_now, mock_config):
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="pregame",
            game_date=now - timedelta(hours=1),  # started 1 hour ago
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_pregame_to_live(session)
        assert result == 1
        assert game.status == "live"
        assert game.updated_at == now

    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_skips_game_before_game_date(self, mock_now, mock_config):
        """Games whose game_date is in the future should NOT be promoted."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        mock_config.items.return_value = [("NBA", config)]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = []

        result = _promote_pregame_to_live(session)
        assert result == 0

    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_skips_league_not_in_db(self, mock_now, mock_config):
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        mock_config.items.return_value = [("FAKE", config)]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = None

        result = _promote_pregame_to_live(session)
        assert result == 0

    @patch("sports_scraper.services.game_state_updater.LEAGUE_CONFIG")
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_multiple_games(self, mock_now, mock_config):
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        mock_config.items.return_value = [("NBA", config)]

        games = [
            _make_game(id=1, status="pregame", game_date=now - timedelta(hours=1)),
            _make_game(id=2, status="pregame", game_date=now - timedelta(minutes=30)),
        ]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = games

        result = _promote_pregame_to_live(session)
        assert result == 2
        for g in games:
            assert g.status == "live"


# ---------------------------------------------------------------------------
# _promote_stale_to_final
# ---------------------------------------------------------------------------
_POSTGAME_WINDOW_HOURS = 3.0


class TestPromoteStaleToFinal:
    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_promotes_stale_live_game_to_final(self, mock_now, mock_config):
        """Live game 7 hrs past tip → promoted to final."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="live",
            game_date=now - timedelta(hours=7),  # 7 hrs ago, cutoff is 6
            home_score=105,
            away_score=98,
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_stale_to_final(session)
        assert result == 1
        assert game.status == "final"
        assert game.end_time == game.game_date + timedelta(hours=_ESTIMATED_GAME_DURATION_HOURS)
        assert game.updated_at == now

    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_does_not_promote_recent_live_game(self, mock_now, mock_config):
        """Live game 2 hrs past tip → NOT promoted (still within timeout)."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = []

        result = _promote_stale_to_final(session)
        assert result == 0

    @patch(f"{_MOD}.logger")
    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_logs_warning_for_stale_live(self, mock_now, mock_config, mock_logger):
        """live→final fires logger.warning with reason stale_live_timeout."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="live",
            game_date=now - timedelta(hours=7),
            home_score=88,
            away_score=90,
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        _promote_stale_to_final(session)

        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert call_kwargs[1]["reason"] == "stale_live_timeout"
        assert call_kwargs[1]["from_status"] == "live"
        # Ensure info was NOT called (only warning for live→final)
        mock_logger.info.assert_not_called()

    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_promotes_stale_scheduled_game_with_data(self, mock_now, mock_config):
        """Scheduled game past cutoff with boxscore data → final."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="scheduled",
            game_date=now - timedelta(hours=7),
            home_score=100,
            away_score=95,
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_stale_to_final(session)
        assert result == 1
        assert game.status == "final"

    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_cancels_phantom_scheduled_game(self, mock_now, mock_config):
        """Scheduled game past cutoff with NO game data → canceled."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="scheduled",
            game_date=now - timedelta(hours=7),
            # no scores, no pbp, no boxscore, no scrape — phantom
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_stale_to_final(session)
        assert result == 1
        assert game.status == "cancelled"

    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_mixed_stale_statuses(self, mock_now, mock_config):
        """Real games promoted to final, phantom canceled."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        games = [
            _make_game(id=1, status="scheduled", game_date=now - timedelta(hours=8), home_score=88, away_score=80),
            _make_game(id=2, status="pregame", game_date=now - timedelta(hours=7)),  # phantom
            _make_game(id=3, status="live", game_date=now - timedelta(hours=10), last_pbp_at=now - timedelta(hours=8)),
        ]

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = games

        result = _promote_stale_to_final(session)
        assert result == 3
        assert games[0].status == "final"
        assert games[1].status == "cancelled"
        assert games[2].status == "final"

    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_defers_live_game_with_recent_data(self, mock_now, mock_config):
        """Live game past stale cutoff but with recent PBP → NOT promoted."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="live",
            game_date=now - timedelta(hours=8),
            home_score=88,
            away_score=90,
            last_pbp_at=now - timedelta(minutes=10),  # fresh data
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_stale_to_final(session)
        assert result == 0
        assert game.status == "live"  # still live

    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_promotes_live_game_with_stale_data(self, mock_now, mock_config):
        """Live game past cutoff with old PBP (>30 min) → promoted to final."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="live",
            game_date=now - timedelta(hours=8),
            home_score=88,
            away_score=90,
            last_pbp_at=now - timedelta(hours=2),  # stale data
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_stale_to_final(session)
        assert result == 1
        assert game.status == "final"

    @patch(f"{_MOD}.LEAGUE_CONFIG")
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_does_not_defer_scheduled_game_with_recent_data(self, mock_now, mock_config):
        """Scheduled game with recent boxscore data → still promoted (only live is deferred)."""
        now = _utc_now()
        config = MagicMock()
        config.estimated_game_duration_hours = _ESTIMATED_GAME_DURATION_HOURS
        config.postgame_window_hours = _POSTGAME_WINDOW_HOURS
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game(
            status="scheduled",
            game_date=now - timedelta(hours=8),
            home_score=100,
            away_score=95,
            last_boxscore_at=now - timedelta(minutes=10),  # recent, but game is scheduled not live
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = _MOCK_LEAGUE_ID
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_stale_to_final(session)
        assert result == 1
        assert game.status == "final"  # not deferred — only live games get deferred


# ---------------------------------------------------------------------------
# _has_recent_data
# ---------------------------------------------------------------------------
class TestHasRecentData:
    def test_recent_pbp(self):
        now = _utc_now()
        game = _make_game(last_pbp_at=now - timedelta(minutes=10))
        assert _has_recent_data(game, now) is True

    def test_recent_boxscore(self):
        now = _utc_now()
        game = _make_game(last_boxscore_at=now - timedelta(minutes=5))
        assert _has_recent_data(game, now) is True

    def test_stale_data(self):
        now = _utc_now()
        game = _make_game(
            last_pbp_at=now - timedelta(hours=2),
            last_boxscore_at=now - timedelta(hours=2),
        )
        assert _has_recent_data(game, now) is False

    def test_no_data(self):
        now = _utc_now()
        game = _make_game()  # all None
        assert _has_recent_data(game, now) is False


# ---------------------------------------------------------------------------
# _promote_final_to_archived
# ---------------------------------------------------------------------------
class TestPromoteFinalToArchived:
    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_archives_game_with_artifacts_and_social(self, mock_now):
        now = _utc_now()
        game = _make_game(
            status="final",
            end_time=now - timedelta(days=_ARCHIVE_AFTER_DAYS + 1),
            social_scrape_2_at=now - timedelta(days=_ARCHIVE_AFTER_DAYS),
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _promote_final_to_archived(session)
        assert result == 1
        assert game.status == "archived"
        assert game.closed_at == now
        assert game.updated_at == now

    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_no_eligible_games(self, mock_now):
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []

        result = _promote_final_to_archived(session)
        assert result == 0

    @patch("sports_scraper.services.game_state_updater.now_utc", return_value=_utc_now())
    def test_multiple_games(self, mock_now):
        now = _utc_now()
        games = [
            _make_game(id=1, end_time=now - timedelta(days=10)),
            _make_game(id=2, end_time=now - timedelta(days=14)),
        ]

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = games

        result = _promote_final_to_archived(session)
        assert result == 2
        for g in games:
            assert g.status == "archived"


# ---------------------------------------------------------------------------
# _is_phantom_game
# ---------------------------------------------------------------------------
class TestIsPhantomGame:
    def test_phantom_game_all_none(self):
        """Game with no scores, no PBP, no boxscore, no scrape → phantom."""
        game = _make_game()
        assert _is_phantom_game(game) is True

    def test_not_phantom_with_scores(self):
        game = _make_game(home_score=100, away_score=95)
        assert _is_phantom_game(game) is False

    def test_not_phantom_with_pbp(self):
        game = _make_game(last_pbp_at=_utc_now())
        assert _is_phantom_game(game) is False

    def test_not_phantom_with_boxscore(self):
        game = _make_game(last_boxscore_at=_utc_now())
        assert _is_phantom_game(game) is False

    def test_not_phantom_with_scrape(self):
        game = _make_game(last_scraped_at=_utc_now())
        assert _is_phantom_game(game) is False

    def test_not_phantom_with_only_home_score(self):
        game = _make_game(home_score=0)
        assert _is_phantom_game(game) is False


# ---------------------------------------------------------------------------
# _cancel_phantom_finals
# ---------------------------------------------------------------------------
class TestCancelPhantomFinals:
    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_cancels_phantom_final_game(self, mock_now):
        now = _utc_now()
        game = _make_game(
            status="final",
            game_date=now - timedelta(hours=24),
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [game]

        result = _cancel_phantom_finals(session)
        assert result == 1
        assert game.status == "cancelled"
        assert game.end_time is None
        assert game.updated_at == now

    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_no_phantom_finals(self, mock_now):
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []

        result = _cancel_phantom_finals(session)
        assert result == 0

    @patch(f"{_MOD}.now_utc", return_value=_utc_now())
    def test_multiple_phantom_finals(self, mock_now):
        now = _utc_now()
        games = [
            _make_game(id=1, status="final", game_date=now - timedelta(days=5)),
            _make_game(id=2, status="final", game_date=now - timedelta(days=2)),
        ]

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = games

        result = _cancel_phantom_finals(session)
        assert result == 2
        for g in games:
            assert g.status == "cancelled"
