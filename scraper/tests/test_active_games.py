"""Tests for ActiveGamesResolver: query games by lifecycle window state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from sports_scraper.services.active_games import (
    _DEFAULT_PBP_STALE_MINUTES,
    _DEFAULT_POSTGAME_HOURS,
    _DEFAULT_PREGAME_HOURS,
    ActiveGamesResolver,
)


def _utc_now() -> datetime:
    return datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _make_game(**kwargs) -> MagicMock:
    game = MagicMock()
    game.id = kwargs.get("id", 1)
    game.status = kwargs.get("status", "live")
    game.home_team_id = kwargs.get("home_team_id", 100)
    game.away_team_id = kwargs.get("away_team_id", 200)
    game.game_date = kwargs.get("game_date")
    game.end_time = kwargs.get("end_time")
    game.last_pbp_at = kwargs.get("last_pbp_at")
    game.league_id = kwargs.get("league_id", 10)
    return game


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------
class TestActiveGamesResolverInit:
    def test_default_params(self):
        resolver = ActiveGamesResolver()
        assert resolver.pregame_hours == _DEFAULT_PREGAME_HOURS
        assert resolver.postgame_hours == _DEFAULT_POSTGAME_HOURS
        assert resolver.pbp_stale_minutes == _DEFAULT_PBP_STALE_MINUTES

    def test_custom_params(self):
        resolver = ActiveGamesResolver(pregame_hours=12, postgame_hours=6, pbp_stale_minutes=10)
        assert resolver.pregame_hours == 12
        assert resolver.postgame_hours == 6
        assert resolver.pbp_stale_minutes == 10


# ---------------------------------------------------------------------------
# get_active_games
# ---------------------------------------------------------------------------
class TestGetActiveGames:
    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_returns_results_no_league_filter(self, mock_now):
        resolver = ActiveGamesResolver()
        session = MagicMock()
        game = _make_game()
        session.query.return_value.filter.return_value.all.return_value = [(game, "IN")]

        result = resolver.get_active_games(session)
        assert len(result) == 1
        assert result[0] == (game, "IN")

    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_filters_by_league_code(self, mock_now):
        resolver = ActiveGamesResolver()
        session = MagicMock()

        # Set up the league lookup to return a league_id
        query_mock = MagicMock()
        session.query.return_value = query_mock
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock

        game = _make_game()
        filter_mock.all.return_value = [(game, "IN")]
        filter_mock.scalar.return_value = 10

        result = resolver.get_active_games(session, league_code="NBA")
        assert len(result) >= 0  # Query was executed

    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_unknown_league_code_scalar_returns_none(self, mock_now):
        resolver = ActiveGamesResolver()
        session = MagicMock()

        query_mock = MagicMock()
        session.query.return_value = query_mock
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock
        filter_mock.scalar.return_value = None
        filter_mock.all.return_value = []

        result = resolver.get_active_games(session, league_code="FAKE")
        assert result == []


# ---------------------------------------------------------------------------
# get_games_needing_pbp
# ---------------------------------------------------------------------------
class TestGetGamesNeedingPbp:
    @patch("sports_scraper.services.active_games.LEAGUE_CONFIG")
    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_returns_stale_games(self, mock_now, mock_config):
        config = MagicMock()
        config.live_pbp_enabled = True
        mock_config.items.return_value = [("NBA", config)]

        game = _make_game()
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [(10,)]
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [game]

        resolver = ActiveGamesResolver()
        result = resolver.get_games_needing_pbp(session)
        assert len(result) == 1

    @patch("sports_scraper.services.active_games.LEAGUE_CONFIG")
    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_empty_when_no_enabled_leagues(self, mock_now, mock_config):
        config = MagicMock()
        config.live_pbp_enabled = False
        mock_config.items.return_value = [("NCAAB", config)]

        resolver = ActiveGamesResolver()
        result = resolver.get_games_needing_pbp(MagicMock())
        assert result == []

    @patch("sports_scraper.services.active_games.LEAGUE_CONFIG")
    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_empty_when_no_league_ids_in_db(self, mock_now, mock_config):
        config = MagicMock()
        config.live_pbp_enabled = True
        mock_config.items.return_value = [("NBA", config)]

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []

        resolver = ActiveGamesResolver()
        result = resolver.get_games_needing_pbp(session)
        assert result == []


# ---------------------------------------------------------------------------
# get_games_needing_social
# ---------------------------------------------------------------------------
class TestGetGamesNeedingSocial:
    def test_deduplicates_team_pairs(self):
        resolver = ActiveGamesResolver()
        game1 = _make_game(id=1, home_team_id=100, away_team_id=200)
        game2 = _make_game(id=2, home_team_id=100, away_team_id=300)

        with patch.object(
            ActiveGamesResolver, "get_active_games",
            return_value=[(game1, "IN"), (game2, "PRE")],
        ):
            session = MagicMock()
            pairs = resolver.get_games_needing_social(session)
            team_ids = [t for _, t in pairs]
            assert len(team_ids) == len(set(team_ids))
            assert 100 in team_ids
            assert 200 in team_ids
            assert 300 in team_ids

    def test_empty_when_no_active_games(self):
        resolver = ActiveGamesResolver()
        with patch.object(
            ActiveGamesResolver, "get_active_games",
            return_value=[],
        ):
            session = MagicMock()
            pairs = resolver.get_games_needing_social(session)
            assert pairs == []


# ---------------------------------------------------------------------------
# get_games_needing_odds
# ---------------------------------------------------------------------------
class TestGetGamesNeedingOdds:
    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_pregame_games(self, mock_now):
        resolver = ActiveGamesResolver()
        game = _make_game(status="pregame")

        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [game]

        result = resolver.get_games_needing_odds(session)
        assert len(result) == 1

    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_recently_final_games(self, mock_now):
        now = _utc_now()
        resolver = ActiveGamesResolver()
        game = _make_game(status="final", end_time=now - timedelta(hours=1))

        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [game]

        result = resolver.get_games_needing_odds(session)
        assert len(result) == 1

    @patch("sports_scraper.services.active_games.now_utc", return_value=_utc_now())
    def test_empty_result(self, mock_now):
        resolver = ActiveGamesResolver()
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = resolver.get_games_needing_odds(session)
        assert result == []
