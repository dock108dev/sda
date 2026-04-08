"""Tests to boost coverage for advanced stats ingestion services and math utils."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# math.py tests
# ---------------------------------------------------------------------------


class TestSafeDiv:
    def test_normal(self):
        from sports_scraper.utils.math import safe_div
        assert safe_div(10, 5) == 2.0

    def test_zero_denom(self):
        from sports_scraper.utils.math import safe_div
        assert safe_div(10, 0) is None

    def test_none_numerator(self):
        from sports_scraper.utils.math import safe_div
        assert safe_div(None, 5) is None

    def test_none_denominator(self):
        from sports_scraper.utils.math import safe_div
        assert safe_div(5, None) is None


class TestSafePct:
    def test_normal(self):
        from sports_scraper.utils.math import safe_pct
        assert safe_pct(1, 4) == 25.0

    def test_zero_denom(self):
        from sports_scraper.utils.math import safe_pct
        assert safe_pct(1, 0) is None


class TestSafeFloat:
    def test_normal(self):
        from sports_scraper.utils.math import safe_float
        assert safe_float("3.14") == 3.14

    def test_none(self):
        from sports_scraper.utils.math import safe_float
        assert safe_float(None) is None

    def test_invalid(self):
        from sports_scraper.utils.math import safe_float
        assert safe_float("abc") is None

    def test_int_input(self):
        from sports_scraper.utils.math import safe_float
        assert safe_float(7) == 7.0


class TestSafeInt:
    def test_normal(self):
        from sports_scraper.utils.math import safe_int
        assert safe_int("42") == 42

    def test_none(self):
        from sports_scraper.utils.math import safe_int
        assert safe_int(None) is None

    def test_invalid(self):
        from sports_scraper.utils.math import safe_int
        assert safe_int("abc") is None

    def test_float_string(self):
        from sports_scraper.utils.math import safe_int
        # int("3.5") raises ValueError
        assert safe_int("3.5") is None


class TestParseMinutes:
    def test_iso_duration(self):
        from sports_scraper.utils.math import parse_minutes
        result = parse_minutes("PT36M12.00S")
        assert result == 36.2

    def test_iso_duration_minutes_only(self):
        from sports_scraper.utils.math import parse_minutes
        result = parse_minutes("PT25M")
        assert result == 25.0

    def test_iso_duration_seconds_only(self):
        from sports_scraper.utils.math import parse_minutes
        result = parse_minutes("PT30S")
        assert result == 0.5

    def test_clock_format(self):
        from sports_scraper.utils.math import parse_minutes
        result = parse_minutes("36:12")
        assert result == 36.2

    def test_raw_float(self):
        from sports_scraper.utils.math import parse_minutes
        assert parse_minutes(18.5) == 18.5

    def test_none(self):
        from sports_scraper.utils.math import parse_minutes
        assert parse_minutes(None) is None

    def test_invalid_clock(self):
        from sports_scraper.utils.math import parse_minutes
        # "ab:cd" should fail int() and fall through
        result = parse_minutes("ab:cd")
        # Falls through to safe_float("ab:cd") which returns None
        assert result is None

    def test_iso_empty_match(self):
        from sports_scraper.utils.math import parse_minutes
        # PT with nothing parseable -> regex matches but both groups are None -> 0.0
        result = parse_minutes("PTXYZ")
        assert result == 0.0


# ---------------------------------------------------------------------------
# Helper: build mock db objects used across NHL/NBA/NCAAB tests
# ---------------------------------------------------------------------------

def _mock_game(
    game_id=1,
    status="final",
    league_id=10,
    home_team_id=100,
    away_team_id=200,
    home_score=3,
    away_score=2,
    season="2024-2025",
    external_ids=None,
):
    game = MagicMock()
    game.id = game_id
    game.status = status
    game.league_id = league_id
    game.home_team_id = home_team_id
    game.away_team_id = away_team_id
    game.home_score = home_score
    game.away_score = away_score
    game.season = season
    game.external_ids = external_ids or {}
    game.last_advanced_stats_at = None
    return game


def _mock_league(code="NHL"):
    league = MagicMock()
    league.code = code
    return league


def _mock_session_for_ingestion(game, league, team_boxscores=None, player_boxscores=None):
    """Build a mock session that handles .get() and .query().filter().all()."""
    session = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        model_name = getattr(model, "__name__", str(model))

        if model_name == "SportsGame" or "SportsGame" in str(model):
            q.get = MagicMock(return_value=game)
            return q
        elif model_name == "SportsLeague" or "SportsLeague" in str(model):
            q.get = MagicMock(return_value=league)
            return q
        elif "TeamBoxscore" in str(model):
            q.filter = MagicMock(return_value=MagicMock(all=MagicMock(return_value=team_boxscores or [])))
            return q
        elif "PlayerBoxscore" in str(model):
            q.filter = MagicMock(return_value=MagicMock(all=MagicMock(return_value=player_boxscores or [])))
            return q
        else:
            q.filter = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            q.get = MagicMock(return_value=None)
            return q

    session.query = MagicMock(side_effect=query_side_effect)
    session.execute = MagicMock()
    session.flush = MagicMock()
    return session


# ---------------------------------------------------------------------------
# NHL advanced stats ingestion tests
# ---------------------------------------------------------------------------


@dataclass
class _TeamAgg:
    team: str = ""
    is_home: bool = False
    xgoals_for: float = 1.5
    xgoals_against: float = 0.0
    shots_on_goal: int = 30
    missed_shots: int = 5
    blocked_shots: int = 3
    goals: int = 3
    high_danger_shots: int = 10
    high_danger_goals: int = 2
    shots_on_goal_against: int = 25
    missed_shots_against: int = 4
    blocked_shots_against: int = 2
    goals_against: int = 2
    xgoals_against_total: float = 1.8
    high_danger_shots_against: int = 8
    high_danger_goals_against: int = 1


@dataclass
class _SkaterAgg:
    player_id: str = "P001"
    player_name: str = "Test Skater"
    team: str = "TOR"
    is_home: bool = True
    xgoals_for: float = 0.5
    xgoals_against: float = 0.3
    shots: int = 5
    goals: int = 1


@dataclass
class _GoalieAgg:
    player_id: str = "G001"
    player_name: str = "Test Goalie"
    team: str = "TOR"
    is_home: bool = True
    xgoals_against: float = 2.1
    goals_against: int = 2
    shots_against: int = 30
    high_danger_shots: int = 10
    high_danger_goals: int = 1
    medium_danger_shots: int = 12
    medium_danger_goals: int = 1
    low_danger_shots: int = 8
    low_danger_goals: int = 0


class TestNHLAdvancedStatsIngestion:
    """Tests for nhl_advanced_stats_ingestion.ingest_advanced_stats_for_game."""

    def _import(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import (
            ingest_advanced_stats_for_game,
        )
        return ingest_advanced_stats_for_game

    def test_game_not_found(self):
        fn = self._import()
        session = MagicMock()
        q = MagicMock()
        q.get = MagicMock(return_value=None)
        session.query = MagicMock(return_value=q)

        result = fn(session, 999)
        assert result["status"] == "not_found"

    def test_skip_not_final(self):
        fn = self._import()
        game = _mock_game(status="live")
        league = _mock_league("NHL")
        session = _mock_session_for_ingestion(game, league)

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_final"

    def test_skip_not_nhl(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NBA")
        session = _mock_session_for_ingestion(game, league)

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_nhl"

    def test_skip_no_game_pk(self):
        fn = self._import()
        game = _mock_game(status="final", external_ids={})
        league = _mock_league("NHL")
        session = _mock_session_for_ingestion(game, league)

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_game_pk"

    def test_no_shots_returned(self):
        fn = self._import()
        game = _mock_game(status="final", external_ids={"nhl_game_pk": "2024020001"})
        league = _mock_league("NHL")
        session = _mock_session_for_ingestion(game, league)

        with patch(
            "sports_scraper.live.nhl_advanced.NHLAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.fetch_game_shots.return_value = []
            result = fn(session, 1)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_shot_data"

    def test_fetch_raises_exception(self):
        fn = self._import()
        game = _mock_game(status="final", external_ids={"nhl_game_pk": "2024020001"})
        league = _mock_league("NHL")
        session = _mock_session_for_ingestion(game, league)

        with patch(
            "sports_scraper.live.nhl_advanced.NHLAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.fetch_game_shots.side_effect = RuntimeError("network")
            try:
                fn(session, 1)
                assert False, "Should have raised"
            except RuntimeError:
                pass

    def test_happy_path(self):
        fn = self._import()
        game = _mock_game(status="final", external_ids={"nhl_game_pk": "2024020001"})
        league = _mock_league("NHL")

        # Build boxscore rows for cross-reference
        box_row = MagicMock()
        box_row.player_external_ref = "P001"
        box_row.stats = {"minutes": 18.5, "assists": 2, "blocked_shots": 1}

        session = _mock_session_for_ingestion(game, league, player_boxscores=[box_row])

        shots = [{"isHomeTeam": "1", "team": "TOR"}]
        home_agg = _TeamAgg(team="TOR", is_home=True)
        away_agg = _TeamAgg(team="MTL", is_home=False, shots_on_goal=20, goals=2)
        skater_agg = _SkaterAgg()
        goalie_agg = _GoalieAgg()

        with patch(
            "sports_scraper.live.nhl_advanced.NHLAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.fetch_game_shots.return_value = shots
            fetcher_inst.aggregate_team_stats.return_value = {"home": home_agg, "away": away_agg}
            fetcher_inst.aggregate_skater_stats.return_value = [skater_agg]
            fetcher_inst.aggregate_goalie_stats.return_value = [goalie_agg]

            result = fn(session, 1)

        assert result["status"] == "success"
        assert result["team_rows_upserted"] == 2
        assert result["skater_rows_upserted"] == 1
        assert result["goalie_rows_upserted"] == 1
        assert session.execute.call_count == 4  # 2 teams + 1 skater + 1 goalie
        assert session.flush.called

    def test_happy_path_no_home_shot(self):
        """All shots have isHomeTeam != '1' -> home_team_abbrev stays empty."""
        fn = self._import()
        game = _mock_game(status="final", external_ids={"nhl_game_pk": "2024020001"})
        league = _mock_league("NHL")
        session = _mock_session_for_ingestion(game, league)

        shots = [{"isHomeTeam": "0", "team": "MTL"}]
        home_agg = _TeamAgg()
        away_agg = _TeamAgg()

        with patch(
            "sports_scraper.live.nhl_advanced.NHLAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.fetch_game_shots.return_value = shots
            fetcher_inst.aggregate_team_stats.return_value = {"home": home_agg, "away": away_agg}
            fetcher_inst.aggregate_skater_stats.return_value = []
            fetcher_inst.aggregate_goalie_stats.return_value = []

            result = fn(session, 1)

        assert result["status"] == "success"


class TestNHLHelpers:
    """Tests for _parse_toi, _per_60, _compute_game_score, _build_boxscore_lookup."""

    def test_parse_toi_numeric(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _parse_toi
        assert _parse_toi({"minutes": 18.5}) == 18.5

    def test_parse_toi_zero_minutes(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _parse_toi
        assert _parse_toi({"minutes": 0}) is None

    def test_parse_toi_string_format(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _parse_toi
        result = _parse_toi({"time_on_ice": "18:30"})
        assert result == 18.5

    def test_parse_toi_bad_string(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _parse_toi
        assert _parse_toi({"time_on_ice": "ab:cd"}) is None

    def test_parse_toi_no_data(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _parse_toi
        assert _parse_toi({}) is None

    def test_parse_toi_invalid_minutes(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _parse_toi
        assert _parse_toi({"minutes": "bad"}) is None

    def test_per_60_normal(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _per_60
        result = _per_60(3, 20.0)
        assert result == 9.0

    def test_per_60_none_stat(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _per_60
        assert _per_60(None, 20.0) is None

    def test_per_60_none_toi(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _per_60
        assert _per_60(3, None) is None

    def test_per_60_zero_toi(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _per_60
        assert _per_60(3, 0) is None

    def test_game_score_normal(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _compute_game_score
        # 1*0.75 + 2*0.7 + 5*0.075 + 1*0.05 = 0.75 + 1.4 + 0.375 + 0.05 = 2.575
        result = _compute_game_score(1, 2, 5, 1)
        assert result == 2.57

    def test_game_score_all_zero(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _compute_game_score
        assert _compute_game_score(0, 0, 0, 0) is None

    def test_game_score_none_values(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _compute_game_score
        # None should be treated as 0
        result = _compute_game_score(None, None, 4, None)
        # 0*0.75 + 0*0.7 + 4*0.075 + 0*0.05 = 0.3
        assert result == 0.3

    def test_build_boxscore_lookup(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _build_boxscore_lookup

        row = MagicMock()
        row.player_external_ref = "P100"
        row.stats = {
            "minutes": 20.0,
            "assists": 3,
            "points": 5,
            "blocked_shots": 2,
            "hits": 4,
            "position": "C",
        }

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = _build_boxscore_lookup(session, 1)
        assert "P100" in result
        assert result["P100"]["toi_minutes"] == 20.0
        assert result["P100"]["assists"] == 3
        assert result["P100"]["blocked_shots"] == 2

    def test_build_boxscore_lookup_empty_stats(self):
        from sports_scraper.services.nhl_advanced_stats_ingestion import _build_boxscore_lookup

        row = MagicMock()
        row.player_external_ref = "P200"
        row.stats = None

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [row]

        result = _build_boxscore_lookup(session, 1)
        assert result["P200"]["toi_minutes"] is None
        assert result["P200"]["assists"] == 0


# ---------------------------------------------------------------------------
# NBA advanced stats ingestion tests
# ---------------------------------------------------------------------------


class TestNBAAdvancedStatsIngestion:
    """Tests for nba_advanced_stats_ingestion.ingest_advanced_stats_for_game."""

    def _import(self):
        from sports_scraper.services.nba_advanced_stats_ingestion import (
            ingest_advanced_stats_for_game,
        )
        return ingest_advanced_stats_for_game

    def test_game_not_found(self):
        fn = self._import()
        session = MagicMock()
        q = MagicMock()
        q.get = MagicMock(return_value=None)
        session.query = MagicMock(return_value=q)

        result = fn(session, 999)
        assert result["status"] == "not_found"

    def test_skip_not_final(self):
        fn = self._import()
        game = _mock_game(status="live")
        league = _mock_league("NBA")
        session = _mock_session_for_ingestion(game, league)

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_final"

    def test_skip_not_nba(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NHL")
        session = _mock_session_for_ingestion(game, league)

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_nba"

    def test_missing_boxscores(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NBA")
        session = _mock_session_for_ingestion(game, league, team_boxscores=[])

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "missing_boxscores"

    def test_cant_identify_teams(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NBA")

        # Two boxscores but neither matches home/away team IDs
        tb1 = MagicMock()
        tb1.team_id = 999
        tb1.stats = {}
        tb2 = MagicMock()
        tb2.team_id = 998
        tb2.stats = {}

        session = _mock_session_for_ingestion(game, league, team_boxscores=[tb1, tb2])

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "cant_identify_teams"

    def test_happy_path(self):
        fn = self._import()
        game = _mock_game(status="final", home_score=110, away_score=105)
        league = _mock_league("NBA")

        home_tb = MagicMock()
        home_tb.team_id = 100
        home_tb.stats = {
            "fg_attempted": 85, "offensive_rebounds": 10,
            "turnovers": 12, "ft_attempted": 20,
        }
        away_tb = MagicMock()
        away_tb.team_id = 200
        away_tb.stats = {
            "fg_attempted": 80, "offensive_rebounds": 8,
            "turnovers": 15, "ft_attempted": 18,
        }

        player_box = MagicMock()
        player_box.player_external_ref = "NBA001"
        player_box.player_name = "Test Player"
        player_box.team_id = 100
        player_box.stats = {"minutes": 35.0, "points": 25}

        session = _mock_session_for_ingestion(
            game, league,
            team_boxscores=[home_tb, away_tb],
            player_boxscores=[player_box],
        )

        team_stats_result = {
            "home": {"off_rating": 112.0, "def_rating": 108.0, "net_rating": 4.0, "pace": 98.0},
            "away": {"off_rating": 108.0, "def_rating": 112.0, "net_rating": -4.0, "pace": 98.0},
        }
        player_stats_result = [
            {
                "player_id": "NBA001", "player_name": "Test Player",
                "is_home": True, "minutes": 35.0, "ts_pct": 60.0,
            }
        ]

        with patch(
            "sports_scraper.live.nba_advanced.NBAAdvancedStatsFetcher"
        ) as MockFetcher, patch(
            "sports_scraper.live.nba_advanced._compute_possessions"
        ) as mock_poss, patch(
            "sports_scraper.live.nba_advanced._extract_stat"
        ) as mock_extract:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.compute_team_advanced_stats.return_value = team_stats_result
            fetcher_inst.compute_player_advanced_stats.return_value = player_stats_result
            mock_poss.return_value = 98.0
            mock_extract.return_value = 80

            result = fn(session, 1)

        assert result["status"] == "success"
        assert result["rows_upserted"] == 2
        assert result["player_rows_upserted"] >= 1

    def test_player_with_zero_id_skipped(self):
        """Players with player_id '0' or empty should be skipped."""
        fn = self._import()
        game = _mock_game(status="final", home_score=100, away_score=95)
        league = _mock_league("NBA")

        home_tb = MagicMock()
        home_tb.team_id = 100
        home_tb.stats = {"fg_attempted": 80}
        away_tb = MagicMock()
        away_tb.team_id = 200
        away_tb.stats = {"fg_attempted": 75}

        session = _mock_session_for_ingestion(
            game, league,
            team_boxscores=[home_tb, away_tb],
            player_boxscores=[],
        )

        team_stats = {
            "home": {"off_rating": 100.0},
            "away": {"off_rating": 95.0},
        }
        # Return a player with id "0"
        player_stats = [
            {"player_id": "0", "player_name": "Ghost", "is_home": True}
        ]

        with patch(
            "sports_scraper.live.nba_advanced.NBAAdvancedStatsFetcher"
        ) as MockFetcher, patch(
            "sports_scraper.live.nba_advanced._compute_possessions"
        ) as mock_poss, patch(
            "sports_scraper.live.nba_advanced._extract_stat"
        ) as mock_extract:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.compute_team_advanced_stats.return_value = team_stats
            fetcher_inst.compute_player_advanced_stats.return_value = player_stats
            mock_poss.return_value = 90.0
            mock_extract.return_value = 70

            result = fn(session, 1)

        assert result["status"] == "success"
        assert result["player_rows_upserted"] == 0


class TestNCAABAdvancedStatsIngestion:
    """Tests for ncaab_advanced_stats_ingestion.ingest_advanced_stats_for_game."""

    def _import(self):
        from sports_scraper.services.ncaab_advanced_stats_ingestion import (
            ingest_advanced_stats_for_game,
        )
        return ingest_advanced_stats_for_game

    def test_game_not_found(self):
        fn = self._import()
        session = MagicMock()
        q = MagicMock()
        q.get = MagicMock(return_value=None)
        session.query = MagicMock(return_value=q)

        result = fn(session, 999)
        assert result["status"] == "not_found"

    def test_skip_not_final(self):
        fn = self._import()
        game = _mock_game(status="live")
        league = _mock_league("NCAAB")
        session = _mock_session_for_ingestion(game, league)

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_final"

    def test_skip_not_ncaab(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NHL")
        session = _mock_session_for_ingestion(game, league)

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_ncaab"

    def test_missing_boxscores(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NCAAB")
        session = _mock_session_for_ingestion(game, league, team_boxscores=[])

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "missing_boxscores"

    def test_team_mismatch(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NCAAB")

        tb1 = MagicMock()
        tb1.team_id = 999
        tb1.stats = {}
        tb2 = MagicMock()
        tb2.team_id = 998
        tb2.stats = {}

        session = _mock_session_for_ingestion(game, league, team_boxscores=[tb1, tb2])

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "team_mismatch"

    def test_empty_boxscores(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NCAAB")

        home_tb = MagicMock()
        home_tb.team_id = 100
        home_tb.stats = {}  # no fg data
        away_tb = MagicMock()
        away_tb.team_id = 200
        away_tb.stats = {}

        session = _mock_session_for_ingestion(game, league, team_boxscores=[home_tb, away_tb])

        result = fn(session, 1)
        assert result["status"] == "skipped"
        assert result["reason"] == "empty_boxscores"

    def test_happy_path(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NCAAB")

        home_tb = MagicMock()
        home_tb.team_id = 100
        home_tb.stats = {"fieldGoalsAttempted": 55}
        away_tb = MagicMock()
        away_tb.team_id = 200
        away_tb.stats = {"fieldGoalsAttempted": 50}

        player_box = MagicMock()
        player_box.player_external_ref = "NCAAB001"
        player_box.player_name = "College Player"
        player_box.team_id = 100
        player_box.stats = {"minutes": 30, "points": 18}

        session = _mock_session_for_ingestion(
            game, league,
            team_boxscores=[home_tb, away_tb],
            player_boxscores=[player_box],
        )

        team_stats = {
            "home": {"possessions": 68.0, "off_rating": 105.0, "pace": 68.0},
            "away": {"possessions": 65.0, "off_rating": 98.0, "pace": 65.0},
        }
        player_results = [
            {
                "player_external_ref": "NCAAB001",
                "player_name": "College Player",
                "minutes": 30, "game_score": 12.5,
            }
        ]

        with patch(
            "sports_scraper.live.ncaab_advanced.NCAABAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.compute_team_advanced_stats.return_value = team_stats
            fetcher_inst.compute_player_advanced_stats.return_value = player_results

            result = fn(session, 1)

        assert result["status"] == "success"
        assert result["rows_upserted"] == 2
        assert result["player_rows_upserted"] >= 1
        assert session.flush.called

    def test_player_without_external_ref_skipped(self):
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NCAAB")

        home_tb = MagicMock()
        home_tb.team_id = 100
        home_tb.stats = {"fieldGoalsAttempted": 50}
        away_tb = MagicMock()
        away_tb.team_id = 200
        away_tb.stats = {"fieldGoalsAttempted": 48}

        session = _mock_session_for_ingestion(
            game, league,
            team_boxscores=[home_tb, away_tb],
            player_boxscores=[],
        )

        team_stats = {
            "home": {"possessions": 60.0},
            "away": {"possessions": 58.0},
        }
        # Player with empty external ref
        player_results = [
            {"player_external_ref": "", "player_name": "No Ref"}
        ]

        with patch(
            "sports_scraper.live.ncaab_advanced.NCAABAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.compute_team_advanced_stats.return_value = team_stats
            fetcher_inst.compute_player_advanced_stats.return_value = player_results

            result = fn(session, 1)

        assert result["status"] == "success"
        assert result["player_rows_upserted"] == 0

    def test_boxscore_with_nested_fg(self):
        """Tests the _has_fg_data branch for nested fieldGoals dict."""
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NCAAB")

        home_tb = MagicMock()
        home_tb.team_id = 100
        home_tb.stats = {"fieldGoals": {"attempted": 55}}  # nested format
        away_tb = MagicMock()
        away_tb.team_id = 200
        away_tb.stats = {}  # empty but home has data, so not both empty

        session = _mock_session_for_ingestion(
            game, league,
            team_boxscores=[home_tb, away_tb],
            player_boxscores=[],
        )

        team_stats = {
            "home": {"possessions": 65.0},
            "away": {"possessions": 62.0},
        }

        with patch(
            "sports_scraper.live.ncaab_advanced.NCAABAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.compute_team_advanced_stats.return_value = team_stats
            fetcher_inst.compute_player_advanced_stats.return_value = []

            result = fn(session, 1)

        assert result["status"] == "success"

    def test_away_players_grouped_correctly(self):
        """Ensure away players are grouped into away_players list."""
        fn = self._import()
        game = _mock_game(status="final")
        league = _mock_league("NCAAB")

        home_tb = MagicMock()
        home_tb.team_id = 100
        home_tb.stats = {"fieldGoalsAttempted": 50}
        away_tb = MagicMock()
        away_tb.team_id = 200
        away_tb.stats = {"fieldGoalsAttempted": 48}

        away_player = MagicMock()
        away_player.player_external_ref = "NCAAB_AWAY"
        away_player.player_name = "Away Player"
        away_player.team_id = 200
        away_player.stats = {"minutes": 25}

        session = _mock_session_for_ingestion(
            game, league,
            team_boxscores=[home_tb, away_tb],
            player_boxscores=[away_player],
        )

        team_stats = {
            "home": {"possessions": 60.0},
            "away": {"possessions": 58.0},
        }
        player_results_home = []
        player_results_away = [
            {"player_external_ref": "NCAAB_AWAY", "player_name": "Away Player", "minutes": 25}
        ]

        with patch(
            "sports_scraper.live.ncaab_advanced.NCAABAdvancedStatsFetcher"
        ) as MockFetcher:
            fetcher_inst = MockFetcher.return_value
            fetcher_inst.compute_team_advanced_stats.return_value = team_stats
            # First call (home), second call (away)
            fetcher_inst.compute_player_advanced_stats.side_effect = [
                player_results_home,
                player_results_away,
            ]

            result = fn(session, 1)

        assert result["status"] == "success"
        assert result["player_rows_upserted"] == 1
