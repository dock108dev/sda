"""Extended tests for profile_service.py — pitcher statcast profiles and team roster."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analytics.services.profile_service import (
    ProfileResult,
    _fetch_mlb_api_roster,
    _pitcher_profile_from_boxscore,
    _pitcher_profile_from_statcast,
    _season_weights,
    _weighted_mean,
    get_pitcher_rolling_profile,
    get_player_rolling_profile,
    get_team_info,
    get_team_rolling_profile,
    get_team_roster,
    profile_to_pa_probabilities,
)


# ---------------------------------------------------------------------------
# _pitcher_profile_from_statcast
# ---------------------------------------------------------------------------


class TestPitcherProfileFromStatcast:
    @pytest.mark.asyncio
    async def test_returns_none_with_insufficient_rows(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = [(MagicMock(), datetime(2026, 3, 1, tzinfo=UTC))]
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_statcast("p1", 1, db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_profile_from_pitcher_game_stats(self):
        db = AsyncMock()

        def _make_pitcher_stat():
            return SimpleNamespace(
                batters_faced=20,
                strikeouts=5,
                walks=2,
                home_runs_allowed=1,
                k_rate=0.25,
                bb_rate=0.10,
                hr_rate=0.05,
                whiff_rate=0.24,
                z_contact_pct=0.82,
                chase_rate=0.31,
                avg_exit_velo_against=88.5,
                hard_hit_pct_against=0.35,
                barrel_pct_against=0.07,
            )

        game_date = datetime(2026, 3, 1, tzinfo=UTC)
        rows = [(_make_pitcher_stat(), game_date) for _ in range(5)]

        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_statcast("p1", 1, db=db)
        assert result is not None
        assert "k_rate" in result
        assert "bb_rate" in result
        assert "whiff_rate" in result
        assert "contact_suppression" in result
        assert "power_suppression" in result
        assert "strikeout_rate" in result
        assert "walk_rate" in result

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")

        result = await _pitcher_profile_from_statcast("p1", 1, db=db)
        assert result is None


# ---------------------------------------------------------------------------
# _pitcher_profile_from_boxscore
# ---------------------------------------------------------------------------


class TestPitcherProfileFromBoxscore:
    @pytest.mark.asyncio
    async def test_returns_none_with_insufficient_data(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_boxscore("p1", 1, db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_derives_rates_from_boxscore_stats(self):
        db = AsyncMock()

        stats = {
            "strikeOuts": 8,
            "baseOnBalls": 2,
            "homeRuns": 1,
            "hits": 5,
        }
        game_date = datetime(2026, 3, 1, tzinfo=UTC)
        rows = [(MagicMock(stats=stats), game_date) for _ in range(5)]

        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_boxscore("p1", 1, db=db)
        assert result is not None
        assert abs(result["strikeout_rate"] - 8 / 16) < 0.01
        assert abs(result["walk_rate"] - 2 / 16) < 0.01

    @pytest.mark.asyncio
    async def test_skips_zero_bf_games(self):
        db = AsyncMock()

        zero_stats = {"strikeOuts": 0, "baseOnBalls": 0, "homeRuns": 0, "hits": 0}
        good_stats = {"strikeOuts": 5, "baseOnBalls": 2, "homeRuns": 1, "hits": 4}
        game_date = datetime(2026, 3, 1, tzinfo=UTC)

        rows = [
            (MagicMock(stats=good_stats), game_date),
            (MagicMock(stats=zero_stats), game_date),
            (MagicMock(stats=good_stats), game_date),
            (MagicMock(stats=good_stats), game_date),
        ]

        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_boxscore("p1", 1, db=db)
        assert result is not None  # 3 valid games >= min of 3


# ---------------------------------------------------------------------------
# get_pitcher_rolling_profile (integration of both paths)
# ---------------------------------------------------------------------------


class TestGetPitcherRollingProfileIntegration:
    @pytest.mark.asyncio
    @patch("app.analytics.services.profile_service._pitcher_profile_from_statcast")
    @patch("app.analytics.services.profile_service._pitcher_profile_from_boxscore")
    async def test_prefers_statcast(self, mock_boxscore, mock_statcast):
        mock_statcast.return_value = {"k_rate": 0.28, "whiff_rate": 0.25}
        mock_boxscore.return_value = {"strikeout_rate": 0.20}

        db = AsyncMock()
        result = await get_pitcher_rolling_profile("p1", 1, db=db)
        assert result == {"k_rate": 0.28, "whiff_rate": 0.25}
        mock_boxscore.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.analytics.services.profile_service._pitcher_profile_from_statcast")
    @patch("app.analytics.services.profile_service._pitcher_profile_from_boxscore")
    async def test_falls_back_to_boxscore(self, mock_boxscore, mock_statcast):
        mock_statcast.return_value = None
        mock_boxscore.return_value = {"strikeout_rate": 0.22}

        db = AsyncMock()
        result = await get_pitcher_rolling_profile("p1", 1, db=db)
        assert result == {"strikeout_rate": 0.22}
        mock_boxscore.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.analytics.services.profile_service._pitcher_profile_from_statcast")
    @patch("app.analytics.services.profile_service._pitcher_profile_from_boxscore")
    async def test_returns_none_when_both_fail(self, mock_boxscore, mock_statcast):
        mock_statcast.return_value = None
        mock_boxscore.return_value = None

        db = AsyncMock()
        result = await get_pitcher_rolling_profile("p1", 1, db=db)
        assert result is None


# ---------------------------------------------------------------------------
# get_team_roster
# ---------------------------------------------------------------------------


class TestGetTeamRoster:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_team(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        result = await get_team_roster("XXX", db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_batters_and_pitchers(self):
        db = AsyncMock()

        team = MagicMock()
        team.id = 1
        team.abbreviation = "NYY"
        team.external_ref = "147"

        batter_row = SimpleNamespace(
            player_external_ref="100", player_name="Batter A", games_played=20,
        )
        pitcher_row = SimpleNamespace(
            player_external_ref="200", player_name="Pitcher B", games=15, avg_ip=5.5,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Team lookup
                result.scalar_one_or_none.return_value = team
            elif call_count == 2:
                # Batter query
                result.all.return_value = [batter_row]
            elif call_count == 3:
                # Pitcher query
                result.all.return_value = [pitcher_row]
            else:
                result.all.return_value = []
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute

        result = await get_team_roster("NYY", db=db)
        assert result is not None
        assert len(result["batters"]) == 1
        assert result["batters"][0]["name"] == "Batter A"
        assert len(result["pitchers"]) == 1
        assert result["pitchers"][0]["name"] == "Pitcher B"

    @pytest.mark.asyncio
    async def test_widens_lookback_when_no_recent_data(self):
        """Falls through to wider lookback windows when recent data is empty."""
        db = AsyncMock()

        team = MagicMock()
        team.id = 1
        team.abbreviation = "NYY"
        team.external_ref = "147"

        batter_row = SimpleNamespace(
            player_external_ref="100", player_name="B", games_played=10,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = team
            elif call_count <= 5:
                # First lookback (30d): empty batters and pitchers
                result.all.return_value = []
            elif call_count == 6:
                # Second lookback (90d): has batters
                result.all.return_value = [batter_row]
            elif call_count == 7:
                # Second lookback (90d): has pitchers
                result.all.return_value = []
            else:
                result.all.return_value = []
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute

        result = await get_team_roster("NYY", db=db)
        assert result is not None

    @pytest.mark.asyncio
    @patch("app.analytics.services.profile_service._fetch_mlb_api_roster")
    async def test_falls_back_to_api(self, mock_api):
        """When DB has no data, falls back to MLB Stats API."""
        mock_api.return_value = {
            "batters": [{"external_ref": "100", "name": "API Batter", "games_played": 0}],
            "pitchers": [],
        }

        db = AsyncMock()
        team = MagicMock()
        team.id = 1
        team.abbreviation = "NYY"
        team.external_ref = "147"

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = team
            else:
                result.all.return_value = []
            return result

        db.execute = mock_execute

        result = await get_team_roster("NYY", db=db)
        assert result is not None
        assert result["batters"][0]["name"] == "API Batter"


class TestFetchMLBApiRoster:
    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_parses_roster_response(self, mock_client_cls):
        from app.analytics.services.profile_service import _fetch_mlb_api_roster

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "roster": [
                {
                    "person": {"id": 100, "fullName": "Batter A"},
                    "position": {"type": "Outfielder"},
                },
                {
                    "person": {"id": 200, "fullName": "Pitcher B"},
                    "position": {"type": "Pitcher"},
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _fetch_mlb_api_roster("147")
        assert result is not None
        assert len(result["batters"]) == 1
        assert len(result["pitchers"]) == 1
        assert result["batters"][0]["name"] == "Batter A"
        assert result["pitchers"][0]["name"] == "Pitcher B"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_returns_none_on_error(self, mock_client_cls):
        from app.analytics.services.profile_service import _fetch_mlb_api_roster

        mock_client_cls.side_effect = Exception("Network error")

        result = await _fetch_mlb_api_roster("147")
        assert result is None

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_returns_none_on_empty_roster(self, mock_client_cls):
        from app.analytics.services.profile_service import _fetch_mlb_api_roster

        mock_response = MagicMock()
        mock_response.json.return_value = {"roster": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _fetch_mlb_api_roster("147")
        assert result is None

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_skips_entries_with_missing_id_or_name(self, mock_client_cls):
        """Line 683: entries missing player_id or name are skipped."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "roster": [
                # Missing person.id
                {"person": {"fullName": "No ID"}, "position": {"type": "Outfielder"}},
                # Missing person.fullName
                {"person": {"id": 999}, "position": {"type": "Pitcher"}},
                # Empty person
                {"person": {}, "position": {"type": "Outfielder"}},
                # Valid entry
                {"person": {"id": 100, "fullName": "Good Player"}, "position": {"type": "Outfielder"}},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _fetch_mlb_api_roster("147")
        assert result is not None
        # Only the one valid entry should appear
        assert len(result["batters"]) == 1
        assert result["batters"][0]["name"] == "Good Player"
        assert len(result["pitchers"]) == 0


