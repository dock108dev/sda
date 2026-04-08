"""Tests for non-MLB sport analytics: player profiles, rotation weights, and
rotation services for NBA, NCAAB, NHL, and NFL drive profiles/weights.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db_rows(rows):
    """Return an AsyncMock db whose execute() yields the given rows."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute.return_value = result
    return db


def _mock_db_scalar(value):
    """Return an AsyncMock db whose execute().scalar_one_or_none() returns value."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute.return_value = result
    return db


def _make_nba_player_row(**overrides):
    defaults = dict(
        player_external_ref="nba-p1",
        player_name="Player One",
        minutes=30.0,
        off_rating=115.0,
        def_rating=112.0,
        usg_pct=0.22,
        ts_pct=0.58,
        efg_pct=0.54,
        contested_2pt_fga=3,
        uncontested_2pt_fga=4,
        contested_2pt_fgm=2,
        uncontested_2pt_fgm=3,
        contested_3pt_fga=2,
        uncontested_3pt_fga=3,
        contested_3pt_fgm=1,
        uncontested_3pt_fgm=1,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_ncaab_player_row(**overrides):
    defaults = dict(
        player_external_ref="ncaab-p1",
        player_name="College Star",
        minutes=25.0,
        off_rating=108.0,
        usg_pct=0.23,
        ts_pct=0.55,
        efg_pct=0.50,
        points=15,
        rebounds=6,
        assists=3,
        turnovers=2,
        steals=1,
        blocks=1,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_nhl_skater_row(**overrides):
    defaults = dict(
        player_external_ref="nhl-s1",
        player_name="Skater One",
        toi_minutes=18.0,
        xgoals_for=0.6,
        xgoals_against=0.4,
        shooting_pct=10.0,
        goals_per_60=0.8,
        shots_per_60=9.0,
        game_score=1.5,
        shots=3,
        goals=1,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_nfl_adv_row(**overrides):
    defaults = dict(
        game_id=100,
        team_id=1,
        epa_per_play=0.05,
        pass_epa=0.10,
        rush_epa=-0.02,
        success_rate=0.47,
        pass_success_rate=0.50,
        rush_success_rate=0.42,
        explosive_play_rate=0.09,
        avg_cpoe=1.5,
        avg_air_yards=8.0,
        avg_yac=5.5,
        pass_plays=35,
        rush_plays=25,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ===================================================================
# NBA Player Profiles
# ===================================================================

class TestNBAPlayerRollingProfile:

    @pytest.mark.asyncio
    async def test_returns_none_when_insufficient_games(self):
        from app.analytics.services.nba_player_profiles import get_nba_player_rolling_profile

        db = _mock_db_rows([_make_nba_player_row(), _make_nba_player_row()])
        result = await get_nba_player_rolling_profile(db, "nba-p1", team_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_profile_with_enough_games(self):
        from app.analytics.services.nba_player_profiles import get_nba_player_rolling_profile

        rows = [_make_nba_player_row() for _ in range(5)]
        db = _mock_db_rows(rows)
        result = await get_nba_player_rolling_profile(db, "nba-p1", team_id=1)

        assert result is not None
        assert result["games_found"] == 5
        assert "off_rating" in result
        assert "tov_rate" in result
        assert "fg3_rate" in result
        assert "fg2_pct" in result

    @pytest.mark.asyncio
    async def test_shooting_splits_zero_fga(self):
        from app.analytics.services.nba_player_profiles import get_nba_player_rolling_profile

        rows = [
            _make_nba_player_row(
                contested_2pt_fga=0, uncontested_2pt_fga=0,
                contested_2pt_fgm=0, uncontested_2pt_fgm=0,
                contested_3pt_fga=0, uncontested_3pt_fga=0,
                contested_3pt_fgm=0, uncontested_3pt_fgm=0,
            )
            for _ in range(4)
        ]
        db = _mock_db_rows(rows)
        result = await get_nba_player_rolling_profile(db, "nba-p1", team_id=1)
        assert result is not None
        assert "fg3_rate" not in result
        assert "fg2_rate" not in result

    @pytest.mark.asyncio
    async def test_tov_rate_clamped(self):
        from app.analytics.services.nba_player_profiles import get_nba_player_rolling_profile

        rows = [_make_nba_player_row(usg_pct=0.50) for _ in range(4)]
        db = _mock_db_rows(rows)
        result = await get_nba_player_rolling_profile(db, "nba-p1", team_id=1)
        assert result["tov_rate"] <= 0.25

        rows = [_make_nba_player_row(usg_pct=0.0) for _ in range(4)]
        db = _mock_db_rows(rows)
        result = await get_nba_player_rolling_profile(db, "nba-p1", team_id=1)
        assert result["tov_rate"] >= 0.05

    @pytest.mark.asyncio
    async def test_none_field_values_skipped(self):
        from app.analytics.services.nba_player_profiles import get_nba_player_rolling_profile

        rows = [
            _make_nba_player_row(off_rating=None),
            _make_nba_player_row(off_rating=110.0),
            _make_nba_player_row(off_rating=120.0),
            _make_nba_player_row(off_rating=None),
        ]
        db = _mock_db_rows(rows)
        result = await get_nba_player_rolling_profile(db, "nba-p1", team_id=1)
        assert result is not None
        assert result["off_rating"] == round((110.0 + 120.0) / 2, 4)


class TestNBABuildUnitProbabilities:

    @pytest.mark.asyncio
    async def test_empty_players_returns_defaults(self):
        from app.analytics.services.nba_player_profiles import build_unit_probabilities

        db = AsyncMock()
        result = await build_unit_probabilities(db, [], team_id=1)
        assert "ft_pct" in result

    @pytest.mark.asyncio
    @patch("app.analytics.services.nba_player_profiles.get_nba_player_rolling_profile")
    async def test_fallback_to_baseline_when_no_profile(self, mock_profile):
        from app.analytics.services.nba_player_profiles import build_unit_probabilities

        mock_profile.return_value = None
        db = AsyncMock()
        players = [{"external_ref": "p1", "name": "Test"}]
        result = await build_unit_probabilities(db, players, team_id=1)
        assert "two_pt_make_probability" in result
        assert "turnover_probability" in result

    @pytest.mark.asyncio
    @patch("app.analytics.services.nba_player_profiles.get_nba_player_rolling_profile")
    async def test_with_real_profiles(self, mock_profile):
        from app.analytics.services.nba_player_profiles import build_unit_probabilities

        mock_profile.return_value = {
            "off_rating": 118.0, "ts_pct": 0.60, "efg_pct": 0.56,
            "usg_pct": 0.25, "fg3_rate": 0.40, "fg2_pct": 0.55,
            "fg3_pct": 0.38, "tov_rate": 0.12,
        }
        db = AsyncMock()
        players = [{"external_ref": "p1", "name": "Star"}]
        result = await build_unit_probabilities(db, players, team_id=1)

        for key in [
            "two_pt_make_probability", "three_pt_make_probability",
            "three_pt_miss_probability", "free_throw_trip_probability",
            "turnover_probability", "ft_pct",
        ]:
            assert key in result
            assert 0.0 <= result[key] <= 1.0

    @pytest.mark.asyncio
    @patch("app.analytics.services.nba_player_profiles.get_nba_player_rolling_profile")
    async def test_opposing_defense_adjustment(self, mock_profile):
        from app.analytics.services.nba_player_profiles import build_unit_probabilities

        mock_profile.return_value = {
            "off_rating": 114.0, "ts_pct": 0.58, "efg_pct": 0.54,
            "usg_pct": 0.20, "fg3_rate": 0.35, "fg2_pct": 0.52,
            "fg3_pct": 0.36, "tov_rate": 0.13,
        }
        db = AsyncMock()
        players = [{"external_ref": "p1", "name": "Test"}]

        result_elite = await build_unit_probabilities(
            db, players, team_id=1, opposing_def_rating=108.0,
        )
        result_bad = await build_unit_probabilities(
            db, players, team_id=1, opposing_def_rating=120.0,
        )
        assert result_bad["two_pt_make_probability"] >= result_elite["two_pt_make_probability"]

    @pytest.mark.asyncio
    @patch("app.analytics.services.nba_player_profiles.get_nba_player_rolling_profile")
    async def test_player_without_external_ref_gets_fallback(self, mock_profile):
        from app.analytics.services.nba_player_profiles import build_unit_probabilities

        mock_profile.return_value = None
        db = AsyncMock()
        players = [{"external_ref": "", "name": "No Ref"}]
        result = await build_unit_probabilities(db, players, team_id=1)
        assert "two_pt_make_probability" in result
        mock_profile.assert_not_called()


class TestNBAAggregateToProbs:

    def test_probabilities_valid(self):
        from app.analytics.services.nba_player_profiles import _aggregate_to_possession_probs

        profiles = [
            {"off_rating": 114.0, "ts_pct": 0.58, "efg_pct": 0.54,
             "usg_pct": 0.20, "fg3_rate": 0.35, "fg2_pct": 0.52,
             "fg3_pct": 0.36, "tov_rate": 0.13},
        ]
        result = _aggregate_to_possession_probs(profiles, None)
        for key in [
            "two_pt_make_probability", "three_pt_make_probability",
            "three_pt_miss_probability", "free_throw_trip_probability",
            "turnover_probability",
        ]:
            assert key in result
            assert 0.0 <= result[key] <= 1.0
        assert "ft_pct" in result

    def test_zero_usage_handled(self):
        from app.analytics.services.nba_player_profiles import _aggregate_to_possession_probs

        profiles = [{"usg_pct": 0.0}]
        result = _aggregate_to_possession_probs(profiles, None)
        assert "two_pt_make_probability" in result


# ===================================================================
# NBA Rotation Weights
# ===================================================================

class TestNBARotationWeights:

    @pytest.mark.asyncio
    @patch("app.analytics.services.nba_player_profiles.build_unit_probabilities")
    @patch("app.analytics.sports.nba.game_simulator._build_weights")
    async def test_build_rotation_weights(self, mock_build_w, mock_unit_probs):
        from app.analytics.services.nba_rotation_weights import build_rotation_weights

        mock_unit_probs.return_value = {
            "two_pt_make_probability": 0.26,
            "three_pt_make_probability": 0.13,
            "three_pt_miss_probability": 0.22,
            "free_throw_trip_probability": 0.10,
            "turnover_probability": 0.13,
            "ft_pct": 0.78,
        }
        mock_build_w.return_value = [0.26, 0.13, 0.22, 0.10, 0.13]

        rotation = {
            "starters": [{"external_ref": "p1", "name": "S1"}],
            "bench": [{"external_ref": "p2", "name": "B1"}],
            "starter_minutes_share": 0.72,
        }
        db = AsyncMock()
        result = await build_rotation_weights(db, rotation, team_id=1)

        assert "starter_weights" in result
        assert "bench_weights" in result
        assert result["starter_share"] == 0.72
        assert result["players_resolved"] == 2
        assert "ft_pct_starter" in result
        assert "ft_pct_bench" in result

    @pytest.mark.asyncio
    @patch("app.analytics.services.nba_player_profiles.build_unit_probabilities")
    @patch("app.analytics.sports.nba.game_simulator._build_weights")
    async def test_empty_bench_falls_back_to_starters(self, mock_build_w, mock_unit_probs):
        from app.analytics.services.nba_rotation_weights import build_rotation_weights

        mock_unit_probs.return_value = {"ft_pct": 0.78}
        mock_build_w.return_value = [0.5, 0.5]

        rotation = {
            "starters": [{"external_ref": "p1", "name": "S1"}],
            "bench": [],
            "starter_minutes_share": 0.70,
        }
        db = AsyncMock()
        result = await build_rotation_weights(db, rotation, team_id=1)
        assert mock_unit_probs.call_count == 2
        # Second call should receive starters (fallback for empty bench)
        second_call_players = mock_unit_probs.call_args_list[1][0][1]
        assert second_call_players == rotation["starters"]


# ===================================================================
# NBA Rotation Service
# ===================================================================

class TestNBARotationService:

    @pytest.mark.asyncio
    async def test_reconstruct_returns_none_when_few_players(self):
        from app.analytics.services.nba_rotation_service import reconstruct_rotation_from_stats

        db = _mock_db_rows([_make_nba_player_row() for _ in range(3)])
        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_reconstruct_returns_none_when_active_below_five(self):
        from app.analytics.services.nba_rotation_service import reconstruct_rotation_from_stats

        rows = [_make_nba_player_row(minutes=20.0)] + [
            _make_nba_player_row(minutes=0) for _ in range(5)
        ]
        db = _mock_db_rows(rows)
        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_reconstruct_splits_starters_and_bench(self):
        from app.analytics.services.nba_rotation_service import reconstruct_rotation_from_stats

        rows = [
            _make_nba_player_row(
                player_external_ref=f"p{i}",
                player_name=f"Player {i}",
                minutes=float(30 - i * 2),
            )
            for i in range(8)
        ]
        db = _mock_db_rows(rows)
        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)

        assert result is not None
        assert len(result["starters"]) == 5
        assert len(result["bench"]) == 3
        assert 0 < result["starter_minutes_share"] < 1

    @pytest.mark.asyncio
    async def test_get_recent_rotation_no_game_found(self):
        from app.analytics.services.nba_rotation_service import get_recent_rotation

        db = _mock_db_scalar(None)
        result = await get_recent_rotation(db, team_id=1)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.analytics.services.nba_rotation_service.reconstruct_rotation_from_stats")
    async def test_get_recent_rotation_delegates(self, mock_reconstruct):
        from app.analytics.services.nba_rotation_service import get_recent_rotation

        mock_reconstruct.return_value = {"starters": [], "bench": [], "starter_minutes_share": 0.7}
        db = _mock_db_scalar(42)
        result = await get_recent_rotation(db, team_id=1)
        mock_reconstruct.assert_awaited_once_with(db, 42, 1)
        assert result is not None


# ===================================================================
# NCAAB Player Profiles
# ===================================================================

class TestNCAABPlayerRollingProfile:

    @pytest.mark.asyncio
    async def test_returns_none_when_insufficient_games(self):
        from app.analytics.services.ncaab_player_profiles import get_ncaab_player_rolling_profile

        db = _mock_db_rows([_make_ncaab_player_row()])
        result = await get_ncaab_player_rolling_profile(db, "ncaab-p1", team_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_profile_with_per_minute_rates(self):
        from app.analytics.services.ncaab_player_profiles import get_ncaab_player_rolling_profile

        rows = [_make_ncaab_player_row() for _ in range(4)]
        db = _mock_db_rows(rows)
        result = await get_ncaab_player_rolling_profile(db, "ncaab-p1", team_id=1)

        assert result is not None
        assert result["games_found"] == 4
        assert "pts_per_min" in result
        assert "reb_per_min" in result
        assert "tov_rate" in result

    @pytest.mark.asyncio
    async def test_zero_minutes_total(self):
        from app.analytics.services.ncaab_player_profiles import get_ncaab_player_rolling_profile

        rows = [_make_ncaab_player_row(minutes=0) for _ in range(4)]
        db = _mock_db_rows(rows)
        result = await get_ncaab_player_rolling_profile(db, "ncaab-p1", team_id=1)
        assert result is not None
        assert "pts_per_min" not in result


class TestNCAABBuildUnitProbabilities:

    @pytest.mark.asyncio
    async def test_empty_players_returns_defaults(self):
        from app.analytics.services.ncaab_player_profiles import build_unit_probabilities

        db = AsyncMock()
        result = await build_unit_probabilities(db, [], team_id=1)
        assert "ft_pct" in result
        assert "orb_pct" in result

    @pytest.mark.asyncio
    @patch("app.analytics.services.ncaab_player_profiles.get_ncaab_player_rolling_profile")
    async def test_with_profiles(self, mock_profile):
        from app.analytics.services.ncaab_player_profiles import build_unit_probabilities

        mock_profile.return_value = {
            "off_rating": 108.0, "ts_pct": 0.55, "efg_pct": 0.50,
            "usg_pct": 0.22, "tov_rate": 0.15,
        }
        db = AsyncMock()
        players = [{"external_ref": "p1", "name": "Test"}]
        result = await build_unit_probabilities(db, players, team_id=1)

        for key in [
            "two_pt_make_probability", "three_pt_make_probability",
            "turnover_probability", "ft_pct", "orb_pct",
        ]:
            assert key in result
            assert 0.0 <= result[key] <= 1.0


class TestNCAABAggregateToProbs:

    def test_probabilities_valid(self):
        from app.analytics.services.ncaab_player_profiles import _aggregate_to_possession_probs

        profiles = [{"off_rating": 105.0, "ts_pct": 0.54, "efg_pct": 0.50,
                      "usg_pct": 0.20, "tov_rate": 0.17}]
        result = _aggregate_to_possession_probs(profiles, None)
        for key in [
            "two_pt_make_probability", "three_pt_make_probability",
            "three_pt_miss_probability", "free_throw_trip_probability",
            "turnover_probability",
        ]:
            assert key in result
            assert 0.0 <= result[key] <= 1.0
        assert "ft_pct" in result
        assert "orb_pct" in result

    def test_orb_pct_clamped(self):
        from app.analytics.services.ncaab_player_profiles import _aggregate_to_possession_probs

        profiles = [{"off_rating": 150.0, "usg_pct": 0.20}]
        result = _aggregate_to_possession_probs(profiles, None)
        assert result["orb_pct"] <= 0.38

        profiles = [{"off_rating": 70.0, "usg_pct": 0.20}]
        result = _aggregate_to_possession_probs(profiles, None)
        assert result["orb_pct"] >= 0.18


# ===================================================================
# NCAAB Rotation Weights
# ===================================================================

class TestNCAABRotationWeights:

    @pytest.mark.asyncio
    @patch("app.analytics.services.ncaab_player_profiles.build_unit_probabilities")
    @patch("app.analytics.sports.ncaab.game_simulator._build_weights")
    async def test_build_rotation_weights(self, mock_bw, mock_up):
        from app.analytics.services.ncaab_rotation_weights import build_rotation_weights

        mock_up.return_value = {"ft_pct": 0.70, "orb_pct": 0.28}
        mock_bw.return_value = [0.2, 0.2, 0.2, 0.2, 0.2]

        rotation = {
            "starters": [{"external_ref": "p1", "name": "S1"}],
            "bench": [{"external_ref": "p2", "name": "B1"}],
            "starter_minutes_share": 0.68,
        }
        db = AsyncMock()
        result = await build_rotation_weights(db, rotation, team_id=1)

        assert result["starter_share"] == 0.68
        assert "orb_pct_starter" in result
        assert "orb_pct_bench" in result
        assert result["players_resolved"] == 2


# ===================================================================
# NCAAB Rotation Service
# ===================================================================

class TestNCAABRotationService:

    @pytest.mark.asyncio
    async def test_reconstruct_returns_none_when_few_players(self):
        from app.analytics.services.ncaab_rotation_service import reconstruct_rotation_from_stats

        db = _mock_db_rows([_make_ncaab_player_row() for _ in range(3)])
        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_reconstruct_splits_starters_bench(self):
        from app.analytics.services.ncaab_rotation_service import reconstruct_rotation_from_stats

        rows = [
            _make_ncaab_player_row(
                player_external_ref=f"p{i}",
                player_name=f"Player {i}",
                minutes=float(30 - i * 2),
            )
            for i in range(7)
        ]
        db = _mock_db_rows(rows)
        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)

        assert result is not None
        assert len(result["starters"]) == 5
        assert len(result["bench"]) == 2

    @pytest.mark.asyncio
    async def test_get_recent_rotation_no_game(self):
        from app.analytics.services.ncaab_rotation_service import get_recent_rotation

        db = _mock_db_scalar(None)
        result = await get_recent_rotation(db, team_id=1)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.analytics.services.ncaab_rotation_service.reconstruct_rotation_from_stats")
    async def test_get_recent_rotation_with_exclude(self, mock_recon):
        from app.analytics.services.ncaab_rotation_service import get_recent_rotation

        mock_recon.return_value = {"starters": [], "bench": [], "starter_minutes_share": 0.7}
        db = _mock_db_scalar(99)
        result = await get_recent_rotation(db, team_id=1, exclude_game_id=50)
        mock_recon.assert_awaited_once_with(db, 99, 1)


# ===================================================================
# NHL Player Profiles
# ===================================================================

class TestNHLPlayerRollingProfile:

    @pytest.mark.asyncio
    async def test_returns_none_when_insufficient_games(self):
        from app.analytics.services.nhl_player_profiles import get_nhl_player_rolling_profile

        db = _mock_db_rows([_make_nhl_skater_row()])
        result = await get_nhl_player_rolling_profile(db, "nhl-s1", team_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_profile(self):
        from app.analytics.services.nhl_player_profiles import get_nhl_player_rolling_profile

        rows = [_make_nhl_skater_row() for _ in range(5)]
        db = _mock_db_rows(rows)
        result = await get_nhl_player_rolling_profile(db, "nhl-s1", team_id=1)

        assert result is not None
        assert result["games_found"] == 5
        assert "toi_minutes" in result
        assert "shooting_pct" in result
        assert "goals" in result


class TestNHLBuildUnitProbabilities:

    @pytest.mark.asyncio
    async def test_empty_players_returns_defaults(self):
        from app.analytics.services.nhl_player_profiles import build_unit_probabilities

        db = AsyncMock()
        result = await build_unit_probabilities(db, [], team_id=1)
        assert "goal_probability" in result or "goal" in result

    @pytest.mark.asyncio
    @patch("app.analytics.services.nhl_player_profiles.get_nhl_player_rolling_profile")
    async def test_with_profiles(self, mock_profile):
        from app.analytics.services.nhl_player_profiles import build_unit_probabilities

        mock_profile.return_value = {
            "shooting_pct": 12.0,
            "shots_per_60": 10.0,
            "toi_minutes": 20.0,
            "xgoals_for": 0.7,
        }
        db = AsyncMock()
        players = [{"external_ref": "s1", "name": "Sniper"}]
        result = await build_unit_probabilities(db, players, team_id=1)

        assert "goal_probability" in result
        assert "blocked_shot_probability" in result
        assert "missed_shot_probability" in result
        assert 0.0 <= result["goal_probability"] <= 1.0

    @pytest.mark.asyncio
    @patch("app.analytics.services.nhl_player_profiles.get_nhl_player_rolling_profile")
    async def test_goalie_adjustment(self, mock_profile):
        from app.analytics.services.nhl_player_profiles import build_unit_probabilities

        mock_profile.return_value = {
            "shooting_pct": 9.0, "toi_minutes": 18.0, "xgoals_for": 0.5,
        }
        db = AsyncMock()
        players = [{"external_ref": "s1", "name": "Test"}]

        result_elite = await build_unit_probabilities(
            db, players, team_id=1, opposing_goalie_save_pct=0.930,
        )
        result_bad = await build_unit_probabilities(
            db, players, team_id=1, opposing_goalie_save_pct=0.880,
        )
        assert result_bad["goal_probability"] >= result_elite["goal_probability"]


class TestNHLAggregateToShotProbs:

    def test_goal_probability_clamped(self):
        from app.analytics.services.nhl_player_profiles import _aggregate_to_shot_probs

        profiles = [{"shooting_pct": 50.0, "toi_minutes": 20.0, "xgoals_for": 2.0}]
        result = _aggregate_to_shot_probs(profiles, None)
        assert result["goal_probability"] <= 0.18

        profiles = [{"shooting_pct": 0.1, "toi_minutes": 20.0, "xgoals_for": 0.1}]
        result = _aggregate_to_shot_probs(profiles, None)
        assert result["goal_probability"] >= 0.03

    def test_goalie_save_pct_over_one_normalized(self):
        from app.analytics.services.nhl_player_profiles import _aggregate_to_shot_probs

        profiles = [{"shooting_pct": 9.0, "toi_minutes": 18.0, "xgoals_for": 0.5}]
        result = _aggregate_to_shot_probs(profiles, opposing_goalie_save_pct=91.0)
        assert "goal_probability" in result

    def test_zero_toi_handled(self):
        from app.analytics.services.nhl_player_profiles import _aggregate_to_shot_probs

        profiles = [{"toi_minutes": 0.0}]
        result = _aggregate_to_shot_probs(profiles, None)
        assert "goal_probability" in result


# ===================================================================
# NHL Rotation Weights
# ===================================================================

class TestNHLRotationWeights:

    @pytest.mark.asyncio
    @patch("app.analytics.services.nhl_player_profiles.build_unit_probabilities")
    @patch("app.analytics.sports.nhl.game_simulator._build_weights")
    async def test_build_rotation_weights(self, mock_bw, mock_up):
        from app.analytics.services.nhl_rotation_weights import build_rotation_weights

        mock_up.return_value = {"goal_probability": 0.09}
        mock_bw.return_value = [0.09, 0.62, 0.16, 0.13]

        rotation = {
            "starters": [{"external_ref": "s1"}] * 6,
            "bench": [{"external_ref": "b1"}] * 4,
            "starter_minutes_share": 0.65,
        }
        db = AsyncMock()
        result = await build_rotation_weights(db, rotation, team_id=1)

        assert result["starter_share"] == 0.65
        assert result["players_resolved"] == 10
        assert "starter_weights" in result
        assert "bench_weights" in result


# ===================================================================
# NHL Rotation Service
# ===================================================================

class TestNHLRotationService:

    @pytest.mark.asyncio
    async def test_reconstruct_returns_none_when_few_skaters(self):
        from app.analytics.services.nhl_rotation_service import reconstruct_rotation_from_stats

        rows = [_make_nhl_skater_row() for _ in range(3)]
        db = AsyncMock()
        result1 = MagicMock()
        result1.scalars.return_value.all.return_value = rows
        db.execute.return_value = result1

        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_reconstruct_splits_starters_bench_and_goalie(self):
        from app.analytics.services.nhl_rotation_service import reconstruct_rotation_from_stats

        skaters = [
            _make_nhl_skater_row(
                player_external_ref=f"s{i}",
                player_name=f"Skater {i}",
                toi_minutes=float(22 - i),
            )
            for i in range(15)
        ]

        goalie = SimpleNamespace(
            player_external_ref="g1",
            player_name="Goalie One",
            save_pct=0.920,
            shots_against=35,
        )

        db = AsyncMock()
        skater_result = MagicMock()
        skater_result.scalars.return_value.all.return_value = skaters
        goalie_result = MagicMock()
        goalie_result.scalar_one_or_none.return_value = goalie
        db.execute.side_effect = [skater_result, goalie_result]

        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)
        assert result is not None
        assert len(result["starters"]) == 10
        assert len(result["bench"]) == 5
        assert result["goalie"]["external_ref"] == "g1"
        assert result["goalie"]["save_pct"] == 0.920

    @pytest.mark.asyncio
    async def test_reconstruct_no_goalie(self):
        from app.analytics.services.nhl_rotation_service import reconstruct_rotation_from_stats

        skaters = [
            _make_nhl_skater_row(
                player_external_ref=f"s{i}",
                player_name=f"Skater {i}",
                toi_minutes=float(20 - i),
            )
            for i in range(8)
        ]

        db = AsyncMock()
        skater_result = MagicMock()
        skater_result.scalars.return_value.all.return_value = skaters
        goalie_result = MagicMock()
        goalie_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [skater_result, goalie_result]

        result = await reconstruct_rotation_from_stats(db, game_id=1, team_id=1)
        assert result is not None
        assert result["goalie"] is None

    @pytest.mark.asyncio
    async def test_get_recent_rotation_no_game(self):
        from app.analytics.services.nhl_rotation_service import get_recent_rotation

        db = _mock_db_scalar(None)
        result = await get_recent_rotation(db, team_id=1)
        assert result is None


# ===================================================================
# NFL Drive Profiles
# ===================================================================

class TestNFLBuildTeamProfile:

    @pytest.mark.asyncio
    async def test_returns_none_when_insufficient_games(self):
        from app.analytics.services.nfl_drive_profiles import build_nfl_team_profile

        db = _mock_db_rows([_make_nfl_adv_row()])
        result = await build_nfl_team_profile(db, team_id=1)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.analytics.services.nfl_drive_profiles._get_special_teams_profile")
    @patch("app.analytics.services.nfl_drive_profiles._get_defensive_profile")
    async def test_returns_profile_with_enough_games(self, mock_def, mock_st):
        from app.analytics.services.nfl_drive_profiles import build_nfl_team_profile

        mock_def.return_value = {"def_sacks_per_game": 2.5}
        mock_st.return_value = {"fg_pct": 0.87}

        rows = [_make_nfl_adv_row() for _ in range(4)]
        db = _mock_db_rows(rows)
        result = await build_nfl_team_profile(db, team_id=1)

        assert result is not None
        assert result["games_found"] == 4
        assert "epa_per_play" in result
        assert "pass_rate" in result
        assert result["def_sacks_per_game"] == 2.5
        assert result["fg_pct"] == 0.87

    @pytest.mark.asyncio
    @patch("app.analytics.services.nfl_drive_profiles._get_special_teams_profile")
    @patch("app.analytics.services.nfl_drive_profiles._get_defensive_profile")
    async def test_pass_rate_calculation(self, mock_def, mock_st):
        from app.analytics.services.nfl_drive_profiles import build_nfl_team_profile

        mock_def.return_value = None
        mock_st.return_value = None

        rows = [_make_nfl_adv_row(pass_plays=60, rush_plays=40) for _ in range(3)]
        db = _mock_db_rows(rows)
        result = await build_nfl_team_profile(db, team_id=1)

        assert result is not None
        assert result["pass_rate"] == round(180 / 300, 4)

    @pytest.mark.asyncio
    @patch("app.analytics.services.nfl_drive_profiles._get_special_teams_profile")
    @patch("app.analytics.services.nfl_drive_profiles._get_defensive_profile")
    async def test_zero_plays(self, mock_def, mock_st):
        from app.analytics.services.nfl_drive_profiles import build_nfl_team_profile

        mock_def.return_value = None
        mock_st.return_value = None

        rows = [_make_nfl_adv_row(pass_plays=0, rush_plays=0) for _ in range(3)]
        db = _mock_db_rows(rows)
        result = await build_nfl_team_profile(db, team_id=1)
        assert result is not None
        assert "pass_rate" not in result


class TestNFLDefensiveProfile:

    @pytest.mark.asyncio
    async def test_returns_none_when_no_game_ids(self):
        from app.analytics.services.nfl_drive_profiles import _get_defensive_profile

        db = AsyncMock()
        result = await _get_defensive_profile(db, team_id=1, adv_rows=[])
        assert result is None

    @pytest.mark.asyncio
    async def test_aggregates_defensive_stats(self):
        from app.analytics.services.nfl_drive_profiles import _get_defensive_profile

        adv_rows = [SimpleNamespace(game_id=100), SimpleNamespace(game_id=101)]

        game_100 = SimpleNamespace(id=100, home_team_id=1, away_team_id=2)
        game_101 = SimpleNamespace(id=101, home_team_id=3, away_team_id=1)

        def_box = SimpleNamespace(
            stats={"category": "defensive", "SACKS": 2, "TFL": 3, "QB HTS": 4},
        )
        int_box = SimpleNamespace(
            stats={"category": "interceptions", "INT": 1},
        )

        db = AsyncMock()
        games_result = MagicMock()
        games_result.scalars.return_value.all.return_value = [game_100, game_101]
        box_result1 = MagicMock()
        box_result1.scalars.return_value.all.return_value = [def_box, int_box]
        box_result2 = MagicMock()
        box_result2.scalars.return_value.all.return_value = [def_box]

        db.execute.side_effect = [games_result, box_result1, box_result2]

        result = await _get_defensive_profile(db, team_id=1, adv_rows=adv_rows)
        assert result is not None
        assert result["def_sacks_per_game"] == round(4.0 / 2, 2)
        assert result["def_turnovers_forced_per_game"] == round(1.0 / 2, 2)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_games_found(self):
        from app.analytics.services.nfl_drive_profiles import _get_defensive_profile

        adv_rows = [SimpleNamespace(game_id=999)]

        db = AsyncMock()
        games_result = MagicMock()
        games_result.scalars.return_value.all.return_value = []
        box_result = MagicMock()
        box_result.scalars.return_value.all.return_value = []
        db.execute.side_effect = [games_result, box_result]

        result = await _get_defensive_profile(db, team_id=1, adv_rows=adv_rows)
        assert result is None


class TestNFLSpecialTeamsProfile:

    @pytest.mark.asyncio
    async def test_returns_none_when_no_game_ids(self):
        from app.analytics.services.nfl_drive_profiles import _get_special_teams_profile

        db = AsyncMock()
        result = await _get_special_teams_profile(db, team_id=1, adv_rows=[])
        assert result is None

    @pytest.mark.asyncio
    async def test_parses_fg_stats(self):
        from app.analytics.services.nfl_drive_profiles import _get_special_teams_profile

        adv_rows = [SimpleNamespace(game_id=100)]

        kicking_box = SimpleNamespace(
            stats={"category": "kicking", "FG": "3/4"},
        )

        db = AsyncMock()
        box_result = MagicMock()
        box_result.scalars.return_value.all.return_value = [kicking_box]
        db.execute.return_value = box_result

        result = await _get_special_teams_profile(db, team_id=1, adv_rows=adv_rows)
        assert result is not None
        assert result["fg_pct"] == round(3 / 4, 4)

    @pytest.mark.asyncio
    async def test_no_kicking_stats_returns_default(self):
        from app.analytics.services.nfl_drive_profiles import _get_special_teams_profile

        adv_rows = [SimpleNamespace(game_id=100)]

        db = AsyncMock()
        box_result = MagicMock()
        box_result.scalars.return_value.all.return_value = []
        db.execute.return_value = box_result

        result = await _get_special_teams_profile(db, team_id=1, adv_rows=adv_rows)
        assert result is not None
        assert result["fg_pct"] == 0.85

    @pytest.mark.asyncio
    async def test_bad_fg_string_handled(self):
        from app.analytics.services.nfl_drive_profiles import _get_special_teams_profile

        adv_rows = [SimpleNamespace(game_id=100)]

        bad_box = SimpleNamespace(
            stats={"category": "kicking", "FG": "bad/data"},
        )

        db = AsyncMock()
        box_result = MagicMock()
        box_result.scalars.return_value.all.return_value = [bad_box]
        db.execute.return_value = box_result

        result = await _get_special_teams_profile(db, team_id=1, adv_rows=adv_rows)
        assert result is not None


# ===================================================================
# NFL Drive Weights
# ===================================================================

class TestNFLBuildDriveWeights:

    @pytest.mark.asyncio
    async def test_returns_none_when_both_profiles_missing(self):
        from app.analytics.services.nfl_drive_weights import build_drive_weights

        db = AsyncMock()
        game = SimpleNamespace(home_team_id=1, away_team_id=2)

        with patch(
            "app.analytics.services.nfl_drive_profiles.build_nfl_team_profile",
            return_value=None,
        ):
            result = await build_drive_weights(db, game, None, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_weights_with_profiles(self):
        from app.analytics.services.nfl_drive_weights import build_drive_weights

        db = AsyncMock()
        game = SimpleNamespace(home_team_id=1, away_team_id=2)
        home = {
            "epa_per_play": 0.05, "success_rate": 0.47, "avg_cpoe": 1.5,
            "def_sacks_per_game": 2.5, "def_tfl_per_game": 5.0,
            "def_turnovers_forced_per_game": 1.0, "fg_pct": 0.87,
        }
        away = {
            "epa_per_play": -0.02, "success_rate": 0.42, "avg_cpoe": -1.0,
            "def_sacks_per_game": 3.0, "def_tfl_per_game": 6.0,
            "def_turnovers_forced_per_game": 1.5, "fg_pct": 0.83,
        }

        result = await build_drive_weights(db, game, home, away)
        assert result is not None
        assert "home_drive_weights" in result
        assert "away_drive_weights" in result
        assert len(result["home_drive_weights"]) == 5
        assert len(result["away_drive_weights"]) == 5
        assert result["home_fg_pct"] == 0.87
        assert result["away_fg_pct"] == 0.83

    @pytest.mark.asyncio
    async def test_fetches_missing_away_profile(self):
        from app.analytics.services.nfl_drive_weights import build_drive_weights

        db = AsyncMock()
        game = SimpleNamespace(home_team_id=1, away_team_id=2)
        home = {
            "epa_per_play": 0.0, "success_rate": 0.45,
            "def_sacks_per_game": 2.5, "def_tfl_per_game": 5.0,
            "def_turnovers_forced_per_game": 1.0,
        }

        with patch(
            "app.analytics.services.nfl_drive_profiles.build_nfl_team_profile",
            return_value=home,
        ):
            result = await build_drive_weights(db, game, home, None)
        assert result is not None


class TestNFLDeriveDriveWeights:

    def test_weights_sum_to_one(self):
        from app.analytics.services.nfl_drive_weights import _derive_drive_weights

        offense = {
            "epa_per_play": 0.05, "success_rate": 0.47, "avg_cpoe": 1.5,
        }
        opposing = {
            "def_sacks_per_game": 2.5, "def_tfl_per_game": 5.0,
            "def_turnovers_forced_per_game": 1.0,
        }
        weights = _derive_drive_weights(offense, opposing)
        assert len(weights) == 5
        assert abs(sum(weights) - 1.0) < 0.01

    def test_better_offense_more_tds(self):
        from app.analytics.services.nfl_drive_weights import _derive_drive_weights

        good_offense = {
            "epa_per_play": 0.15, "success_rate": 0.55, "avg_cpoe": 3.0,
        }
        bad_offense = {
            "epa_per_play": -0.10, "success_rate": 0.35, "avg_cpoe": -3.0,
        }
        avg_defense = {
            "def_sacks_per_game": 2.5, "def_tfl_per_game": 5.0,
            "def_turnovers_forced_per_game": 1.0,
        }
        good_weights = _derive_drive_weights(good_offense, avg_defense)
        bad_weights = _derive_drive_weights(bad_offense, avg_defense)

        assert good_weights[0] > bad_weights[0]

    def test_strong_defense_more_turnovers(self):
        from app.analytics.services.nfl_drive_weights import _derive_drive_weights

        avg_offense = {"epa_per_play": 0.0, "success_rate": 0.45}
        strong_def = {
            "def_sacks_per_game": 4.0, "def_tfl_per_game": 8.0,
            "def_turnovers_forced_per_game": 2.0,
        }
        weak_def = {
            "def_sacks_per_game": 1.0, "def_tfl_per_game": 3.0,
            "def_turnovers_forced_per_game": 0.5,
        }
        vs_strong = _derive_drive_weights(avg_offense, strong_def)
        vs_weak = _derive_drive_weights(avg_offense, weak_def)

        assert vs_strong[3] > vs_weak[3]

    def test_all_defaults(self):
        from app.analytics.services.nfl_drive_weights import _derive_drive_weights

        weights = _derive_drive_weights({}, {})
        assert len(weights) == 5
        assert all(0 < w < 1 for w in weights)
        assert abs(sum(weights) - 1.0) < 0.01