# ---------------------------------------------------------------------------
# _season_weights and _weighted_mean (lines 43, 52)
# ---------------------------------------------------------------------------


class TestSeasonWeightsAndWeightedMean:
    def test_season_weights_empty(self):
        """Line 43: empty game_dates returns empty list."""
        assert _season_weights([]) == []

    def test_season_weights_mixed_years(self):
        dates = [datetime(2026, 3, 1), datetime(2026, 2, 1), datetime(2025, 9, 1)]
        weights = _season_weights(dates)
        assert weights == [1.0, 1.0, 0.7]

    def test_weighted_mean_zero_weights(self):
        """Line 52: total weight is 0 returns 0.0."""
        assert _weighted_mean([(5.0, 0.0), (3.0, 0.0)]) == 0.0

    def test_weighted_mean_normal(self):
        result = _weighted_mean([(10.0, 1.0), (20.0, 1.0)])
        assert result == 15.0


# ---------------------------------------------------------------------------
# get_team_rolling_profile (lines 75, 101-147)
# ---------------------------------------------------------------------------


class TestGetTeamRollingProfile:
    @pytest.mark.asyncio
    async def test_returns_none_for_non_mlb_sport(self):
        """Line 75: non-MLB sport returns None immediately."""
        db = AsyncMock()
        result = await get_team_rolling_profile("NYY", "nba", db=db)
        assert result is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_team(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        result = await get_team_rolling_profile("XXX", "mlb", db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_insufficient_games(self):
        """Lines 116-121: fewer than 5 games returns None."""
        db = AsyncMock()

        team = MagicMock()
        team.id = 1

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = team
            else:
                # Only 3 rows — below threshold of 5
                result.all.return_value = [
                    (MagicMock(), datetime(2026, 3, i, tzinfo=UTC))
                    for i in range(1, 4)
                ]
            return result

        db.execute = mock_execute

        result = await get_team_rolling_profile("NYY", "mlb", db=db)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.analytics.services.profile_service.stats_to_metrics", create=True)
    async def test_returns_profile_result_with_sufficient_games(self, mock_stm):
        """Lines 101-147: full happy path returning ProfileResult."""
        # stats_to_metrics is imported inside the function body, so we need
        # to patch where it's actually called.
        mock_stm.return_value = {"whiff_rate": 0.23, "barrel_rate": 0.07}

        db = AsyncMock()
        team = MagicMock()
        team.id = 1

        game_dates = [datetime(2026, 3, i, tzinfo=UTC) for i in range(1, 8)]
        game_dates.reverse()  # desc order

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = team
            else:
                result.all.return_value = [
                    (MagicMock(), gd) for gd in game_dates
                ]
            return result

        db.execute = mock_execute

        with patch("app.tasks._training_helpers.stats_to_metrics", return_value={"whiff_rate": 0.23, "barrel_rate": 0.07}):
            result = await get_team_rolling_profile("NYY", "mlb", db=db)

        assert result is not None
        assert isinstance(result, ProfileResult)
        assert result.games_used == 7
        assert "whiff_rate" in result.metrics
        assert "barrel_rate" in result.metrics
        assert len(result.date_range) == 2
        assert result.season_breakdown[2026] == 7

    @pytest.mark.asyncio
    async def test_exclude_playoffs_flag(self):
        """Line 112: exclude_playoffs adds a filter."""
        db = AsyncMock()
        team = MagicMock()
        team.id = 1

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = team
            else:
                result.all.return_value = []
            return result

        db.execute = mock_execute

        # Just verify it doesn't crash with exclude_playoffs=True
        result = await get_team_rolling_profile(
            "NYY", "mlb", exclude_playoffs=True, db=db
        )
        assert result is None  # no rows returned


# ---------------------------------------------------------------------------
# get_team_info (line 179)
# ---------------------------------------------------------------------------


class TestGetTeamInfo:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_team(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        result = await get_team_info("XXX", db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_team_info_dict(self):
        """Line 179: returns dict with team info."""
        db = AsyncMock()
        team = MagicMock()
        team.id = 42
        team.name = "New York Yankees"
        team.short_name = "Yankees"
        team.abbreviation = "NYY"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = team
        db.execute.return_value = result_mock

        result = await get_team_info("NYY", db=db)
        assert result is not None
        assert result["id"] == 42
        assert result["name"] == "New York Yankees"
        assert result["short_name"] == "Yankees"
        assert result["abbreviation"] == "NYY"


# ---------------------------------------------------------------------------
# profile_to_pa_probabilities (lines 226-232)
# ---------------------------------------------------------------------------


class TestProfileToPaProbabilities:
    def test_normal_profile_returns_all_keys(self):
        profile = {
            "whiff_rate": 0.23,
            "barrel_rate": 0.07,
            "hard_hit_rate": 0.35,
            "contact_rate": 0.77,
            "chase_rate": 0.32,
        }
        result = profile_to_pa_probabilities(profile)
        expected_keys = {
            "strikeout_probability", "walk_probability", "single_probability",
            "double_probability", "triple_probability", "home_run_probability",
        }
        assert set(result.keys()) == expected_keys
        # All probabilities should be positive
        for v in result.values():
            assert v > 0

    @patch("app.analytics.services.profile_service._clamp", side_effect=lambda val, lo, hi: val)
    def test_extreme_profile_triggers_scaling(self, mock_clamp):
        """Lines 226-232: when _clamp is bypassed, extreme rates push
        named_total > 0.95, triggering the scaling branch."""
        profile = {
            "whiff_rate": 0.95,    # extreme whiff -> very high K rate
            "barrel_rate": 0.50,    # extreme barrel -> high HR rate
            "hard_hit_rate": 0.95,  # extreme hard hit -> high double rate
            "contact_rate": 0.99,   # extreme contact -> high single rate
            "chase_rate": 0.01,     # extreme discipline -> high walk rate
        }
        result = profile_to_pa_probabilities(profile)
        total = sum(result.values())
        # After scaling, the named portion should be <= 0.95
        assert total <= 0.96  # allow tiny floating point slack

    def test_defaults_used_when_keys_missing(self):
        """Uses league-average defaults when profile keys are absent."""
        result = profile_to_pa_probabilities({})
        assert "strikeout_probability" in result
        assert result["strikeout_probability"] > 0


# ---------------------------------------------------------------------------
# get_player_rolling_profile (lines 278, 314-324)
# ---------------------------------------------------------------------------


class TestGetPlayerRollingProfile:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_games(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock

        result = await get_player_rolling_profile("p1", 1, db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_profile_with_enough_games(self):
        """Happy path with >= 5 games, no blending needed."""
        db = AsyncMock()

        game_dates = [datetime(2026, 3, i, tzinfo=UTC) for i in range(7, 0, -1)]
        rows = [(MagicMock(), gd) for gd in game_dates]

        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        with patch(
            "app.tasks._training_helpers.stats_to_metrics",
            return_value={"whiff_rate": 0.20, "barrel_rate": 0.08},
        ):
            result = await get_player_rolling_profile("p1", 1, db=db)

        assert result is not None
        assert "whiff_rate" in result

    @pytest.mark.asyncio
    async def test_exclude_playoffs_flag(self):
        """Line 278: exclude_playoffs adds a season_type filter."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock

        result = await get_player_rolling_profile(
            "p1", 1, exclude_playoffs=True, db=db
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_blends_with_team_profile_for_low_games(self):
        """Lines 314-324: fewer than 5 games blends with team profile."""
        db = AsyncMock()

        # Player has only 3 games
        player_dates = [datetime(2026, 3, i, tzinfo=UTC) for i in range(3, 0, -1)]
        player_rows = [(MagicMock(), gd) for gd in player_dates]

        team_mock = MagicMock()
        team_mock.abbreviation = "NYY"

        # Team rolling profile result (via get_team_rolling_profile)
        team_profile_result = ProfileResult(
            metrics={"whiff_rate": 0.30, "barrel_rate": 0.10},
            games_used=20,
            date_range=("2026-01-01", "2026-03-07"),
            season_breakdown={2026: 20},
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Player game query
                result.all.return_value = player_rows
            elif call_count == 2:
                # Team lookup by id (inside blending path)
                result.scalar_one_or_none.return_value = team_mock
            else:
                result.all.return_value = []
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute

        with patch(
            "app.tasks._training_helpers.stats_to_metrics",
            return_value={"whiff_rate": 0.20, "barrel_rate": 0.08},
        ), patch(
            "app.analytics.services.profile_service.get_team_rolling_profile",
            return_value=team_profile_result,
        ):
            result = await get_player_rolling_profile("p1", 1, db=db)

        assert result is not None
        # With 3 games: player_weight = 3/5 = 0.6, team_weight = 0.4
        # blended whiff_rate = 0.20 * 0.6 + 0.30 * 0.4 = 0.24
        assert abs(result["whiff_rate"] - 0.24) < 0.01

    @pytest.mark.asyncio
    async def test_blending_skipped_when_team_not_found(self):
        """When team lookup fails, returns unblended player profile."""
        db = AsyncMock()

        player_dates = [datetime(2026, 3, i, tzinfo=UTC) for i in range(3, 0, -1)]
        player_rows = [(MagicMock(), gd) for gd in player_dates]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.all.return_value = player_rows
            elif call_count == 2:
                # Team lookup returns None
                result.scalar_one_or_none.return_value = None
            else:
                result.all.return_value = []
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute

        with patch(
            "app.tasks._training_helpers.stats_to_metrics",
            return_value={"whiff_rate": 0.20},
        ):
            result = await get_player_rolling_profile("p1", 1, db=db)

        assert result is not None
        assert abs(result["whiff_rate"] - 0.20) < 0.01


# ---------------------------------------------------------------------------
# _pitcher_profile_from_statcast exclude_playoffs (line 388)
# ---------------------------------------------------------------------------


class TestPitcherStatcastExcludePlayoffs:
    @pytest.mark.asyncio
    async def test_exclude_playoffs_flag(self):
        """Line 388: exclude_playoffs adds season_type filter."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_statcast(
            "p1", 1, exclude_playoffs=True, db=db
        )
        # With 0 rows < 3, returns None
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_batters_faced_is_not_numeric(self):
        """Line 398: returns None when batters_faced is an unexpected type."""
        db = AsyncMock()

        # Create a row where batters_faced is a string (not int/float/None)
        bad_stat = SimpleNamespace(batters_faced="invalid")
        game_date = datetime(2026, 3, 1, tzinfo=UTC)
        rows = [(bad_stat, game_date) for _ in range(5)]

        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_statcast("p1", 1, db=db)
        assert result is None


# ---------------------------------------------------------------------------
# _pitcher_profile_from_boxscore exclude_playoffs (line 465)
# ---------------------------------------------------------------------------


class TestPitcherBoxscoreExcludePlayoffs:
    @pytest.mark.asyncio
    async def test_exclude_playoffs_flag(self):
        """Line 465: exclude_playoffs adds season_type filter."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock

        result = await _pitcher_profile_from_boxscore(
            "p1", 1, exclude_playoffs=True, db=db
        )
        assert result is None
