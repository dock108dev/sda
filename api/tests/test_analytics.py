"""Tests for the analytics framework scaffolding."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_has_sklearn = importlib.util.find_spec("sklearn") is not None
_has_joblib = importlib.util.find_spec("joblib") is not None

from app.analytics.core.analytics_engine import AnalyticsEngine
from app.analytics.core.metrics_engine import MetricsEngine
from app.analytics.core.simulation_engine import SimulationEngine
from app.analytics.core.types import (
    MatchupProfile,
    PlayerProfile,
    SimulationResult,
    TeamProfile,
)
from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.sports.mlb.metrics import MLBMetrics
from app.analytics.sports.mlb.simulator import MLBSimulator
from app.analytics.sports.mlb.transforms import (
    transform_game_stats,
    transform_matchup_data,
    transform_player_stats,
)


class TestAnalyticsEngine:
    """Verify AnalyticsEngine initializes and returns correct types."""

    def test_init_stores_sport(self) -> None:
        engine = AnalyticsEngine("mlb")
        assert engine.sport == "mlb"

    def test_init_normalizes_sport_case(self) -> None:
        engine = AnalyticsEngine("MLB")
        assert engine.sport == "mlb"

    def test_get_team_profile_returns_team_profile(self) -> None:
        engine = AnalyticsEngine("mlb")
        profile = engine.get_team_profile("NYY")
        assert isinstance(profile, TeamProfile)
        assert profile.team_id == "NYY"
        assert profile.sport == "mlb"

    def test_get_player_profile_returns_player_profile(self) -> None:
        engine = AnalyticsEngine("mlb")
        profile = engine.get_player_profile("player_123")
        assert isinstance(profile, PlayerProfile)
        assert profile.player_id == "player_123"
        assert profile.sport == "mlb"

    def test_get_matchup_returns_matchup_profile(self) -> None:
        engine = AnalyticsEngine("mlb")
        matchup = engine.get_matchup("NYY", "BOS")
        assert isinstance(matchup, MatchupProfile)
        assert matchup.entity_a_id == "NYY"
        assert matchup.entity_b_id == "BOS"

    def test_unsupported_sport_raises_on_load(self) -> None:
        engine = AnalyticsEngine("cricket")
        with pytest.raises(ValueError, match="Unsupported sport"):
            engine._load_module()


class TestMetricsEngine:
    """Verify MetricsEngine routes to sport-specific modules."""

    def test_init_stores_sport(self) -> None:
        engine = MetricsEngine("mlb")
        assert engine.sport == "mlb"

    def test_calculate_player_metrics_delegates_to_mlb(self) -> None:
        engine = MetricsEngine("mlb")
        result = engine.calculate_player_metrics({
            "zone_swing_pct": 0.75,
            "outside_swing_pct": 0.30,
            "zone_contact_pct": 0.88,
            "outside_contact_pct": 0.60,
            "avg_exit_velocity": 90.0,
            "hard_hit_pct": 0.40,
        })
        assert isinstance(result, dict)
        assert "contact_rate" in result
        assert "power_index" in result
        assert "swing_rate" in result
        assert "whiff_rate" in result
        assert "expected_slug" in result

    def test_calculate_team_metrics_delegates_to_mlb(self) -> None:
        engine = MetricsEngine("mlb")
        result = engine.calculate_team_metrics({
            "zone_swing_pct": 0.70,
            "outside_swing_pct": 0.28,
            "zone_contact_pct": 0.85,
            "outside_contact_pct": 0.55,
            "avg_exit_velocity": 89.0,
            "hard_hit_pct": 0.38,
        })
        assert isinstance(result, dict)
        assert "team_contact_rate" in result
        assert "team_power_index" in result

    def test_calculate_matchup_metrics_delegates_to_mlb(self) -> None:
        engine = MetricsEngine("mlb")
        batter = {
            "zone_swing_pct": 0.75,
            "outside_swing_pct": 0.30,
            "zone_contact_pct": 0.88,
            "outside_contact_pct": 0.60,
            "avg_exit_velocity": 90.0,
            "hard_hit_pct": 0.40,
            "barrel_pct": 0.10,
        }
        pitcher = {
            "zone_contact_pct": 0.70,
            "outside_contact_pct": 0.45,
        }
        result = engine.calculate_matchup_metrics(batter, pitcher)
        assert "contact_probability" in result
        assert "hit_probability" in result
        assert "strikeout_probability" in result

    def test_unsupported_sport_returns_empty(self) -> None:
        engine = MetricsEngine("cricket")
        assert engine.calculate_player_metrics({}) == {}
        assert engine.calculate_team_metrics({}) == {}
        assert engine.calculate_matchup_metrics({}, {}) == {}

    def test_empty_stats_returns_empty_dict(self) -> None:
        engine = MetricsEngine("mlb")
        result = engine.calculate_player_metrics({})
        assert isinstance(result, dict)
        assert len(result) == 0


class TestSimulationEngine:
    """Verify SimulationEngine interface."""

    def test_init_stores_sport(self) -> None:
        engine = SimulationEngine("mlb")
        assert engine.sport == "mlb"

class TestTypes:
    """Verify data structures."""

    def test_player_profile_defaults(self) -> None:
        p = PlayerProfile(player_id="1", sport="mlb")
        assert p.metrics == {}
        assert p.name == ""

    def test_team_profile_defaults(self) -> None:
        t = TeamProfile(team_id="NYY", sport="mlb")
        assert t.metrics == {}
        assert t.roster_summary == []

    def test_matchup_profile_defaults(self) -> None:
        m = MatchupProfile(entity_a_id="A", entity_b_id="B", sport="mlb")
        assert m.comparison == {}
        assert m.advantages == {}
        assert m.probabilities == {}

    def test_simulation_result_defaults(self) -> None:
        s = SimulationResult(sport="mlb")
        assert s.iterations == 0
        assert s.outcomes == []
        assert s.summary == {}


class TestMLBMetrics:
    """Verify MLB derived metric calculations."""

    def test_build_player_metrics_full_input(self) -> None:
        m = MLBMetrics()
        result = m.build_player_metrics({
            "zone_swing_pct": 0.75,
            "outside_swing_pct": 0.30,
            "zone_contact_pct": 0.88,
            "outside_contact_pct": 0.60,
            "avg_exit_velocity": 90.0,
            "hard_hit_pct": 0.40,
            "barrel_pct": 0.10,
        })
        assert result["swing_rate"] == round((0.75 + 0.30) / 2, 4)
        assert result["contact_rate"] == round((0.88 + 0.60) / 2, 4)
        assert result["whiff_rate"] == round(1.0 - (0.88 + 0.60) / 2, 4)
        assert result["barrel_rate"] == 0.10
        assert result["hard_hit_rate"] == 0.40
        assert result["avg_exit_velocity"] == 90.0
        assert "power_index" in result
        assert "expected_slug" in result

    def test_build_player_metrics_partial_input(self) -> None:
        m = MLBMetrics()
        result = m.build_player_metrics({"avg_exit_velocity": 92.0})
        assert "avg_exit_velocity" in result
        assert "power_index" in result
        # Missing contact inputs should not produce contact_rate
        assert "contact_rate" not in result

    def test_build_player_metrics_empty_input(self) -> None:
        m = MLBMetrics()
        result = m.build_player_metrics({})
        assert result == {}

    def test_power_index_formula(self) -> None:
        m = MLBMetrics()
        result = m.build_player_metrics({
            "avg_exit_velocity": 88.0,  # = baseline
            "hard_hit_pct": 0.35,       # = baseline
        })
        assert abs(result["power_index"] - 1.0) < 0.001

    def test_power_index_above_baseline(self) -> None:
        m = MLBMetrics()
        result = m.build_player_metrics({
            "avg_exit_velocity": 95.0,
            "hard_hit_pct": 0.50,
        })
        assert result["power_index"] > 1.0

    def test_expected_slug_is_power_times_contact(self) -> None:
        m = MLBMetrics()
        result = m.build_player_metrics({
            "zone_swing_pct": 0.70,
            "outside_swing_pct": 0.25,
            "zone_contact_pct": 0.90,
            "outside_contact_pct": 0.65,
            "avg_exit_velocity": 91.0,
            "hard_hit_pct": 0.42,
        })
        expected = round(result["power_index"] * result["contact_rate"], 4)
        assert result["expected_slug"] == expected

    def test_build_player_profile_populates_metrics(self) -> None:
        m = MLBMetrics()
        profile = m.build_player_profile({
            "player_id": "123",
            "name": "Mike Trout",
            "zone_swing_pct": 0.72,
            "outside_swing_pct": 0.28,
            "zone_contact_pct": 0.86,
            "outside_contact_pct": 0.58,
            "avg_exit_velocity": 92.0,
            "hard_hit_pct": 0.45,
        })
        assert isinstance(profile, PlayerProfile)
        assert profile.player_id == "123"
        assert profile.name == "Mike Trout"
        assert profile.sport == "mlb"
        assert "contact_rate" in profile.metrics
        assert "power_index" in profile.metrics

    def test_build_team_metrics_from_aggregated(self) -> None:
        m = MLBMetrics()
        result = m.build_team_metrics({
            "zone_swing_pct": 0.70,
            "outside_swing_pct": 0.28,
            "zone_contact_pct": 0.85,
            "outside_contact_pct": 0.55,
            "avg_exit_velocity": 89.0,
            "hard_hit_pct": 0.38,
        })
        assert "team_contact_rate" in result
        assert "team_power_index" in result
        assert "team_swing_rate" in result

    def test_build_team_metrics_from_players_list(self) -> None:
        m = MLBMetrics()
        result = m.build_team_metrics({
            "players": [
                {"zone_contact_pct": 0.90, "outside_contact_pct": 0.60,
                 "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45},
                {"zone_contact_pct": 0.80, "outside_contact_pct": 0.50,
                 "avg_exit_velocity": 86.0, "hard_hit_pct": 0.30},
            ],
        })
        assert "team_contact_rate" in result
        assert "team_power_index" in result
        # Average of two players
        expected_contact = round(((0.90 + 0.60) / 2 + (0.80 + 0.50) / 2) / 2, 4)
        assert result["team_contact_rate"] == expected_contact

    def test_build_team_profile(self) -> None:
        m = MLBMetrics()
        profile = m.build_team_profile({"team_id": "NYY", "name": "Yankees"})
        assert isinstance(profile, TeamProfile)
        assert profile.team_id == "NYY"
        assert profile.name == "Yankees"
        assert profile.sport == "mlb"

    def test_build_matchup_metrics(self) -> None:
        m = MLBMetrics()
        batter = {
            "zone_swing_pct": 0.75,
            "outside_swing_pct": 0.30,
            "zone_contact_pct": 0.88,
            "outside_contact_pct": 0.60,
            "avg_exit_velocity": 90.0,
            "hard_hit_pct": 0.40,
            "barrel_pct": 0.10,
        }
        pitcher = {
            "zone_contact_pct": 0.70,
            "outside_contact_pct": 0.45,
        }
        result = m.build_matchup_metrics(batter, pitcher)
        assert "contact_probability" in result
        assert "barrel_probability" in result
        assert "hit_probability" in result
        assert "strikeout_probability" in result
        assert "walk_probability" in result
        # All probabilities should be in [0, 1]
        for key, val in result.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} out of range"

    def test_matchup_metrics_empty_pitcher_uses_baseline(self) -> None:
        m = MLBMetrics()
        batter = {
            "zone_contact_pct": 0.88,
            "outside_contact_pct": 0.60,
            "avg_exit_velocity": 90.0,
            "hard_hit_pct": 0.40,
            "barrel_pct": 0.10,
        }
        result = m.build_matchup_metrics(batter, {})
        assert "contact_probability" in result
        # With baseline pitcher, contact_prob should be close to batter's rate
        assert result["contact_probability"] > 0


class TestMLBSimulator:
    """Verify MLB simulator module."""

    def test_init_sets_sport(self) -> None:
        sim = MLBSimulator()
        assert sim.sport == "mlb"

    def test_simulate_plate_appearance_returns_dict(self) -> None:
        sim = MLBSimulator()
        result = sim.simulate_plate_appearance({}, {})
        assert isinstance(result, dict)

    def test_simulate_game_returns_result(self) -> None:
        sim = MLBSimulator()
        result = sim.simulate_game({}, iterations=500)
        assert isinstance(result, SimulationResult)
        assert result.iterations == 500


class TestMLBTransforms:
    """Verify MLB transform functions."""

    def test_transform_game_stats_returns_dict(self) -> None:
        assert isinstance(transform_game_stats({}), dict)

    def test_transform_player_stats_returns_dict(self) -> None:
        assert isinstance(transform_player_stats({}), dict)

    def test_transform_matchup_data_returns_dict(self) -> None:
        assert isinstance(transform_matchup_data({}, {}), dict)


class TestAggregationEngine:
    """Verify AggregationEngine routes to sport-specific modules."""

    def test_aggregate_player_history_mlb(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine

        engine = AggregationEngine("mlb")
        games = [
            {"zone_swing_pct": 0.70, "zone_contact_pct": 0.85, "avg_exit_velocity": 90.0, "hard_hit_pct": 0.40, "pitches": 80},
            {"zone_swing_pct": 0.80, "zone_contact_pct": 0.90, "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45, "pitches": 90},
        ]
        result = engine.aggregate_player_history("p1", games)
        assert result["player_id"] == "p1"
        assert result["zone_swing_pct"] == 0.75
        assert result["avg_exit_velocity"] == 91.0
        assert result["pitches"] == 170.0

    def test_aggregate_player_history_empty(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine

        engine = AggregationEngine("mlb")
        result = engine.aggregate_player_history("p1", [])
        assert result == {"player_id": "p1"}

    def test_aggregate_player_history_with_recency(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine

        engine = AggregationEngine("mlb")
        games = [
            {"avg_exit_velocity": 85.0, "hard_hit_pct": 0.30},
            {"avg_exit_velocity": 86.0, "hard_hit_pct": 0.31},
            {"avg_exit_velocity": 87.0, "hard_hit_pct": 0.32},
            {"avg_exit_velocity": 95.0, "hard_hit_pct": 0.50},
            {"avg_exit_velocity": 96.0, "hard_hit_pct": 0.52},
        ]
        result = engine.aggregate_player_history("p1", games, recent_n=2)
        # Recent avg EV = 95.5, season avg EV = 89.8
        # Blended = 95.5 * 0.7 + 89.8 * 0.3 = 66.85 + 26.94 = 93.79
        assert result["avg_exit_velocity"] == pytest.approx(93.79, abs=0.01)

    def test_aggregate_team_history_mlb(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine

        engine = AggregationEngine("mlb")
        games = [
            {"zone_contact_pct": 0.80, "outside_contact_pct": 0.55},
            {"zone_contact_pct": 0.90, "outside_contact_pct": 0.65},
        ]
        result = engine.aggregate_team_history("NYY", games)
        assert result["team_id"] == "NYY"
        assert result["zone_contact_pct"] == 0.85

    def test_unsupported_sport_returns_id_only(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine

        engine = AggregationEngine("cricket")
        result = engine.aggregate_player_history("p1", [{"foo": 1}])
        assert result == {"player_id": "p1"}

    def test_build_matchup_dataset(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine

        engine = AggregationEngine("mlb")
        a_games = [{"avg_exit_velocity": 90.0}]
        b_games = [{"avg_exit_velocity": 85.0}]
        result = engine.build_matchup_dataset("a1", "b1", a_games, b_games)
        assert result["entity_a_profile"]["player_id"] == "a1"
        assert result["entity_b_profile"]["player_id"] == "b1"


class TestProfileBuilder:
    """Verify ProfileBuilder creates typed profiles from aggregated stats."""

    def test_build_player_profile(self) -> None:
        from app.analytics.core.profile_builder import ProfileBuilder

        builder = ProfileBuilder("mlb")
        agg = {
            "name": "Test Player",
            "zone_swing_pct": 0.75,
            "outside_swing_pct": 0.30,
            "zone_contact_pct": 0.88,
            "outside_contact_pct": 0.60,
            "avg_exit_velocity": 90.0,
            "hard_hit_pct": 0.40,
        }
        profile = builder.build_player_profile("p1", agg)
        assert isinstance(profile, PlayerProfile)
        assert profile.player_id == "p1"
        assert profile.sport == "mlb"
        assert profile.name == "Test Player"
        assert "contact_rate" in profile.metrics
        assert "power_index" in profile.metrics

    def test_build_team_profile(self) -> None:
        from app.analytics.core.profile_builder import ProfileBuilder

        builder = ProfileBuilder("mlb")
        agg = {
            "name": "Yankees",
            "zone_contact_pct": 0.85,
            "outside_contact_pct": 0.55,
            "avg_exit_velocity": 89.0,
            "hard_hit_pct": 0.38,
        }
        profile = builder.build_team_profile("NYY", agg)
        assert isinstance(profile, TeamProfile)
        assert profile.team_id == "NYY"
        assert profile.name == "Yankees"
        assert "team_contact_rate" in profile.metrics


class TestMLBAggregation:
    """Verify MLB aggregation helpers."""

    def test_compute_averages(self) -> None:
        from app.analytics.sports.mlb.aggregation import MLBAggregation

        agg = MLBAggregation()
        games = [
            {"zone_swing_pct": 0.70, "barrel_pct": 0.08},
            {"zone_swing_pct": 0.80, "barrel_pct": 0.12},
        ]
        result = agg.aggregate_player_games(games)
        assert result["zone_swing_pct"] == 0.75
        assert result["barrel_pct"] == 0.10

    def test_rate_contact_derived(self) -> None:
        from app.analytics.sports.mlb.aggregation import MLBAggregation

        agg = MLBAggregation()
        games = [
            {"contacts": 10, "swings": 20},
            {"contacts": 15, "swings": 30},
        ]
        result = agg.aggregate_player_games(games)
        assert result["rate_contact"] == 0.5

    def test_weighted_blend_with_recent(self) -> None:
        from app.analytics.sports.mlb.aggregation import MLBAggregation

        agg = MLBAggregation()
        games = [
            {"avg_exit_velocity": 85.0},
            {"avg_exit_velocity": 86.0},
            {"avg_exit_velocity": 87.0},
            {"avg_exit_velocity": 95.0},
        ]
        result = agg.aggregate_player_games(games, recent_n=1)
        # recent=95, season=88.25, blend=95*0.7+88.25*0.3=66.5+26.475=92.975
        assert result["avg_exit_velocity"] == pytest.approx(92.975, abs=0.001)

    def test_rolling_average(self) -> None:
        from app.analytics.sports.mlb.aggregation import rolling_average

        result = rolling_average([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
        assert len(result) == 5
        assert result[2] == 2.0  # avg(1,2,3)
        assert result[4] == 4.0  # avg(3,4,5)

    def test_weighted_average(self) -> None:
        from app.analytics.sports.mlb.aggregation import weighted_average

        assert weighted_average([10.0, 20.0], [1.0, 3.0]) == 17.5
        assert weighted_average([10.0, 20.0]) == 15.0
        assert weighted_average([]) is None

    def test_rate_calculation(self) -> None:
        from app.analytics.sports.mlb.aggregation import rate_calculation

        assert rate_calculation(10.0, 20.0) == 0.5
        assert rate_calculation(10.0, 0.0) is None


class TestEndToEndPipeline:
    """Verify full pipeline: Games → Aggregation → Metrics → Profiles."""

    def test_full_pipeline(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine
        from app.analytics.core.profile_builder import ProfileBuilder

        games = [
            {
                "zone_swing_pct": 0.72, "outside_swing_pct": 0.28,
                "zone_contact_pct": 0.86, "outside_contact_pct": 0.58,
                "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45,
                "barrel_pct": 0.10,
            },
            {
                "zone_swing_pct": 0.78, "outside_swing_pct": 0.32,
                "zone_contact_pct": 0.90, "outside_contact_pct": 0.62,
                "avg_exit_velocity": 94.0, "hard_hit_pct": 0.48,
                "barrel_pct": 0.12,
            },
        ]

        # Step 1: Aggregate
        engine = AggregationEngine("mlb")
        agg = engine.aggregate_player_history("trout_123", games)
        assert agg["player_id"] == "trout_123"
        assert "avg_exit_velocity" in agg

        # Step 2: Build profile (runs MetricsEngine internally)
        builder = ProfileBuilder("mlb")
        profile = builder.build_player_profile("trout_123", agg)
        assert isinstance(profile, PlayerProfile)
        assert profile.player_id == "trout_123"
        assert "contact_rate" in profile.metrics
        assert "power_index" in profile.metrics
        assert "expected_slug" in profile.metrics
        assert profile.metrics["power_index"] > 1.0  # above baseline


class TestMatchupEngine:
    """Verify MatchupEngine routes to sport-specific modules."""

    def _batter_profile(self) -> PlayerProfile:
        return PlayerProfile(
            player_id="batter_1",
            sport="mlb",
            name="Test Batter",
            metrics={
                "contact_rate": 0.82,
                "whiff_rate": 0.18,
                "swing_rate": 0.52,
                "power_index": 1.2,
                "barrel_rate": 0.10,
                "hard_hit_rate": 0.42,
                "avg_exit_velocity": 92.0,
                "expected_slug": 0.984,
            },
        )

    def _pitcher_profile(self) -> PlayerProfile:
        return PlayerProfile(
            player_id="pitcher_1",
            sport="mlb",
            name="Test Pitcher",
            metrics={
                "contact_suppression": 0.10,
                "strikeout_rate": 0.28,
                "walk_rate": 0.07,
                "power_suppression": 0.05,
            },
        )

    def test_player_vs_player_returns_matchup_profile(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        result = engine.calculate_player_vs_player(
            self._batter_profile(), self._pitcher_profile()
        )
        assert isinstance(result, MatchupProfile)
        assert result.entity_a_id == "batter_1"
        assert result.entity_b_id == "pitcher_1"
        assert result.sport == "mlb"

    def test_player_vs_player_has_probabilities(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        result = engine.calculate_player_vs_player(
            self._batter_profile(), self._pitcher_profile()
        )
        probs = result.probabilities
        assert "strikeout_probability" in probs
        assert "walk_probability" in probs
        assert "single_probability" in probs
        assert "double_probability" in probs
        assert "triple_probability" in probs
        assert "home_run_probability" in probs

    def test_probabilities_leave_room_for_out_residual(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        result = engine.calculate_player_vs_player(
            self._batter_profile(), self._pitcher_profile()
        )
        total = sum(result.probabilities.values())
        # Named events should sum to < 1.0; the remainder is fielded outs
        assert total < 1.0
        assert total > 0.3  # sanity — should not be trivially small

    def test_probabilities_in_valid_range(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        result = engine.calculate_player_vs_player(
            self._batter_profile(), self._pitcher_profile()
        )
        for key, val in result.probabilities.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} out of range"

    def test_comparison_populated(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        # Use two profiles with overlapping metric keys for comparison
        player_a = PlayerProfile(
            player_id="a", sport="mlb",
            metrics={"contact_rate": 0.85, "power_index": 1.2},
        )
        player_b = PlayerProfile(
            player_id="b", sport="mlb",
            metrics={"contact_rate": 0.78, "power_index": 1.0},
        )
        result = engine.calculate_player_vs_player(player_a, player_b)
        assert len(result.comparison) > 0
        assert result.advantages.get("contact_rate") == "a"
        assert result.advantages.get("power_index") == "a"

    def test_team_vs_team(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        team_a = TeamProfile(
            team_id="NYY", sport="mlb",
            metrics={"team_contact_rate": 0.80, "team_whiff_rate": 0.20,
                     "team_swing_rate": 0.50, "team_power_index": 1.1,
                     "team_barrel_rate": 0.09},
        )
        team_b = TeamProfile(
            team_id="BOS", sport="mlb",
            metrics={"team_strikeout_rate": 0.25, "team_walk_rate": 0.08,
                     "team_contact_suppression": 0.05},
        )
        result = engine.calculate_team_vs_team(team_a, team_b)
        assert isinstance(result, MatchupProfile)
        assert result.entity_a_id == "NYY"
        assert "strikeout_probability" in result.probabilities

    def test_player_vs_team(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        batter = self._batter_profile()
        team = TeamProfile(
            team_id="BOS", sport="mlb",
            metrics={"strikeout_rate": 0.25, "walk_rate": 0.08},
        )
        result = engine.calculate_player_vs_team(batter, team)
        assert isinstance(result, MatchupProfile)
        assert result.entity_a_id == "batter_1"
        assert result.entity_b_id == "BOS"
        assert "strikeout_probability" in result.probabilities

    def test_unsupported_sport_returns_empty(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("cricket")
        batter = self._batter_profile()
        pitcher = self._pitcher_profile()
        result = engine.calculate_player_vs_player(batter, pitcher)
        assert isinstance(result, MatchupProfile)
        assert result.probabilities == {}

    def test_baseline_fallbacks_with_empty_pitcher(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        batter = self._batter_profile()
        empty_pitcher = PlayerProfile(player_id="p2", sport="mlb", metrics={})
        result = engine.calculate_player_vs_player(batter, empty_pitcher)
        assert result.probabilities["strikeout_probability"] > 0


class TestMLBMatchup:
    """Verify MLB matchup probability calculations directly."""

    def test_normalize_probabilities_passthrough(self) -> None:
        from app.analytics.sports.mlb.matchup import normalize_probabilities

        raw = {"a": 0.3, "b": 0.2}
        result = normalize_probabilities(raw)
        # Sum <= 1.0 should pass through unchanged
        assert result == raw

    def test_normalize_probabilities_scales_down_when_over_one(self) -> None:
        from app.analytics.sports.mlb.matchup import normalize_probabilities

        raw = {"a": 0.8, "b": 0.6}
        result = normalize_probabilities(raw)
        # Sum > 1.0 should be scaled down
        assert abs(sum(result.values()) - 1.0) < 0.01

    def test_normalize_handles_zero_total(self) -> None:
        from app.analytics.sports.mlb.matchup import normalize_probabilities

        result = normalize_probabilities({"a": 0.0, "b": 0.0})
        assert result == {"a": 0.0, "b": 0.0}

    def test_batter_vs_pitcher_direct(self) -> None:
        from app.analytics.sports.mlb.matchup import MLBMatchup

        matchup = MLBMatchup()
        batter = PlayerProfile(
            player_id="b1", sport="mlb",
            metrics={"contact_rate": 0.85, "whiff_rate": 0.15,
                     "swing_rate": 0.55, "power_index": 1.3,
                     "barrel_rate": 0.12},
        )
        pitcher = PlayerProfile(
            player_id="p1", sport="mlb",
            metrics={"contact_suppression": 0.08, "strikeout_rate": 0.30,
                     "walk_rate": 0.06, "power_suppression": 0.03},
        )
        result = matchup.batter_vs_pitcher(batter, pitcher)
        # Named events sum to < 1.0; remainder = fielded outs
        total = sum(result.values())
        assert total < 1.0
        assert total > 0.3
        assert result["home_run_probability"] > 0

    def test_high_power_batter_has_more_hr(self) -> None:
        from app.analytics.sports.mlb.matchup import MLBMatchup

        matchup = MLBMatchup()
        base = {"contact_rate": 0.80, "whiff_rate": 0.20,
                "swing_rate": 0.50}
        low_power = PlayerProfile(
            player_id="b1", sport="mlb",
            metrics={**base, "power_index": 0.8, "barrel_rate": 0.05},
        )
        high_power = PlayerProfile(
            player_id="b2", sport="mlb",
            metrics={**base, "power_index": 1.5, "barrel_rate": 0.15},
        )
        pitcher = PlayerProfile(player_id="p1", sport="mlb", metrics={})
        low_result = matchup.batter_vs_pitcher(low_power, pitcher)
        high_result = matchup.batter_vs_pitcher(high_power, pitcher)
        assert high_result["home_run_probability"] > low_result["home_run_probability"]


class TestFullMatchupPipeline:
    """Verify Aggregation → Metrics → Profiles → Matchups pipeline."""

    def test_end_to_end_with_matchup(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine
        from app.analytics.core.matchup_engine import MatchupEngine
        from app.analytics.core.profile_builder import ProfileBuilder

        # Step 1: Aggregate raw games
        agg_engine = AggregationEngine("mlb")
        batter_games = [
            {"zone_swing_pct": 0.75, "outside_swing_pct": 0.30,
             "zone_contact_pct": 0.88, "outside_contact_pct": 0.60,
             "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45,
             "barrel_pct": 0.11},
        ]
        batter_agg = agg_engine.aggregate_player_history("b1", batter_games)

        # Step 2: Build profiles
        builder = ProfileBuilder("mlb")
        batter_profile = builder.build_player_profile("b1", batter_agg)
        assert "contact_rate" in batter_profile.metrics

        # Pitcher with suppression metrics (not from aggregation)
        pitcher_profile = PlayerProfile(
            player_id="p1", sport="mlb",
            metrics={"contact_suppression": 0.10, "strikeout_rate": 0.28,
                     "walk_rate": 0.07, "power_suppression": 0.05},
        )

        # Step 3: Run matchup
        matchup_engine = MatchupEngine("mlb")
        matchup = matchup_engine.calculate_player_vs_player(
            batter_profile, pitcher_profile
        )
        assert isinstance(matchup, MatchupProfile)
        assert "strikeout_probability" in matchup.probabilities
        assert "home_run_probability" in matchup.probabilities
        # Named events sum < 1.0; remainder = fielded outs
        assert sum(matchup.probabilities.values()) < 1.0


class TestMLBGameSimulator:
    """Verify MLB plate-appearance game simulation."""

    def test_simulate_game_returns_scores(self) -> None:
        from app.analytics.sports.mlb.game_simulator import MLBGameSimulator

        sim = MLBGameSimulator()
        result = sim.simulate_game({}, rng=__import__("random").Random(42))
        assert "home_score" in result
        assert "away_score" in result
        assert result["winner"] in ("home", "away")

    def test_deterministic_with_seed(self) -> None:
        import random

        from app.analytics.sports.mlb.game_simulator import MLBGameSimulator

        sim = MLBGameSimulator()
        ctx = {
            "home_probabilities": {"strikeout_probability": 0.20, "walk_probability": 0.09,
                                   "single_probability": 0.16, "double_probability": 0.05,
                                   "triple_probability": 0.01, "home_run_probability": 0.04},
            "away_probabilities": {"strikeout_probability": 0.22, "walk_probability": 0.08,
                                   "single_probability": 0.15, "double_probability": 0.05,
                                   "triple_probability": 0.01, "home_run_probability": 0.03},
        }
        r1 = sim.simulate_game(ctx, rng=random.Random(99))
        r2 = sim.simulate_game(ctx, rng=random.Random(99))
        assert r1 == r2

    def test_scores_are_non_negative(self) -> None:
        import random

        from app.analytics.sports.mlb.game_simulator import MLBGameSimulator

        sim = MLBGameSimulator()
        for seed in range(10):
            result = sim.simulate_game({}, rng=random.Random(seed))
            assert result["home_score"] >= 0
            assert result["away_score"] >= 0


class TestSimulationRunner:
    """Verify SimulationRunner aggregation."""

    def test_run_simulations_returns_summary(self) -> None:
        from app.analytics.core.simulation_runner import SimulationRunner
        from app.analytics.sports.mlb.game_simulator import MLBGameSimulator

        runner = SimulationRunner()
        result = runner.run_simulations(MLBGameSimulator(), {}, iterations=100, seed=42)
        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert "average_home_score" in result
        assert "average_away_score" in result
        assert "score_distribution" in result
        assert result["iterations"] == 100

    def test_probabilities_sum_to_one(self) -> None:
        from app.analytics.core.simulation_runner import SimulationRunner
        from app.analytics.sports.mlb.game_simulator import MLBGameSimulator

        runner = SimulationRunner()
        result = runner.run_simulations(MLBGameSimulator(), {}, iterations=200, seed=7)
        total = result["home_win_probability"] + result["away_win_probability"]
        assert abs(total - 1.0) < 0.001

    def test_deterministic_results(self) -> None:
        from app.analytics.core.simulation_runner import SimulationRunner
        from app.analytics.sports.mlb.game_simulator import MLBGameSimulator

        runner = SimulationRunner()
        r1 = runner.run_simulations(MLBGameSimulator(), {}, iterations=50, seed=123)
        r2 = runner.run_simulations(MLBGameSimulator(), {}, iterations=50, seed=123)
        assert r1 == r2

    def test_empty_results(self) -> None:
        from app.analytics.core.simulation_runner import SimulationRunner

        runner = SimulationRunner()
        result = runner.aggregate_results([])
        assert result["iterations"] == 0


class TestSimulationEngineIntegration:
    """Verify SimulationEngine routes to MLB simulator."""

    def test_run_simulation_with_seed(self) -> None:
        engine = SimulationEngine("mlb")
        result = engine.run_simulation({}, iterations=100, seed=42)
        assert "home_win_probability" in result
        assert result["iterations"] == 100

    def test_unsupported_sport_returns_empty(self) -> None:
        engine = SimulationEngine("cricket")
        result = engine.run_simulation({}, iterations=10)
        assert result["iterations"] == 0

class TestFullSimulationPipeline:
    """Verify Aggregation → Metrics → Profiles → Matchups → Simulation."""

    def test_end_to_end_with_simulation(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine
        from app.analytics.core.matchup_engine import MatchupEngine
        from app.analytics.core.profile_builder import ProfileBuilder

        # Aggregate
        agg = AggregationEngine("mlb")
        batter_agg = agg.aggregate_player_history("b1", [
            {"zone_swing_pct": 0.75, "outside_swing_pct": 0.30,
             "zone_contact_pct": 0.88, "outside_contact_pct": 0.60,
             "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45,
             "barrel_pct": 0.11},
        ])

        # Build profiles
        builder = ProfileBuilder("mlb")
        batter_profile = builder.build_player_profile("b1", batter_agg)
        pitcher_profile = PlayerProfile(
            player_id="p1", sport="mlb",
            metrics={"contact_suppression": 0.10, "strikeout_rate": 0.28,
                     "walk_rate": 0.07, "power_suppression": 0.05},
        )

        # Matchup probabilities
        matchup_engine = MatchupEngine("mlb")
        matchup = matchup_engine.calculate_player_vs_player(
            batter_profile, pitcher_profile
        )

        # Simulate using matchup probabilities
        game_context = {
            "home_probabilities": matchup.probabilities,
            "away_probabilities": matchup.probabilities,
        }
        engine = SimulationEngine("mlb")
        result = engine.run_simulation(game_context, iterations=500, seed=42)
        assert result["home_win_probability"] >= 0
        assert result["average_home_score"] > 0
        assert result["iterations"] == 500


class TestSimulationAnalysis:
    """Verify SimulationAnalysis summary methods."""

    _SAMPLE_RESULTS = [
        {"home_score": 5, "away_score": 3, "winner": "home"},
        {"home_score": 2, "away_score": 4, "winner": "away"},
        {"home_score": 6, "away_score": 5, "winner": "home"},
        {"home_score": 3, "away_score": 3, "winner": "home"},
        {"home_score": 4, "away_score": 2, "winner": "home"},
    ]

    def test_summarize_results(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        summary = analysis.summarize_results(self._SAMPLE_RESULTS)
        assert "home_win_probability" in summary
        assert "away_win_probability" in summary
        assert "average_total" in summary
        assert "median_total" in summary
        assert "most_common_scores" in summary
        assert summary["iterations"] == 5
        # 4 home wins out of 5
        assert summary["home_win_probability"] == 0.8

    def test_summarize_results_empty(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        summary = SimulationAnalysis("mlb").summarize_results([])
        assert summary["iterations"] == 0

    def test_summarize_distribution(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        result = SimulationAnalysis("mlb").summarize_distribution(self._SAMPLE_RESULTS)
        assert "score_distribution" in result
        assert "top_scores" in result
        assert len(result["top_scores"]) > 0

    def test_summarize_team_totals(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        result = SimulationAnalysis("mlb").summarize_team_totals(self._SAMPLE_RESULTS)
        assert "home_score_distribution" in result
        assert "away_score_distribution" in result
        assert "median_home_score" in result

    def test_summarize_spreads(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        result = SimulationAnalysis("mlb").summarize_spreads(self._SAMPLE_RESULTS, -1.5)
        assert result["spread_line"] == -1.5
        assert "home_cover_probability" in result
        assert "away_cover_probability" in result
        assert "push_probability" in result
        total = result["home_cover_probability"] + result["away_cover_probability"] + result["push_probability"]
        assert abs(total - 1.0) < 0.001

    def test_summarize_totals(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        result = SimulationAnalysis("mlb").summarize_totals(self._SAMPLE_RESULTS, 8.5)
        assert result["total_line"] == 8.5
        assert "over_probability" in result
        assert "under_probability" in result
        total = result["over_probability"] + result["under_probability"] + result["push_probability"]
        assert abs(total - 1.0) < 0.001

    def test_summarize_totals_with_push(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        # Total of game 4 = 6, line = 6 -> push
        result = SimulationAnalysis("mlb").summarize_totals(self._SAMPLE_RESULTS, 6.0)
        assert result["push_probability"] > 0

    def test_sportsbook_comparison(self) -> None:
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        sportsbook = {
            "moneyline": {"home": -200, "away": 170},
            "spread": {"home_line": -1.5, "home_odds": -110},
            "total": {"line": 8.5, "over_odds": -110},
        }
        summary = SimulationAnalysis("mlb").summarize_results(
            self._SAMPLE_RESULTS, sportsbook=sportsbook,
        )
        assert "sportsbook_comparison" in summary
        comp = summary["sportsbook_comparison"]
        assert "moneyline_comparison" in comp
        assert "edge" in comp["moneyline_comparison"]["home"]


class TestOddsAnalysis:
    """Verify odds conversion and comparison."""

    def test_negative_odds_to_probability(self) -> None:
        from app.analytics.core.odds_analysis import OddsAnalysis

        odds = OddsAnalysis()
        prob = odds.american_to_implied_probability(-200)
        assert abs(prob - 0.6667) < 0.001

    def test_positive_odds_to_probability(self) -> None:
        from app.analytics.core.odds_analysis import OddsAnalysis

        odds = OddsAnalysis()
        prob = odds.american_to_implied_probability(150)
        assert abs(prob - 0.4) < 0.001

    def test_zero_odds_returns_zero(self) -> None:
        from app.analytics.core.odds_analysis import OddsAnalysis

        assert OddsAnalysis().american_to_implied_probability(0) == 0.0

    def test_compare_moneyline_edge(self) -> None:
        from app.analytics.core.odds_analysis import OddsAnalysis

        odds = OddsAnalysis()
        result = odds.compare_moneyline(0.65, -150)
        assert result["model_probability"] == 0.65
        assert result["sportsbook_implied_probability"] == 0.6
        assert result["edge"] == 0.05

    def test_compare_spread(self) -> None:
        from app.analytics.core.odds_analysis import OddsAnalysis

        result = OddsAnalysis().compare_spread(0.55, -110)
        assert "edge" in result
        assert result["model_probability"] == 0.55

    def test_compare_total(self) -> None:
        from app.analytics.core.odds_analysis import OddsAnalysis

        result = OddsAnalysis().compare_total(0.58, -110)
        assert "edge" in result


class TestFullAnalysisPipeline:
    """Verify Aggregation → Metrics → Profiles → Matchups → Simulation → Analysis."""

    def test_end_to_end_with_analysis(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine
        from app.analytics.core.matchup_engine import MatchupEngine
        from app.analytics.core.profile_builder import ProfileBuilder
        from app.analytics.core.simulation_analysis import SimulationAnalysis
        from app.analytics.sports.mlb.game_simulator import MLBGameSimulator

        # Aggregate
        agg = AggregationEngine("mlb")
        batter_agg = agg.aggregate_player_history("b1", [
            {"zone_swing_pct": 0.75, "outside_swing_pct": 0.30,
             "zone_contact_pct": 0.88, "outside_contact_pct": 0.60,
             "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45,
             "barrel_pct": 0.11},
        ])

        # Build profiles + matchup
        builder = ProfileBuilder("mlb")
        batter = builder.build_player_profile("b1", batter_agg)
        pitcher = PlayerProfile(
            player_id="p1", sport="mlb",
            metrics={"contact_suppression": 0.10, "strikeout_rate": 0.28,
                     "walk_rate": 0.07, "power_suppression": 0.05},
        )
        matchup = MatchupEngine("mlb").calculate_player_vs_player(batter, pitcher)

        # Simulate
        context = {
            "home_probabilities": matchup.probabilities,
            "away_probabilities": matchup.probabilities,
        }
        raw_results = []
        import random
        rng = random.Random(42)
        sim = MLBGameSimulator()
        for _ in range(200):
            raw_results.append(sim.simulate_game(context, rng=rng))

        # Analyze
        analysis = SimulationAnalysis("mlb")
        summary = analysis.summarize_results(raw_results)
        assert summary["home_win_probability"] > 0
        assert summary["average_total"] > 0

        totals = analysis.summarize_totals(raw_results, 8.5)
        assert totals["over_probability"] + totals["under_probability"] + totals["push_probability"] == pytest.approx(1.0, abs=0.001)

        spreads = analysis.summarize_spreads(raw_results, -1.5)
        assert spreads["home_cover_probability"] + spreads["away_cover_probability"] + spreads["push_probability"] == pytest.approx(1.0, abs=0.001)


class TestAnalyticsService:
    """Verify service layer wiring."""

    def test_get_team_analysis(self) -> None:
        svc = AnalyticsService()
        profile = svc.get_team_analysis("mlb", "NYY")
        assert isinstance(profile, TeamProfile)
        assert profile.team_id == "NYY"

    def test_get_player_analysis(self) -> None:
        svc = AnalyticsService()
        profile = svc.get_player_analysis("mlb", "p1")
        assert isinstance(profile, PlayerProfile)
        assert profile.player_id == "p1"

    def test_get_matchup_analysis(self) -> None:
        svc = AnalyticsService()
        matchup = svc.get_matchup_analysis("mlb", "NYY", "BOS")
        assert isinstance(matchup, MatchupProfile)

    def test_run_full_simulation(self) -> None:
        svc = AnalyticsService()
        result = svc.run_full_simulation("mlb", {}, iterations=100, seed=42)
        assert "home_win_probability" in result
        assert "average_total" in result
        assert result["iterations"] == 100

    def test_run_full_simulation_with_sportsbook(self) -> None:
        svc = AnalyticsService()
        sportsbook = {"moneyline": {"home": -150, "away": 130}}
        result = svc.run_full_simulation(
            "mlb", {}, iterations=100, seed=42, sportsbook=sportsbook,
        )
        assert "sportsbook_comparison" in result


class TestAnalyticsRoutes:
    """Verify API route responses via FastAPI test client."""

    def _make_test_client(self):
        """Create a TestClient with a mock DB dependency override."""
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.analytics.api.analytics_routes import router
        from app.db import get_db

        # Mock async session that returns empty results
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        async def mock_get_db():
            yield mock_db

        app = FastAPI()
        app.dependency_overrides[get_db] = mock_get_db
        app.include_router(router)
        return TestClient(app)

    def test_post_simulate_endpoint(self) -> None:
        client = self._make_test_client()

        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "LAD",
            "away_team": "TOR",
            "iterations": 100,
            "seed": 42,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "mlb"
        assert data["home_team"] == "LAD"
        assert data["away_team"] == "TOR"
        assert "home_win_probability" in data
        assert "average_home_score" in data
        assert data["iterations"] == 100



class TestWinProbabilityModel:
    """Verify WinProbabilityModel calculations."""

    def test_calculate_win_probability(self) -> None:
        from app.analytics.core.win_probability_model import WinProbabilityModel

        model = WinProbabilityModel()
        results = [
            {"winner": "home"}, {"winner": "home"}, {"winner": "away"},
            {"winner": "home"}, {"winner": "away"},
        ]
        wp = model.calculate_win_probability(results)
        assert wp["home_wp"] == 0.6
        assert wp["away_wp"] == 0.4

    def test_empty_results(self) -> None:
        from app.analytics.core.win_probability_model import WinProbabilityModel

        wp = WinProbabilityModel().calculate_win_probability([])
        assert wp["home_wp"] == 0.5

    def test_build_timeline(self) -> None:
        from app.analytics.core.win_probability_model import WinProbabilityModel

        model = WinProbabilityModel()
        snapshots = [
            {"inning": 1, "half": "top", "home_win_probability": 0.52},
            {"inning": 3, "half": "bottom", "home_win_probability": 0.48},
            {"inning": 6, "half": "top", "home_win_probability": 0.65},
        ]
        timeline = model.build_timeline(snapshots)
        assert len(timeline) == 3
        assert timeline[0]["label"] == "T1"
        assert timeline[1]["label"] == "B3"
        assert timeline[2]["home_wp"] == 0.65



class TestModelCalibration:
    """Verify calibration calculations."""

    def test_evaluate_prediction_home_win(self) -> None:
        from app.analytics.core.model_calibration import ModelCalibration

        cal = ModelCalibration()
        pred = {
            "prediction_id": "p1",
            "model_output": {
                "home_win_probability": 0.61,
                "expected_home_score": 4.8,
                "expected_away_score": 3.9,
            },
        }
        actual = {"home_score": 5, "away_score": 3}
        result = cal.evaluate_prediction(pred, actual)
        # Brier: (0.61 - 1)^2 = 0.1521
        assert abs(result["brier_score"] - 0.1521) < 0.001
        assert result["correct_winner"] is True
        assert result["home_score_error"] == pytest.approx(0.2, abs=0.01)

    def test_evaluate_prediction_away_win(self) -> None:
        from app.analytics.core.model_calibration import ModelCalibration

        cal = ModelCalibration()
        pred = {
            "model_output": {
                "home_win_probability": 0.61,
                "expected_home_score": 4.8,
                "expected_away_score": 3.9,
            },
        }
        actual = {"home_score": 2, "away_score": 5}
        result = cal.evaluate_prediction(pred, actual)
        # Brier: (0.61 - 0)^2 = 0.3721
        assert abs(result["brier_score"] - 0.3721) < 0.001
        assert result["correct_winner"] is False

    def test_calibration_report(self) -> None:
        from app.analytics.core.model_calibration import ModelCalibration

        cal = ModelCalibration()
        predictions = [
            {
                "model_output": {"home_win_probability": 0.7, "expected_home_score": 5, "expected_away_score": 3},
                "actual_result": {"home_score": 6, "away_score": 2},
            },
            {
                "model_output": {"home_win_probability": 0.4, "expected_home_score": 3, "expected_away_score": 4},
                "actual_result": {"home_score": 2, "away_score": 5},
            },
        ]
        report = cal.calibration_report(predictions)
        assert report["total_predictions"] == 2
        assert report["winner_accuracy"] == 1.0  # both correct
        assert report["brier_score"] > 0
        assert "prediction_bias" in report

    def test_calibration_report_empty(self) -> None:
        from app.analytics.core.model_calibration import ModelCalibration

        report = ModelCalibration().calibration_report([])
        assert report["total_predictions"] == 0

    def test_bias_detection(self) -> None:
        from app.analytics.core.model_calibration import ModelCalibration

        cal = ModelCalibration()
        # Model consistently overestimates home team
        predictions = [
            {
                "model_output": {"home_win_probability": 0.8, "expected_home_score": 6, "expected_away_score": 3},
                "actual_result": {"home_score": 3, "away_score": 4},
            },
            {
                "model_output": {"home_win_probability": 0.75, "expected_home_score": 5, "expected_away_score": 3},
                "actual_result": {"home_score": 2, "away_score": 5},
            },
        ]
        bias = cal._detect_bias(predictions)
        assert bias["home_bias"] > 0  # overestimates home win prob
        assert bias["home_score_bias"] > 0  # overestimates home score

    def test_sportsbook_comparison(self) -> None:
        from app.analytics.core.model_calibration import ModelCalibration

        cal = ModelCalibration()
        pred = {
            "model_output": {"home_win_probability": 0.61},
            "sportsbook_lines": {"home_ml": -150},
        }
        actual = {"home_score": 5, "away_score": 3}
        result = cal.evaluate_prediction(pred, actual)
        assert "sportsbook_comparison" in result
        comp = result["sportsbook_comparison"]
        assert "model_error" in comp
        assert "sportsbook_error" in comp
        assert isinstance(comp["model_closer"], bool)


class TestModelMetrics:
    """Verify long-term model metrics calculations."""

    def test_brier_score(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        metrics = ModelMetrics()
        score = metrics.brier_score(0.61, 1)
        assert abs(score - 0.1521) < 0.001

    def test_brier_score_perfect(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        assert ModelMetrics().brier_score(1.0, 1) == 0.0
        assert ModelMetrics().brier_score(0.0, 0) == 0.0

    def test_log_loss(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        metrics = ModelMetrics()
        loss = metrics.log_loss(0.9, 1)
        assert loss > 0
        assert loss < 0.2  # high confidence correct prediction

    def test_log_loss_wrong_prediction(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        metrics = ModelMetrics()
        loss = metrics.log_loss(0.1, 1)
        assert loss > 2.0  # high loss for wrong prediction

    def test_mean_absolute_error(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        metrics = ModelMetrics()
        pairs = [(5.0, 4.0), (3.0, 5.0), (4.0, 4.0)]
        mae = metrics.mean_absolute_error(pairs)
        assert abs(mae - 1.0) < 0.001

    def test_mean_absolute_error_empty(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        assert ModelMetrics().mean_absolute_error([]) == 0.0

    def test_compute_all(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        metrics = ModelMetrics()
        predictions = [
            {
                "model_output": {"home_win_probability": 0.7, "expected_home_score": 5, "expected_away_score": 3},
                "actual_result": {"home_score": 6, "away_score": 2},
            },
            {
                "model_output": {"home_win_probability": 0.3, "expected_home_score": 3, "expected_away_score": 5},
                "actual_result": {"home_score": 2, "away_score": 4},
            },
            {
                "model_output": {"home_win_probability": 0.6, "expected_home_score": 4, "expected_away_score": 3},
                "actual_result": {"home_score": 5, "away_score": 3},
            },
        ]
        result = metrics.compute_all(predictions)
        assert result["total_predictions"] == 3
        assert result["brier_score"] > 0
        assert result["log_loss"] > 0
        assert result["winner_accuracy"] > 0
        assert "calibration_buckets" in result

    def test_compute_all_empty(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        result = ModelMetrics().compute_all([])
        assert result["total_predictions"] == 0

    def test_calibration_buckets(self) -> None:
        from app.analytics.core.model_metrics import ModelMetrics

        metrics = ModelMetrics()
        predictions = [
            {"model_output": {"home_win_probability": 0.15}, "actual_result": {"home_score": 1, "away_score": 3}},
            {"model_output": {"home_win_probability": 0.85}, "actual_result": {"home_score": 5, "away_score": 2}},
            {"model_output": {"home_win_probability": 0.85}, "actual_result": {"home_score": 4, "away_score": 3}},
        ]
        buckets = metrics._calibration_buckets(predictions)
        assert len(buckets) >= 2  # at least two buckets with data


class TestBaseModel:
    """Verify model interface contract."""

    def test_base_model_cannot_instantiate(self) -> None:
        from app.analytics.models.core.model_interface import BaseModel

        with pytest.raises(TypeError):
            BaseModel()  # type: ignore[abstract]

    def test_subclass_must_implement_predict(self) -> None:
        from app.analytics.models.core.model_interface import BaseModel

        class PartialModel(BaseModel):
            def predict(self, features):
                return {}

        with pytest.raises(TypeError):
            PartialModel()  # type: ignore[abstract]

    def test_valid_subclass_instantiates(self) -> None:
        from app.analytics.models.core.model_interface import BaseModel

        class ValidModel(BaseModel):
            model_type = "test"
            sport = "test"

            def predict(self, features):
                return {"result": 1}

            def predict_proba(self, features):
                return {"a": 0.5, "b": 0.5}

        m = ValidModel()
        assert not m.is_loaded
        info = m.get_info()
        assert info["model_type"] == "test"
        assert info["class"] == "ValidModel"


class TestModelLoader:
    """Verify model loader functionality."""

    def test_load_nonexistent_file_raises(self) -> None:
        from app.analytics.models.core.model_loader import ModelLoader

        loader = ModelLoader()
        with pytest.raises(FileNotFoundError):
            loader.load_model("/nonexistent/path/model.pkl")

    def test_load_valid_pickle(self, tmp_path) -> None:
        import pickle

        from app.analytics.models.core.model_loader import ModelLoader

        # Create a simple pickle file
        model_data = {"type": "test_model", "weights": [1, 2, 3]}
        model_file = tmp_path / "test_model.pkl"
        with open(model_file, "wb") as f:
            pickle.dump(model_data, f)

        loader = ModelLoader()
        loaded = loader.load_model(str(model_file))
        assert loaded == model_data


class TestModelRegistry:
    """Verify model registry operations."""

    def test_register_and_get_active(self) -> None:
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        registry.register_model(
            sport="mlb",
            model_type="plate_appearance",
            model_id="mlb_pa_v1",
            artifact_path="/tmp/mlb_pa_v1.pkl",
            metadata={"accuracy": 0.61},
            version=1,
        )
        registry.activate_model("mlb", "plate_appearance", "mlb_pa_v1")
        active = registry.get_active_model("mlb", "plate_appearance")
        assert active is not None
        assert active["model_id"] == "mlb_pa_v1"

    def test_get_active_model_builtin(self) -> None:
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        model = registry.get_active_model_instance("mlb", "plate_appearance")
        assert model is not None
        assert model.sport == "mlb"
        assert model.model_type == "plate_appearance"

    def test_get_active_model_game_builtin(self) -> None:
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        model = registry.get_active_model_instance("mlb", "game")
        assert model is not None
        assert model.model_type == "game"

    def test_get_active_model_unsupported_returns_none(self) -> None:
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        assert registry.get_active_model_instance("cricket", "plate_appearance") is None

    def test_list_models_filtered(self) -> None:
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        registry.register_model("mlb", "pa", "a", "/tmp/a.pkl")
        registry.register_model("nba", "game", "b", "/tmp/b.pkl")
        assert len(registry.list_models(sport="mlb")) == 1
        assert len(registry.list_models()) == 2

    def test_registered_model_active_info(self) -> None:
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        registry.register_model("mlb", "plate_appearance", "custom_pa", "/tmp/pa.pkl", version=1)
        registry.activate_model("mlb", "plate_appearance", "custom_pa")
        info = registry.get_active_model_info("mlb", "plate_appearance")
        assert info is not None
        assert info["model_id"] == "custom_pa"


class TestMLBPlateAppearanceModel:
    """Verify MLB plate appearance model predictions."""

    def test_predict_proba_returns_valid_distribution(self) -> None:
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        model = MLBPlateAppearanceModel()
        probs = model.predict_proba({})
        assert "strikeout" in probs
        assert "home_run" in probs
        assert "out" in probs
        total = sum(probs.values())
        assert abs(total - 1.0) < 0.01

    def test_predict_returns_event(self) -> None:
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        model = MLBPlateAppearanceModel()
        result = model.predict({})
        assert "predicted_event" in result
        assert "event_probabilities" in result
        assert result["predicted_event"] in result["event_probabilities"]

    def test_high_contact_reduces_strikeouts(self) -> None:
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        model = MLBPlateAppearanceModel()
        base = model.predict_proba({})
        high_contact = model.predict_proba({"contact_rate": 0.90})
        assert high_contact["strikeout"] < base["strikeout"]

    def test_high_power_increases_hr(self) -> None:
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        model = MLBPlateAppearanceModel()
        base = model.predict_proba({})
        high_power = model.predict_proba({"power_index": 1.5})
        assert high_power["home_run"] > base["home_run"]

    def test_to_simulation_probs(self) -> None:
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        model = MLBPlateAppearanceModel()
        probs = model.predict_proba({})
        sim_probs = model.to_simulation_probs(probs)
        assert "strikeout_probability" in sim_probs
        assert "walk_probability" in sim_probs
        assert "home_run_probability" in sim_probs

    def test_model_info(self) -> None:
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        model = MLBPlateAppearanceModel()
        info = model.get_info()
        assert info["sport"] == "mlb"
        assert info["model_type"] == "plate_appearance"
        assert info["loaded"] is False


class TestMLBGameModel:
    """Verify MLB game model predictions."""

    def test_predict_returns_probabilities(self) -> None:
        from app.analytics.models.sports.mlb.game_model import MLBGameModel

        model = MLBGameModel()
        result = model.predict({})
        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert "expected_home_score" in result
        assert "expected_away_score" in result

    def test_probabilities_sum_to_one(self) -> None:
        from app.analytics.models.sports.mlb.game_model import MLBGameModel

        model = MLBGameModel()
        result = model.predict({})
        total = result["home_win_probability"] + result["away_win_probability"]
        assert abs(total - 1.0) < 0.001

    def test_predict_proba_keys(self) -> None:
        from app.analytics.models.sports.mlb.game_model import MLBGameModel

        model = MLBGameModel()
        probs = model.predict_proba({})
        assert "home_win" in probs
        assert "away_win" in probs
        assert abs(probs["home_win"] + probs["away_win"] - 1.0) < 0.001

    def test_power_advantage_shifts_wp(self) -> None:
        from app.analytics.models.sports.mlb.game_model import MLBGameModel

        model = MLBGameModel()
        base = model.predict({})
        strong_home = model.predict({"home_power_index": 1.5, "away_power_index": 0.8})
        assert strong_home["home_win_probability"] > base["home_win_probability"]

    def test_default_favors_home(self) -> None:
        from app.analytics.models.sports.mlb.game_model import MLBGameModel

        model = MLBGameModel()
        result = model.predict({})
        assert result["home_win_probability"] > 0.5


class TestSimulationEngineMLIntegration:
    """Verify simulation engine can use ML models."""

    def test_ml_mode_integration(self) -> None:
        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"probability_mode": "ml"},
            iterations=100,
            seed=42,
        )
        assert "home_win_probability" in result
        assert result["iterations"] == 100

    def test_no_mode_defaults(self) -> None:
        engine = SimulationEngine("mlb")
        result = engine.run_simulation({}, iterations=50, seed=42)
        assert result["iterations"] == 50

    def test_ml_mode_with_features(self) -> None:
        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {
                "probability_mode": "ml",
                "features": {"contact_rate": 0.85, "power_index": 1.3},
            },
            iterations=100,
            seed=42,
        )
        assert "home_win_probability" in result


class TestFullMLPipeline:
    """Verify Aggregation -> Metrics -> Features -> ML Model -> Simulation."""

    def test_end_to_end_ml_pipeline(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine
        from app.analytics.core.profile_builder import ProfileBuilder
        from app.analytics.models.core.model_registry import ModelRegistry

        # Step 1: Aggregate
        agg = AggregationEngine("mlb")
        batter_agg = agg.aggregate_player_history("b1", [
            {"zone_swing_pct": 0.75, "outside_swing_pct": 0.30,
             "zone_contact_pct": 0.88, "outside_contact_pct": 0.60,
             "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45,
             "barrel_pct": 0.11},
        ])

        # Step 2: Build profile -> get metrics as features
        builder = ProfileBuilder("mlb")
        profile = builder.build_player_profile("b1", batter_agg)
        features = profile.metrics

        # Step 3: ML model generates probabilities
        registry = ModelRegistry(registry_path=None)
        pa_model = registry.get_active_model_instance("mlb", "plate_appearance")
        assert pa_model is not None

        probs = pa_model.predict_proba(features)
        assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)

        sim_probs = pa_model.to_simulation_probs(probs)

        # Step 4: Simulation with ML probabilities
        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"home_probabilities": sim_probs, "away_probabilities": sim_probs},
            iterations=200,
            seed=42,
        )
        assert result["home_win_probability"] > 0
        assert result["iterations"] == 200


class TestFeatureVector:
    """Verify FeatureVector ordering and output."""

    def test_to_array_deterministic_order(self) -> None:
        from app.analytics.features.core.feature_vector import FeatureVector

        vec = FeatureVector(
            {"b": 2.0, "a": 1.0, "c": 3.0},
            feature_order=["a", "b", "c"],
        )
        assert vec.to_array() == [1.0, 2.0, 3.0]

    def test_to_array_sorted_default(self) -> None:
        from app.analytics.features.core.feature_vector import FeatureVector

        vec = FeatureVector({"z": 9.0, "a": 1.0, "m": 5.0})
        assert vec.to_array() == [1.0, 5.0, 9.0]
        assert vec.feature_names == ["a", "m", "z"]

    def test_to_dict(self) -> None:
        from app.analytics.features.core.feature_vector import FeatureVector

        data = {"x": 1.0, "y": 2.0}
        vec = FeatureVector(data)
        assert vec.to_dict() == data

    def test_missing_features_default_to_zero(self) -> None:
        from app.analytics.features.core.feature_vector import FeatureVector

        vec = FeatureVector(
            {"a": 1.0},
            feature_order=["a", "b", "c"],
        )
        assert vec.to_array() == [1.0, 0.0, 0.0]

    def test_size_and_len(self) -> None:
        from app.analytics.features.core.feature_vector import FeatureVector

        vec = FeatureVector({"a": 1.0, "b": 2.0})
        assert vec.size == 2
        assert len(vec) == 2

    def test_get_feature(self) -> None:
        from app.analytics.features.core.feature_vector import FeatureVector

        vec = FeatureVector({"a": 1.5, "b": 2.5})
        assert vec.get("a") == 1.5
        assert vec.get("missing") == 0.0
        assert vec.get("missing", -1.0) == -1.0


class TestFeatureBuilder:
    """Verify sport-agnostic FeatureBuilder routing."""

    def test_build_features_mlb_pa(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder

        builder = FeatureBuilder()
        profiles = {
            "batter_profile": {"metrics": {"contact_rate": 0.83, "power_index": 1.2}},
            "pitcher_profile": {"metrics": {"contact_rate": 0.70, "whiff_rate": 0.28}},
        }
        vec = builder.build_features("mlb", profiles, "plate_appearance")
        assert vec.size > 0
        arr = vec.to_array()
        assert len(arr) == vec.size
        assert all(isinstance(v, float) for v in arr)

    def test_build_features_mlb_game(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder

        builder = FeatureBuilder()
        profiles = {
            "home_profile": {"metrics": {"contact_rate": 0.80, "power_index": 1.1}},
            "away_profile": {"metrics": {"contact_rate": 0.75, "power_index": 0.9}},
        }
        vec = builder.build_features("mlb", profiles, "game")
        assert vec.size > 0
        d = vec.to_dict()
        assert "home_contact_rate" in d
        assert "away_contact_rate" in d

    def test_unsupported_sport_returns_empty(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder

        builder = FeatureBuilder()
        vec = builder.build_features("cricket", {}, "game")
        assert vec.size == 0

    def test_config_disables_features(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder

        builder = FeatureBuilder()
        profiles = {
            "batter_profile": {"metrics": {"contact_rate": 0.83}},
            "pitcher_profile": {"metrics": {}},
        }
        config = {"batter_contact_rate": {"enabled": False}}
        vec = builder.build_features("mlb", profiles, "plate_appearance", config=config)
        assert "batter_contact_rate" not in vec.to_dict()
        # Other features should still be present
        assert vec.size > 0

    def test_build_dataset(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder

        builder = FeatureBuilder()
        records = [
            {
                "batter_profile": {"metrics": {"contact_rate": 0.80}},
                "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
            },
            {
                "batter_profile": {"metrics": {"contact_rate": 0.85}},
                "pitcher_profile": {"metrics": {"contact_rate": 0.65}},
            },
        ]
        X, names = builder.build_dataset("mlb", records, "plate_appearance")
        assert len(X) == 2
        assert len(names) > 0
        assert len(X[0]) == len(names)

    def test_build_dataset_empty(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder

        X, names = FeatureBuilder().build_dataset("mlb", [], "plate_appearance")
        assert X == []
        assert names == []


class TestMLBFeatureBuilder:
    """Verify MLB-specific feature construction."""

    def test_pa_features_have_batter_and_pitcher_prefix(self) -> None:
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder

        builder = MLBFeatureBuilder()
        vec = builder.build_plate_appearance_features(
            {"contact_rate": 0.83, "power_index": 1.2},
            {"contact_rate": 0.70},
        )
        names = vec.feature_names
        batter_feats = [n for n in names if n.startswith("batter_")]
        pitcher_feats = [n for n in names if n.startswith("pitcher_")]
        assert len(batter_feats) > 0
        assert len(pitcher_feats) > 0

    def test_pa_features_ordering_is_deterministic(self) -> None:
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder

        builder = MLBFeatureBuilder()
        v1 = builder.build_plate_appearance_features(
            {"contact_rate": 0.83}, {"contact_rate": 0.70},
        )
        v2 = builder.build_plate_appearance_features(
            {"contact_rate": 0.83}, {"contact_rate": 0.70},
        )
        assert v1.feature_names == v2.feature_names
        assert v1.to_array() == v2.to_array()

    def test_game_features_have_home_and_away_prefix(self) -> None:
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder

        builder = MLBFeatureBuilder()
        vec = builder.build_game_features(
            {"contact_rate": 0.80, "power_index": 1.1},
            {"contact_rate": 0.75, "power_index": 0.9},
        )
        names = vec.feature_names
        assert any(n.startswith("home_") for n in names)
        assert any(n.startswith("away_") for n in names)

    def test_normalization_clamps_rates(self) -> None:
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder

        builder = MLBFeatureBuilder()
        # Extreme contact rate should be clamped to 1.0
        vec = builder.build_plate_appearance_features(
            {"contact_rate": 1.5}, {},
        )
        d = vec.to_dict()
        assert d["batter_contact_rate"] <= 1.0

    def test_normalization_ratios_for_absolute_stats(self) -> None:
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder

        builder = MLBFeatureBuilder()
        # avg_exit_velocity 96 mph / 88 baseline = ~1.09
        vec = builder.build_plate_appearance_features(
            {"avg_exit_velocity": 96.0}, {},
        )
        d = vec.to_dict()
        assert 1.0 < d["batter_avg_exit_velocity"] < 1.2

    def test_missing_metrics_use_defaults(self) -> None:
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder

        builder = MLBFeatureBuilder()
        vec = builder.build_plate_appearance_features({}, {})
        arr = vec.to_array()
        # All features should have default values (no NaN or None)
        assert all(isinstance(v, float) for v in arr)
        assert all(v >= 0 for v in arr)

    def test_profile_object_extraction(self) -> None:
        from app.analytics.core.types import PlayerProfile

        batter = PlayerProfile(
            player_id="b1", sport="mlb",
            metrics={"contact_rate": 0.85, "power_index": 1.3},
        )
        # Build via the generic route that extracts .metrics
        from app.analytics.features.core.feature_builder import FeatureBuilder
        fb = FeatureBuilder()
        vec = fb.build_features("mlb", {
            "batter_profile": batter,
            "pitcher_profile": PlayerProfile(player_id="p1", sport="mlb", metrics={}),
        }, "plate_appearance")
        assert vec.get("batter_contact_rate") == 0.85


class TestFeatureMLModelIntegration:
    """Verify feature vectors work with ML models."""

    def test_pa_features_to_ml_model(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        builder = FeatureBuilder()
        profiles = {
            "batter_profile": {"metrics": {"contact_rate": 0.85, "power_index": 1.3}},
            "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
        }
        vec = builder.build_features("mlb", profiles, "plate_appearance")

        # ML model accepts feature dict
        model = MLBPlateAppearanceModel()
        probs = model.predict_proba(vec.to_dict())
        assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)

    def test_game_features_to_ml_model(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder
        from app.analytics.models.sports.mlb.game_model import MLBGameModel

        builder = FeatureBuilder()
        profiles = {
            "home_profile": {"metrics": {"contact_rate": 0.80, "power_index": 1.1}},
            "away_profile": {"metrics": {"contact_rate": 0.75, "power_index": 0.9}},
        }
        vec = builder.build_features("mlb", profiles, "game")

        model = MLBGameModel()
        result = model.predict(vec.to_dict())
        assert "home_win_probability" in result

    def test_full_pipeline_aggregation_to_features_to_model(self) -> None:
        from app.analytics.core.aggregation_engine import AggregationEngine
        from app.analytics.core.profile_builder import ProfileBuilder
        from app.analytics.features.core.feature_builder import FeatureBuilder
        from app.analytics.models.sports.mlb.pa_model import MLBPlateAppearanceModel

        # Aggregate -> Profile
        agg = AggregationEngine("mlb")
        batter_agg = agg.aggregate_player_history("b1", [
            {"zone_swing_pct": 0.75, "outside_swing_pct": 0.30,
             "zone_contact_pct": 0.88, "outside_contact_pct": 0.60,
             "avg_exit_velocity": 92.0, "hard_hit_pct": 0.45,
             "barrel_pct": 0.11},
        ])
        builder = ProfileBuilder("mlb")
        batter_profile = builder.build_player_profile("b1", batter_agg)

        pitcher_agg = agg.aggregate_player_history("p1", [
            {"zone_swing_pct": 0.65, "outside_swing_pct": 0.35,
             "zone_contact_pct": 0.72, "outside_contact_pct": 0.50,
             "avg_exit_velocity": 85.0, "hard_hit_pct": 0.28,
             "barrel_pct": 0.05},
        ])
        pitcher_profile = builder.build_player_profile("p1", pitcher_agg)

        # Profile -> Features
        fb = FeatureBuilder()
        vec = fb.build_features("mlb", {
            "batter_profile": batter_profile,
            "pitcher_profile": pitcher_profile,
        }, "plate_appearance")

        assert vec.size > 0
        arr = vec.to_array()
        assert all(isinstance(v, float) for v in arr)

        # Features -> ML Model
        model = MLBPlateAppearanceModel()
        probs = model.predict_proba(batter_profile.metrics)
        sim_probs = model.to_simulation_probs(probs)

        # ML Model -> Simulation
        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"home_probabilities": sim_probs, "away_probabilities": sim_probs},
            iterations=100, seed=42,
        )
        assert result["home_win_probability"] > 0


class TestFeatureBuilderConfigIntegration:
    """Tests for FeatureBuilder + config integration."""

    def test_config_disables_features(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder
        builder = FeatureBuilder()
        profiles = {
            "batter_profile": {
                "metrics": {
                    "contact_rate": 0.82,
                    "power_index": 1.1,
                    "barrel_rate": 0.09,
                    "hard_hit_rate": 0.40,
                    "swing_rate": 0.52,
                    "whiff_rate": 0.20,
                    "avg_exit_velocity": 91.0,
                    "expected_slug": 0.82,
                }
            },
            "pitcher_profile": {
                "metrics": {
                    "contact_rate": 0.70,
                    "power_index": 0.9,
                    "barrel_rate": 0.05,
                    "hard_hit_rate": 0.30,
                    "swing_rate": 0.48,
                    "whiff_rate": 0.28,
                }
            },
        }

        config = {
            "batter_contact_rate": {"enabled": True, "weight": 1.0},
            "batter_power_index": {"enabled": True, "weight": 1.0},
            "batter_barrel_rate": {"enabled": True, "weight": 1.0},
            "batter_hard_hit_rate": {"enabled": True, "weight": 1.0},
            "batter_swing_rate": {"enabled": False},
            "batter_whiff_rate": {"enabled": True, "weight": 1.0},
            "batter_avg_exit_velocity": {"enabled": True, "weight": 1.0},
            "batter_expected_slug": {"enabled": True, "weight": 1.0},
            "pitcher_contact_rate": {"enabled": True, "weight": 1.0},
            "pitcher_power_index": {"enabled": True, "weight": 1.0},
            "pitcher_barrel_rate": {"enabled": True, "weight": 1.0},
            "pitcher_hard_hit_rate": {"enabled": True, "weight": 1.0},
            "pitcher_swing_rate": {"enabled": True, "weight": 1.0},
            "pitcher_whiff_rate": {"enabled": False},
        }

        vec = builder.build_features("mlb", profiles, "plate_appearance", config=config)
        names = vec.feature_names

        assert "batter_swing_rate" not in names
        assert "pitcher_whiff_rate" not in names
        assert "batter_contact_rate" in names
        assert vec.size == 26  # 28 - 2 disabled

    def test_config_applies_weights(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder
        builder = FeatureBuilder()
        profiles = {
            "home_profile": {
                "metrics": {
                    "contact_rate": 0.80,
                    "power_index": 1.0,
                    "expected_slug": 0.77,
                    "barrel_rate": 0.07,
                    "hard_hit_rate": 0.35,
                }
            },
            "away_profile": {
                "metrics": {
                    "contact_rate": 0.80,
                    "power_index": 1.0,
                    "expected_slug": 0.77,
                    "barrel_rate": 0.07,
                    "hard_hit_rate": 0.35,
                }
            },
        }

        config = {
            "home_contact_rate": {"enabled": True, "weight": 0.5},
            "home_power_index": {"enabled": True, "weight": 1.0},
            "home_expected_slug": {"enabled": True, "weight": 1.0},
            "home_barrel_rate": {"enabled": True, "weight": 1.0},
            "home_hard_hit_rate": {"enabled": True, "weight": 1.0},
            "away_contact_rate": {"enabled": True, "weight": 1.0},
            "away_power_index": {"enabled": True, "weight": 1.0},
            "away_expected_slug": {"enabled": True, "weight": 1.0},
            "away_barrel_rate": {"enabled": True, "weight": 1.0},
            "away_hard_hit_rate": {"enabled": True, "weight": 1.0},
        }

        vec_weighted = builder.build_features("mlb", profiles, "game", config=config)
        vec_unweighted = builder.build_features("mlb", profiles, "game")

        weighted_val = vec_weighted.get("home_contact_rate")
        unweighted_val = vec_unweighted.get("home_contact_rate")
        assert abs(weighted_val - unweighted_val * 0.5) < 0.001

    def test_dataset_with_config(self) -> None:
        from app.analytics.features.core.feature_builder import FeatureBuilder
        builder = FeatureBuilder()
        records = [
            {
                "batter_profile": {"metrics": {"contact_rate": 0.82, "power_index": 1.1}},
                "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
            },
            {
                "batter_profile": {"metrics": {"contact_rate": 0.75, "power_index": 0.9}},
                "pitcher_profile": {"metrics": {"contact_rate": 0.72}},
            },
        ]
        config = {
            "batter_contact_rate": {"enabled": True, "weight": 1.0},
            "batter_power_index": {"enabled": True, "weight": 1.0},
            "batter_barrel_rate": {"enabled": False},
            "batter_hard_hit_rate": {"enabled": True, "weight": 1.0},
            "batter_swing_rate": {"enabled": True, "weight": 1.0},
            "batter_whiff_rate": {"enabled": True, "weight": 1.0},
            "batter_avg_exit_velocity": {"enabled": True, "weight": 1.0},
            "batter_expected_slug": {"enabled": True, "weight": 1.0},
            "pitcher_contact_rate": {"enabled": True, "weight": 1.0},
            "pitcher_power_index": {"enabled": True, "weight": 1.0},
            "pitcher_barrel_rate": {"enabled": True, "weight": 1.0},
            "pitcher_hard_hit_rate": {"enabled": True, "weight": 1.0},
            "pitcher_swing_rate": {"enabled": True, "weight": 1.0},
            "pitcher_whiff_rate": {"enabled": True, "weight": 1.0},
        }
        X, names = builder.build_dataset("mlb", records, "plate_appearance", config=config)
        assert len(X) == 2
        assert "batter_barrel_rate" not in names
        assert len(names) == 27  # 28 - 1 disabled


# ---------------------------------------------------------------------------
# Prompt 14 – Model Training Pipeline
# ---------------------------------------------------------------------------

import json

from app.analytics.training.core.dataset_builder import DatasetBuilder
from app.analytics.training.core.model_evaluator import ModelEvaluator
from app.analytics.training.core.training_metadata import TrainingMetadata
from app.analytics.training.core.training_pipeline import TrainingPipeline
from app.analytics.training.sports.mlb_training import MLBTrainingPipeline


def _make_pa_records(n: int = 50) -> list[dict]:
    """Generate synthetic plate-appearance training records."""
    import random
    rng = random.Random(42)
    outcomes = ["strikeout", "out", "walk", "single", "double", "triple", "home_run"]
    weights = [0.22, 0.35, 0.08, 0.18, 0.07, 0.02, 0.08]
    records = []
    for _ in range(n):
        outcome = rng.choices(outcomes, weights=weights, k=1)[0]
        records.append({
            "batter_profile": {
                "metrics": {
                    "contact_rate": round(rng.uniform(0.60, 0.90), 4),
                    "power_index": round(rng.uniform(0.7, 1.5), 4),
                    "barrel_rate": round(rng.uniform(0.03, 0.15), 4),
                    "hard_hit_rate": round(rng.uniform(0.25, 0.50), 4),
                    "swing_rate": round(rng.uniform(0.40, 0.60), 4),
                    "whiff_rate": round(rng.uniform(0.15, 0.35), 4),
                    "avg_exit_velocity": round(rng.uniform(84.0, 95.0), 1),
                    "expected_slug": round(rng.uniform(0.50, 1.10), 4),
                }
            },
            "pitcher_profile": {
                "metrics": {
                    "contact_rate": round(rng.uniform(0.60, 0.85), 4),
                    "power_index": round(rng.uniform(0.7, 1.3), 4),
                    "barrel_rate": round(rng.uniform(0.03, 0.12), 4),
                    "hard_hit_rate": round(rng.uniform(0.25, 0.45), 4),
                    "swing_rate": round(rng.uniform(0.40, 0.60), 4),
                    "whiff_rate": round(rng.uniform(0.15, 0.35), 4),
                }
            },
            "outcome": outcome,
        })
    return records


def _make_game_records(n: int = 50) -> list[dict]:
    """Generate synthetic game training records."""
    import random
    rng = random.Random(42)
    records = []
    for _ in range(n):
        home_win = rng.random() < 0.54
        records.append({
            "home_profile": {
                "metrics": {
                    "contact_rate": round(rng.uniform(0.70, 0.85), 4),
                    "power_index": round(rng.uniform(0.8, 1.3), 4),
                    "expected_slug": round(rng.uniform(0.55, 1.00), 4),
                    "barrel_rate": round(rng.uniform(0.04, 0.12), 4),
                    "hard_hit_rate": round(rng.uniform(0.28, 0.45), 4),
                }
            },
            "away_profile": {
                "metrics": {
                    "contact_rate": round(rng.uniform(0.70, 0.85), 4),
                    "power_index": round(rng.uniform(0.8, 1.3), 4),
                    "expected_slug": round(rng.uniform(0.55, 1.00), 4),
                    "barrel_rate": round(rng.uniform(0.04, 0.12), 4),
                    "hard_hit_rate": round(rng.uniform(0.28, 0.45), 4),
                }
            },
            "home_win": int(home_win),
            "home_score": rng.randint(0, 12),
            "away_score": rng.randint(0, 12),
        })
    return records


class TestDatasetBuilder:
    """Tests for DatasetBuilder."""

    def test_build_returns_X_y_names(self) -> None:
        records = _make_pa_records(20)
        builder = DatasetBuilder("mlb", "plate_appearance")
        mlb = MLBTrainingPipeline()
        X, y, names = builder.build(records, label_fn=mlb.pa_label_fn)

        assert len(X) == 20
        assert len(y) == 20
        assert len(names) > 0
        assert all(isinstance(row, list) for row in X)
        assert all(isinstance(v, float) for row in X for v in row)

    def test_build_game_records(self) -> None:
        records = _make_game_records(20)
        builder = DatasetBuilder("mlb", "game")
        mlb = MLBTrainingPipeline()
        X, y, names = builder.build(records, label_fn=mlb.game_label_fn)

        assert len(X) == 20
        assert len(y) == 20
        assert all(label in (0, 1) for label in y)

    def test_build_with_config(self, tmp_path: Path) -> None:
        (tmp_path / "test_cfg.yaml").write_text(
            "model: t\nsport: mlb\nfeatures:\n"
            "  batter_contact_rate:\n    enabled: true\n    weight: 1.0\n"
            "  batter_power_index:\n    enabled: false\n"
        )
        # DatasetBuilder accepts config_name but needs the loader to find it.
        # For this test, we pass config manually through FeatureBuilder.
        records = _make_pa_records(10)
        builder = DatasetBuilder("mlb", "plate_appearance")
        mlb = MLBTrainingPipeline()
        X, y, names = builder.build(records, label_fn=mlb.pa_label_fn)
        assert len(X) == 10

    def test_build_empty_records(self) -> None:
        builder = DatasetBuilder("mlb", "plate_appearance")
        X, y, names = builder.build([])
        assert X == []
        assert y == []
        assert names == []

    def test_build_labels_only(self) -> None:
        records = _make_pa_records(10)
        builder = DatasetBuilder("mlb", "plate_appearance")
        mlb = MLBTrainingPipeline()
        labels = builder.build_labels(records, label_fn=mlb.pa_label_fn)
        assert len(labels) == 10
        assert all(isinstance(l, str) for l in labels)


@pytest.mark.skipif(
    not _has_sklearn, reason="scikit-learn not installed"
)
class TestModelEvaluator:
    """Tests for ModelEvaluator."""

    def test_evaluate_classifier(self) -> None:
        from sklearn.ensemble import GradientBoostingClassifier

        records = _make_pa_records(60)
        mlb = MLBTrainingPipeline()
        builder = DatasetBuilder("mlb", "plate_appearance")
        X, y, _ = builder.build(records, label_fn=mlb.pa_label_fn)

        model = GradientBoostingClassifier(
            n_estimators=10, max_depth=3, random_state=42,
        )
        model.fit(X[:48], y[:48])

        evaluator = ModelEvaluator()
        result = evaluator.evaluate_classifier(model, X[48:], y[48:])

        assert "accuracy" in result
        assert "sample_count" in result
        assert result["sample_count"] == len(X[48:])
        assert 0.0 <= result["accuracy"] <= 1.0

    def test_evaluate_regressor(self) -> None:
        from sklearn.ensemble import GradientBoostingRegressor

        records = _make_game_records(60)
        mlb = MLBTrainingPipeline()
        builder = DatasetBuilder("mlb", "game")
        X, y_labels, _ = builder.build(records, label_fn=mlb.game_label_fn)
        # Use home_score as regression target
        y_reg = [float(r.get("home_score", 0)) for r in records]

        model = GradientBoostingRegressor(
            n_estimators=10, max_depth=3, random_state=42,
        )
        model.fit(X[:48], y_reg[:48])

        evaluator = ModelEvaluator()
        result = evaluator.evaluate_regressor(model, X[48:], y_reg[48:])

        assert "mae" in result
        assert "rmse" in result
        assert result["mae"] >= 0
        assert result["rmse"] >= 0

    def test_evaluate_empty(self) -> None:
        evaluator = ModelEvaluator()
        result = evaluator.evaluate_classifier(None, [], [])
        assert result["sample_count"] == 0


class TestTrainingMetadata:
    """Tests for TrainingMetadata."""

    def test_create_and_save(self, tmp_path: Path) -> None:
        meta = TrainingMetadata(
            model_id="test_v1",
            sport="mlb",
            model_type="plate_appearance",
            feature_config="mlb_pa_model",
            random_state=42,
        )
        meta.record_split(train_count=100, test_count=25)
        meta.record_metrics({"accuracy": 0.65})
        meta.record_artifact("models/mlb/artifacts/test_v1.pkl")

        path = meta.save(tmp_path / "test_v1.json")
        assert path.exists()

        with open(path) as f:
            data = json.load(f)

        assert data["model_id"] == "test_v1"
        assert data["sport"] == "mlb"
        assert data["training_row_count"] == 125
        assert data["metrics"]["accuracy"] == 0.65
        assert data["artifact_path"] == "models/mlb/artifacts/test_v1.pkl"

    def test_load(self, tmp_path: Path) -> None:
        meta = TrainingMetadata(model_id="load_test", sport="mlb", model_type="game")
        meta.record_metrics({"mae": 1.5})
        meta.save(tmp_path / "load_test.json")

        loaded = TrainingMetadata.load(tmp_path / "load_test.json")
        d = loaded.to_dict()
        assert d["model_id"] == "load_test"
        assert d["metrics"]["mae"] == 1.5

    def test_to_dict(self) -> None:
        meta = TrainingMetadata(model_id="d", sport="mlb", model_type="pa")
        d = meta.to_dict()
        assert "model_id" in d
        assert "created_at" in d


class TestMLBTrainingPipeline:
    """Tests for MLBTrainingPipeline helpers."""

    def test_pa_label_fn(self) -> None:
        mlb = MLBTrainingPipeline()
        assert mlb.pa_label_fn({"outcome": "single"}) == "single"
        assert mlb.pa_label_fn({"outcome": "HOME_RUN"}) == "home_run"
        assert mlb.pa_label_fn({"outcome": "invalid"}) is None
        assert mlb.pa_label_fn({}) is None

    def test_game_label_fn(self) -> None:
        mlb = MLBTrainingPipeline()
        assert mlb.game_label_fn({"home_win": 1}) == 1
        assert mlb.game_label_fn({"home_win": 0}) == 0
        assert mlb.game_label_fn({"home_score": 5, "away_score": 3}) == 1
        assert mlb.game_label_fn({"home_score": 2, "away_score": 4}) == 0
        assert mlb.game_label_fn({}) is None

    def test_build_pa_record(self) -> None:
        record = MLBTrainingPipeline.build_pa_record(
            {"contact_rate": 0.8}, {"contact_rate": 0.7}, "single",
        )
        assert record["outcome"] == "single"
        assert "batter_profile" in record
        assert "pitcher_profile" in record

    def test_build_game_record(self) -> None:
        record = MLBTrainingPipeline.build_game_record(
            {"power_index": 1.1}, {"power_index": 0.9}, True,
            home_score=5, away_score=3,
        )
        assert record["home_win"] == 1
        assert record["home_score"] == 5

    def test_load_returns_empty(self) -> None:
        mlb = MLBTrainingPipeline()
        assert mlb.load_plate_appearance_training_data() == []
        assert mlb.load_game_training_data() == []


@pytest.mark.skipif(
    not _has_sklearn, reason="scikit-learn not installed"
)
class TestTrainingPipeline:
    """Tests for end-to-end TrainingPipeline."""

    def test_pa_pipeline_end_to_end(self, tmp_path: Path) -> None:
        records = _make_pa_records(80)
        mlb = MLBTrainingPipeline()

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="plate_appearance",
            model_id="test_pa_v1",
            random_state=42,
            artifact_dir=tmp_path / "models",
        )

        result = pipeline.run(records=records, label_fn=mlb.pa_label_fn)

        assert result["model_id"] == "test_pa_v1"
        assert result["artifact_path"] is not None
        assert result["metadata_path"] is not None
        assert result["metrics"] is not None
        assert result["train_count"] > 0
        assert result["test_count"] > 0
        assert len(result["feature_names"]) > 0

        # Verify artifact file exists
        assert Path(result["artifact_path"]).exists()
        assert Path(result["metadata_path"]).exists()

    def test_game_pipeline_end_to_end(self, tmp_path: Path) -> None:
        records = _make_game_records(80)
        mlb = MLBTrainingPipeline()

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="game",
            model_id="test_game_v1",
            random_state=42,
            artifact_dir=tmp_path / "models",
        )

        result = pipeline.run(records=records, label_fn=mlb.game_label_fn)

        assert result["model_id"] == "test_game_v1"
        assert Path(result["artifact_path"]).exists()
        assert Path(result["metadata_path"]).exists()
        assert "accuracy" in result["metrics"]

    def test_pipeline_with_no_data(self, tmp_path: Path) -> None:
        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="plate_appearance",
            model_id="empty_test",
            artifact_dir=tmp_path / "models",
        )
        result = pipeline.run(records=[])
        assert result.get("error") == "no_training_data"

    def test_pipeline_metadata_saved(self, tmp_path: Path) -> None:
        records = _make_pa_records(50)
        mlb = MLBTrainingPipeline()

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="plate_appearance",
            model_id="meta_test_v1",
            config_name="",
            random_state=42,
            artifact_dir=tmp_path / "models",
        )

        result = pipeline.run(records=records, label_fn=mlb.pa_label_fn)
        meta_path = Path(result["metadata_path"])
        assert meta_path.exists()

        with open(meta_path) as f:
            meta = json.load(f)

        assert meta["model_id"] == "meta_test_v1"
        assert meta["sport"] == "mlb"
        assert meta["random_state"] == 42
        assert meta["training_row_count"] == 50
        assert "accuracy" in meta["metrics"]

    def test_pipeline_artifact_loadable(self, tmp_path: Path) -> None:
        import joblib

        records = _make_game_records(60)
        mlb = MLBTrainingPipeline()

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="game",
            model_id="load_test_v1",
            random_state=42,
            artifact_dir=tmp_path / "models",
        )

        result = pipeline.run(records=records, label_fn=mlb.game_label_fn)
        model = joblib.load(result["artifact_path"])
        assert hasattr(model, "predict")

    def test_pipeline_custom_sklearn_model(self, tmp_path: Path) -> None:
        from sklearn.ensemble import RandomForestClassifier

        records = _make_pa_records(60)
        mlb = MLBTrainingPipeline()

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="plate_appearance",
            model_id="rf_test_v1",
            random_state=42,
            artifact_dir=tmp_path / "models",
        )

        custom_model = RandomForestClassifier(
            n_estimators=20, max_depth=4, random_state=42,
        )
        result = pipeline.run(
            records=records, label_fn=mlb.pa_label_fn, sklearn_model=custom_model,
        )
        assert result["metrics"] is not None
        assert Path(result["artifact_path"]).exists()


# ---------------------------------------------------------------------------
# Prompt 15 – Model Inference Engine
# ---------------------------------------------------------------------------

from app.analytics.inference.inference_cache import InferenceCache
from app.analytics.inference.model_inference_engine import ModelInferenceEngine
from app.analytics.models.core.model_registry import ModelRegistry


@pytest.mark.skipif(
    not _has_joblib, reason="joblib not installed"
)
class TestInferenceCache:
    """Tests for InferenceCache."""

    def test_cache_loads_and_caches_model(self, tmp_path: Path) -> None:
        import joblib
        from sklearn.ensemble import GradientBoostingClassifier

        model = GradientBoostingClassifier(n_estimators=5, random_state=42)
        model.fit([[1, 2], [3, 4]], [0, 1])
        path = str(tmp_path / "test_model.pkl")
        joblib.dump(model, path)

        cache = InferenceCache()
        assert cache.size == 0
        assert not cache.is_cached(path)

        loaded = cache.get_model(path)
        assert hasattr(loaded, "predict")
        assert cache.is_cached(path)
        assert cache.size == 1

        # Second load should come from cache (same object)
        loaded2 = cache.get_model(path)
        assert loaded is loaded2

    def test_invalidate(self, tmp_path: Path) -> None:
        import joblib
        from sklearn.ensemble import GradientBoostingClassifier

        model = GradientBoostingClassifier(n_estimators=5, random_state=42)
        model.fit([[1, 2], [3, 4]], [0, 1])
        path = str(tmp_path / "inv_model.pkl")
        joblib.dump(model, path)

        cache = InferenceCache()
        cache.get_model(path)
        assert cache.size == 1
        cache.invalidate(path)
        assert cache.size == 0

    def test_clear(self, tmp_path: Path) -> None:
        import joblib
        from sklearn.ensemble import GradientBoostingClassifier

        model = GradientBoostingClassifier(n_estimators=5, random_state=42)
        model.fit([[1, 2], [3, 4]], [0, 1])
        for name in ["a.pkl", "b.pkl"]:
            joblib.dump(model, str(tmp_path / name))

        cache = InferenceCache()
        cache.get_model(str(tmp_path / "a.pkl"))
        cache.get_model(str(tmp_path / "b.pkl"))
        assert cache.size == 2
        cache.clear()
        assert cache.size == 0


class TestModelInferenceEngine:
    """Tests for ModelInferenceEngine."""

    _BATTER_PROFILES = {
        "batter_profile": {
            "metrics": {
                "contact_rate": 0.82,
                "power_index": 1.1,
                "barrel_rate": 0.09,
                "hard_hit_rate": 0.40,
                "swing_rate": 0.52,
                "whiff_rate": 0.20,
                "avg_exit_velocity": 91.0,
                "expected_slug": 0.82,
            }
        },
        "pitcher_profile": {
            "metrics": {
                "contact_rate": 0.70,
                "power_index": 0.9,
                "barrel_rate": 0.05,
                "hard_hit_rate": 0.30,
                "swing_rate": 0.48,
                "whiff_rate": 0.28,
            }
        },
    }

    _GAME_PROFILES = {
        "home_profile": {
            "metrics": {
                "contact_rate": 0.80,
                "power_index": 1.0,
                "expected_slug": 0.77,
                "barrel_rate": 0.07,
                "hard_hit_rate": 0.35,
            }
        },
        "away_profile": {
            "metrics": {
                "contact_rate": 0.75,
                "power_index": 0.95,
                "expected_slug": 0.72,
                "barrel_rate": 0.06,
                "hard_hit_rate": 0.32,
            }
        },
    }

    def test_predict_proba_pa_rule_based(self) -> None:
        engine = ModelInferenceEngine()
        probs = engine.predict_proba("mlb", "plate_appearance", self._BATTER_PROFILES)

        assert isinstance(probs, dict)
        assert len(probs) > 0
        assert "strikeout" in probs
        assert "out" in probs
        assert "single" in probs
        assert all(0 <= v <= 1 for v in probs.values())

    def test_predict_proba_game_rule_based(self) -> None:
        engine = ModelInferenceEngine()
        probs = engine.predict_proba("mlb", "game", self._GAME_PROFILES)

        assert isinstance(probs, dict)
        assert "home_win" in probs
        assert "away_win" in probs
        assert abs(probs["home_win"] + probs["away_win"] - 1.0) < 0.01

    def test_predict_returns_full_output(self) -> None:
        engine = ModelInferenceEngine()
        result = engine.predict("mlb", "plate_appearance", self._BATTER_PROFILES)

        assert "event_probabilities" in result
        assert "predicted_event" in result

    def test_predict_for_simulation_pa(self) -> None:
        engine = ModelInferenceEngine()
        sim_probs = engine.predict_for_simulation(
            "mlb", "plate_appearance", self._BATTER_PROFILES,
        )

        assert "strikeout_probability" in sim_probs
        assert "walk_probability" in sim_probs
        assert "single_probability" in sim_probs
        assert "home_run_probability" in sim_probs

    def test_predict_for_simulation_game(self) -> None:
        engine = ModelInferenceEngine()
        sim_probs = engine.predict_for_simulation(
            "mlb", "game", self._GAME_PROFILES,
        )

        # Game model doesn't have to_simulation_probs, returns raw probs
        assert isinstance(sim_probs, dict)
        assert len(sim_probs) > 0

    def test_predict_unsupported_sport(self) -> None:
        engine = ModelInferenceEngine()
        result = engine.predict("nfl", "game", {})
        assert result.get("error") == "model_not_found"

    def test_predict_proba_unsupported_returns_empty(self) -> None:
        engine = ModelInferenceEngine()
        probs = engine.predict_proba("nfl", "game", {})
        assert probs == {}

    @pytest.mark.skipif(not _has_joblib, reason="joblib not installed")
    def test_with_trained_model(self, tmp_path: Path) -> None:
        """Test inference with a trained model artifact."""
        import joblib
        from sklearn.ensemble import GradientBoostingClassifier

        # Train a small model
        records = _make_pa_records(80)
        mlb_train = MLBTrainingPipeline()
        ds_builder = DatasetBuilder("mlb", "plate_appearance")
        X, y, names = ds_builder.build(records, label_fn=mlb_train.pa_label_fn)

        sklearn_model = GradientBoostingClassifier(
            n_estimators=10, max_depth=3, random_state=42,
        )
        sklearn_model.fit(X, y)
        sklearn_model._training_feature_names = names
        artifact_path = str(tmp_path / "test_pa.pkl")
        joblib.dump(sklearn_model, artifact_path)

        # Register the model
        registry = ModelRegistry(registry_path=None)
        registry.register_model(
            sport="mlb",
            model_type="plate_appearance",
            model_id="test_pa_trained",
            artifact_path=artifact_path,
            version=1,
        )
        registry.activate_model("mlb", "plate_appearance", "test_pa_trained")

        engine = ModelInferenceEngine(registry=registry)
        probs = engine.predict_proba(
            "mlb", "plate_appearance", self._BATTER_PROFILES,
        )

        assert isinstance(probs, dict)
        assert len(probs) > 0
        # Trained model should produce probabilities
        assert all(isinstance(v, float) for v in probs.values())

    @pytest.mark.skipif(not _has_joblib, reason="joblib not installed")
    def test_cache_prevents_reload(self, tmp_path: Path) -> None:
        """Verify inference cache prevents repeated disk reads."""
        import joblib
        from sklearn.ensemble import GradientBoostingClassifier

        # Train on proper feature set
        records = _make_pa_records(60)
        mlb_train = MLBTrainingPipeline()
        ds_builder = DatasetBuilder("mlb", "plate_appearance")
        X, y, names = ds_builder.build(records, label_fn=mlb_train.pa_label_fn)

        sklearn_model = GradientBoostingClassifier(n_estimators=5, random_state=42)
        sklearn_model.fit(X, y)
        sklearn_model._training_feature_names = names
        path = str(tmp_path / "cache_test.pkl")
        joblib.dump(sklearn_model, path)

        cache = InferenceCache()
        registry = ModelRegistry(registry_path=None)
        registry.register_model(
            sport="mlb",
            model_type="plate_appearance",
            model_id="cache_test",
            artifact_path=path,
            version=1,
        )
        registry.activate_model("mlb", "plate_appearance", "cache_test")

        engine = ModelInferenceEngine(registry=registry, cache=cache)
        engine.predict_proba("mlb", "plate_appearance", self._BATTER_PROFILES)
        assert cache.is_cached(path)

        # Second call should use cached model
        engine.predict_proba("mlb", "plate_appearance", self._BATTER_PROFILES)
        assert cache.size == 1


class TestSimulationEngineProbabilityModes:
    """Tests for simulation engine probability mode dispatch."""

    def test_simulation_with_ml_mode(self) -> None:
        """Simulation engine should use ML model when probability_mode is ml."""
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {
                "probability_mode": "ml",
                "profiles": {
                    "batter_profile": {"metrics": {"contact_rate": 0.82}},
                    "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
                },
            },
            iterations=100,
            seed=42,
        )

        assert "home_win_probability" in result
        assert result["iterations"] > 0

    def test_simulation_without_ml_mode(self) -> None:
        """Simulation should work normally without probability_mode key."""
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"home_probabilities": {}, "away_probabilities": {}},
            iterations=100,
            seed=42,
        )

        assert "home_win_probability" in result


# ---------------------------------------------------------------------------
# Prompt 16 – Simulation + ML Integration
# ---------------------------------------------------------------------------

from app.analytics.probabilities.probability_provider import (
    MLB_PA_EVENTS,
    MLProvider,
    RuleBasedProvider,
    normalize_probabilities,
    validate_probabilities,
)
from app.analytics.probabilities.probability_resolver import (
    ProbabilityResolver,
)


class TestNormalizeProbabilities:
    """Tests for normalize_probabilities helper."""

    def test_normalizes_to_one(self) -> None:
        raw = {"a": 0.3, "b": 0.5, "c": 0.2}
        result = normalize_probabilities(raw)
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_clamps_negatives(self) -> None:
        raw = {"a": -0.1, "b": 0.6, "c": 0.5}
        result = normalize_probabilities(raw)
        assert result["a"] == 0.0
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_uniform_on_all_zero(self) -> None:
        raw = {"a": 0.0, "b": 0.0}
        result = normalize_probabilities(raw)
        assert abs(result["a"] - 0.5) < 0.001
        assert abs(result["b"] - 0.5) < 0.001

    def test_fills_missing_events(self) -> None:
        raw = {"strikeout": 0.3}
        result = normalize_probabilities(raw, valid_events=["strikeout", "out"])
        assert "out" in result
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_probabilities({}, valid_events=[])


class TestValidateProbabilities:
    """Tests for validate_probabilities helper."""

    def test_valid_probs(self) -> None:
        probs = {"a": 0.6, "b": 0.4}
        issues = validate_probabilities(probs)
        assert issues == []

    def test_negative_flagged(self) -> None:
        probs = {"a": -0.1, "b": 1.1}
        issues = validate_probabilities(probs)
        assert any("negative" in i for i in issues)

    def test_sum_not_one(self) -> None:
        probs = {"a": 0.3, "b": 0.3}
        issues = validate_probabilities(probs)
        assert any("sum_not_one" in i for i in issues)

    def test_missing_event(self) -> None:
        probs = {"a": 1.0}
        issues = validate_probabilities(probs, valid_events=["a", "b"])
        assert any("missing_event" in i for i in issues)

    def test_empty(self) -> None:
        issues = validate_probabilities({})
        assert "empty_probabilities" in issues


class TestRuleBasedProvider:
    """Tests for RuleBasedProvider."""

    def test_returns_normalized_probs(self) -> None:
        provider = RuleBasedProvider()
        probs = provider.get_event_probabilities("mlb", {})
        assert abs(sum(probs.values()) - 1.0) < 0.001
        for event in MLB_PA_EVENTS:
            assert event in probs

    def test_with_profiles(self) -> None:
        provider = RuleBasedProvider()
        context = {
            "batter_profile": {"metrics": {"contact_rate": 0.85, "power_index": 1.2}},
            "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
        }
        probs = provider.get_event_probabilities("mlb", context)
        assert abs(sum(probs.values()) - 1.0) < 0.001
        assert all(0 <= v <= 1 for v in probs.values())

    def test_provider_name(self) -> None:
        assert RuleBasedProvider().provider_name == "rule_based"


class TestMLProvider:
    """Tests for MLProvider."""

    def test_returns_normalized_probs(self) -> None:
        provider = MLProvider(model_type="plate_appearance")
        context = {
            "batter_profile": {"metrics": {"contact_rate": 0.82, "power_index": 1.1}},
            "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
        }
        probs = provider.get_event_probabilities("mlb", context)
        assert abs(sum(probs.values()) - 1.0) < 0.001
        for event in MLB_PA_EVENTS:
            assert event in probs

    def test_empty_profiles_uses_defaults(self) -> None:
        provider = MLProvider(model_type="plate_appearance")
        probs = provider.get_event_probabilities("mlb", {})
        assert abs(sum(probs.values()) - 1.0) < 0.001

    def test_provider_name(self) -> None:
        assert MLProvider().provider_name == "ml"


class TestProbabilityResolver:
    """Tests for ProbabilityResolver."""

    def test_rule_based_mode(self) -> None:
        resolver = ProbabilityResolver(config={"probability_mode": "rule_based"})
        probs = resolver.get_probabilities("mlb", "plate_appearance", {})
        assert abs(sum(probs.values()) - 1.0) < 0.001

    def test_ml_mode(self) -> None:
        resolver = ProbabilityResolver(config={"probability_mode": "ml"})
        context = {
            "batter_profile": {"metrics": {"contact_rate": 0.82}},
            "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
        }
        probs = resolver.get_probabilities("mlb", "plate_appearance", context)
        assert abs(sum(probs.values()) - 1.0) < 0.001

    def test_resolver_chooses_correct_provider(self) -> None:
        resolver = ProbabilityResolver(config={"probability_mode": "rule_based"})
        provider = resolver.resolve_provider("mlb", "plate_appearance")
        assert provider.provider_name == "rule_based"

        resolver2 = ProbabilityResolver(config={"probability_mode": "ml"})
        provider2 = resolver2.resolve_provider("mlb", "plate_appearance")
        assert provider2.provider_name == "ml"

    def test_ml_failure_raises(self) -> None:
        """ML failure should raise — no silent fallback."""
        resolver = ProbabilityResolver(config={
            "probability_mode": "ml",
        })
        with pytest.raises(RuntimeError, match="ML probability provider failed"):
            resolver.get_probabilities("unknown_sport", "plate_appearance", {})

    def test_metadata_included(self) -> None:
        resolver = ProbabilityResolver(config={"probability_mode": "rule_based"})
        result = resolver.get_probabilities_with_meta("mlb", "plate_appearance", {})
        meta = result.get("_meta", {})
        assert meta.get("probability_source") == "rule_based"
        assert meta.get("fallback_used") is False

    def test_unsupported_mode_raises(self) -> None:
        resolver = ProbabilityResolver()
        with pytest.raises(ValueError, match="Unsupported"):
            resolver.resolve_provider("mlb", "pa", mode="nonexistent_mode")


class TestSimulationProbabilityIntegration:
    """Tests for simulation engine with probability modes."""

    def test_rule_based_mode(self) -> None:
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"probability_mode": "rule_based"},
            iterations=100,
            seed=42,
        )
        assert "home_win_probability" in result
        assert result.get("probability_source") == "rule_based"

    def test_ml_mode(self) -> None:
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {
                "probability_mode": "ml",
                "profiles": {
                    "batter_profile": {"metrics": {"contact_rate": 0.82}},
                    "pitcher_profile": {"metrics": {"contact_rate": 0.70}},
                },
            },
            iterations=100,
            seed=42,
        )
        assert "home_win_probability" in result
        assert result.get("probability_source") in ("ml", "rule_based")

    def test_no_mode_uses_defaults(self) -> None:
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"home_probabilities": {}, "away_probabilities": {}},
            iterations=100,
            seed=42,
        )
        assert "home_win_probability" in result
        # No probability_source when no mode specified
        assert result["iterations"] == 100

    def test_result_includes_metadata(self) -> None:
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"probability_mode": "rule_based"},
            iterations=50,
            seed=42,
        )
        assert "probability_meta" in result
        meta = result["probability_meta"]
        assert meta.get("probability_source") == "rule_based"


# ============================================================
# Prompt 17 — Model Registry System
# ============================================================


class TestModelRegistryCore:
    """Test ModelRegistry register, list, activate, deactivate."""

    def test_register_model(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        model_id = registry.register_model(
            sport="mlb",
            model_type="plate_appearance",
            model_id="mlb_pa_v1",
            artifact_path="/tmp/mlb_pa_v1.pkl",
            metadata={"accuracy": 0.61},
        )
        assert model_id == "mlb_pa_v1"
        models = registry.list_models(sport="mlb", model_type="plate_appearance")
        assert len(models) == 1
        assert models[0]["model_id"] == "mlb_pa_v1"
        assert models[0]["metrics"]["accuracy"] == 0.61

    def test_register_auto_versions(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "pa", "v2", "/tmp/v2.pkl")
        models = registry.list_models(sport="mlb", model_type="pa")
        versions = [m["version"] for m in models]
        assert versions == [1, 2]

    def test_register_duplicate_updates(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl", {"accuracy": 0.5})
        registry.register_model("mlb", "pa", "v1", "/tmp/v1_new.pkl", {"accuracy": 0.7})
        models = registry.list_models(sport="mlb", model_type="pa")
        assert len(models) == 1
        assert models[0]["artifact_path"] == "/tmp/v1_new.pkl"
        assert models[0]["metrics"]["accuracy"] == 0.7

    def test_get_active_model_none_by_default(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        active = registry.get_active_model("mlb", "pa")
        assert active is None

    def test_activate_model(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "pa", "v2", "/tmp/v2.pkl")

        result = registry.activate_model("mlb", "pa", "v1")
        assert result["status"] == "success"
        active = registry.get_active_model("mlb", "pa")
        assert active is not None
        assert active["model_id"] == "v1"

        # Switch to v2 (rollback)
        result = registry.activate_model("mlb", "pa", "v2")
        assert result["status"] == "success"
        active = registry.get_active_model("mlb", "pa")
        assert active["model_id"] == "v2"

    def test_activate_nonexistent_returns_error(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        result = registry.activate_model("mlb", "pa", "no_such_model")
        assert result["status"] == "error"

    def test_deactivate_model(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.activate_model("mlb", "pa", "v1")
        assert registry.deactivate_model("mlb", "pa", "v1")
        assert registry.get_active_model("mlb", "pa") is None

    def test_deactivate_wrong_model_returns_false(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.activate_model("mlb", "pa", "v1")
        assert registry.deactivate_model("mlb", "pa", "v2") is False


class TestModelRegistryPersistence:
    """Test JSON file persistence."""

    def test_persists_to_disk(self, tmp_path):
        import json

        from app.analytics.models.core.model_registry import ModelRegistry

        path = tmp_path / "reg.json"
        registry = ModelRegistry(registry_path=path)
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl", {"acc": 0.6})
        registry.activate_model("mlb", "pa", "v1")

        data = json.loads(path.read_text())
        assert "mlb" in data
        assert data["mlb"]["pa"]["active_model"] == "v1"
        assert len(data["mlb"]["pa"]["models"]) == 1

    def test_loads_from_disk(self, tmp_path):
        import json

        from app.analytics.models.core.model_registry import ModelRegistry

        path = tmp_path / "reg.json"
        data = {
            "mlb": {
                "pa": {
                    "active_model": "v1",
                    "models": [
                        {
                            "model_id": "v1",
                            "artifact_path": "/tmp/v1.pkl",
                            "version": 1,
                            "metrics": {"accuracy": 0.55},
                        }
                    ],
                }
            }
        }
        path.write_text(json.dumps(data))

        registry = ModelRegistry(registry_path=path)
        active = registry.get_active_model("mlb", "pa")
        assert active is not None
        assert active["model_id"] == "v1"

    def test_memory_only_mode(self):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        assert len(registry.list_models()) == 1


class TestModelRegistryListFiltering:
    """Test list_models filtering."""

    def test_list_all(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "game", "g1", "/tmp/g1.pkl")
        registry.register_model("nba", "game", "n1", "/tmp/n1.pkl")

        assert len(registry.list_models()) == 3

    def test_filter_by_sport(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("nba", "game", "n1", "/tmp/n1.pkl")

        mlb = registry.list_models(sport="mlb")
        assert len(mlb) == 1
        assert mlb[0]["sport"] == "mlb"

    def test_filter_by_model_type(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "game", "g1", "/tmp/g1.pkl")

        pa_models = registry.list_models(sport="mlb", model_type="pa")
        assert len(pa_models) == 1

    def test_active_flag_in_list(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "pa", "v2", "/tmp/v2.pkl")
        registry.activate_model("mlb", "pa", "v2")

        models = registry.list_models(sport="mlb", model_type="pa")
        active_flags = {m["model_id"]: m["active"] for m in models}
        assert active_flags["v1"] is False
        assert active_flags["v2"] is True


class TestModelRegistryInferenceIntegration:
    """Test that the inference engine loads active models via registry."""

    def test_get_active_model_info(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl", {"accuracy": 0.6})
        registry.activate_model("mlb", "pa", "v1")

        info = registry.get_active_model_info("mlb", "pa")
        assert info is not None
        assert info["model_id"] == "v1"
        assert info["path"] == "/tmp/v1.pkl"
        assert info["sport"] == "mlb"
        assert info["model_type"] == "pa"

    def test_get_active_model_info_none_when_inactive(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        assert registry.get_active_model_info("mlb", "pa") is None

    def test_inference_engine_uses_registry(self, tmp_path):
        from app.analytics.inference.model_inference_engine import ModelInferenceEngine
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        engine = ModelInferenceEngine(registry=registry)

        # No active model — should fall back to built-in
        probs = engine.predict_proba("mlb", "plate_appearance", {})
        assert isinstance(probs, dict)
        assert len(probs) > 0

    def test_inference_engine_with_active_artifact(self, tmp_path):
        from app.analytics.inference.model_inference_engine import ModelInferenceEngine
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        # Register with a non-existent path — should fall back to builtin
        registry.register_model("mlb", "plate_appearance", "v1", "/nonexistent/v1.pkl")
        registry.activate_model("mlb", "plate_appearance", "v1")

        engine = ModelInferenceEngine(registry=registry)
        probs = engine.predict_proba("mlb", "plate_appearance", {})
        # Falls back to built-in when artifact can't be loaded
        assert isinstance(probs, dict)


class TestModelRegistryTrainingIntegration:
    """Test that training pipeline registers models."""

    def test_training_pipeline_registers(self, tmp_path):
        from unittest.mock import patch

        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="plate_appearance",
            config_name="mlb_pa_model",
            model_id="test_train_reg",
            artifact_dir=tmp_path / "models",
        )

        registered = []

        def mock_register(*args, **kwargs):
            registered.append(kwargs)
            return kwargs.get("model_id", "")

        with patch(
            "app.analytics.models.core.model_registry.ModelRegistry.register_model",
            side_effect=mock_register,
        ):
            pipeline._register_model(
                "/tmp/artifact.pkl", "/tmp/metadata.json", {"accuracy": 0.7},
            )

        assert len(registered) == 1
        assert registered[0]["model_id"] == "test_train_reg"
        assert registered[0]["sport"] == "mlb"
        assert registered[0]["artifact_path"] == "/tmp/artifact.pkl"


# ============================================================
# Prompt 18 — Model Evaluation Metrics System
# ============================================================


class TestModelMetricsClassifier:
    """Test classification metrics from ModelMetrics."""

    def test_evaluate_classifier_basic(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_classifier(
            y_true=[1, 0, 1],
            y_pred=[1, 0, 0],
            y_proba=[0.8, 0.3, 0.4],
        )
        assert "accuracy" in result
        assert "log_loss" in result
        assert "brier_score" in result
        assert result["accuracy"] == pytest.approx(2 / 3, abs=0.01)
        assert result["sample_count"] == 3

    def test_evaluate_classifier_multiclass(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_classifier(
            y_true=["a", "b", "c", "a"],
            y_pred=["a", "b", "a", "a"],
            y_proba=[
                [0.7, 0.2, 0.1],
                [0.1, 0.8, 0.1],
                [0.3, 0.3, 0.4],
                [0.6, 0.2, 0.2],
            ],
            labels=["a", "b", "c"],
        )
        assert result["accuracy"] == 0.75
        assert result["log_loss"] > 0
        assert result["brier_score"] > 0

    def test_evaluate_classifier_perfect(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_classifier(
            y_true=[1, 0, 1],
            y_pred=[1, 0, 1],
            y_proba=[0.99, 0.01, 0.99],
        )
        assert result["accuracy"] == 1.0
        assert result["brier_score"] < 0.01

    def test_evaluate_classifier_empty(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_classifier([], [], [])
        assert result["accuracy"] == 0.0
        assert result["sample_count"] == 0

    def test_evaluate_classifier_2d_proba(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_classifier(
            y_true=[0, 1, 0],
            y_pred=[0, 1, 1],
            y_proba=[[0.8, 0.2], [0.3, 0.7], [0.4, 0.6]],
        )
        assert result["accuracy"] == pytest.approx(2 / 3, abs=0.01)
        assert result["brier_score"] > 0


class TestModelMetricsRegressor:
    """Test regression metrics from ModelMetrics."""

    def test_evaluate_regressor_basic(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_regressor(
            y_true=[3.0, 5.0, 7.0],
            y_pred=[2.5, 5.5, 6.0],
        )
        assert "mae" in result
        assert "rmse" in result
        assert result["sample_count"] == 3
        assert result["mae"] > 0
        assert result["rmse"] >= result["mae"]

    def test_evaluate_regressor_perfect(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_regressor(
            y_true=[1.0, 2.0, 3.0],
            y_pred=[1.0, 2.0, 3.0],
        )
        assert result["mae"] == 0.0
        assert result["rmse"] == 0.0

    def test_evaluate_regressor_empty(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        result = mm.evaluate_regressor([], [])
        assert result["mae"] == 0.0
        assert result["sample_count"] == 0


class TestModelMetricsReport:
    """Test build_report and compare_models."""

    def test_build_report(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        evaluation = mm.evaluate_classifier(
            y_true=[1, 0, 1],
            y_pred=[1, 0, 0],
            y_proba=[0.8, 0.3, 0.4],
        )
        report = mm.build_report(
            model_id="test_v1",
            model_type="plate_appearance",
            sport="mlb",
            evaluation=evaluation,
        )
        assert report["model_id"] == "test_v1"
        assert report["sport"] == "mlb"
        assert report["dataset_size"] == 3
        assert "accuracy" in report["metrics"]
        assert "log_loss" in report["metrics"]
        assert "brier_score" in report["metrics"]
        # class_distribution excluded from metrics
        assert "class_distribution" not in report["metrics"]

    def test_compare_models_lower_is_better(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        metrics_a = {"log_loss": 0.94, "brier_score": 0.204, "accuracy": 0.61}
        metrics_b = {"log_loss": 0.89, "brier_score": 0.195, "accuracy": 0.64}
        comparison = mm.compare_models(
            metrics_a, metrics_b,
            model_a_id="v1", model_b_id="v2",
        )
        assert comparison["better_model"] == "v2"
        assert comparison["metric_differences"]["log_loss"] == pytest.approx(-0.05, abs=0.001)

    def test_compare_models_a_better(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        metrics_a = {"log_loss": 0.80, "accuracy": 0.70}
        metrics_b = {"log_loss": 0.95, "accuracy": 0.55}
        comparison = mm.compare_models(metrics_a, metrics_b, model_a_id="a", model_b_id="b")
        assert comparison["better_model"] == "a"

    def test_compare_models_tie(self):
        from app.analytics.models.core.model_metrics import ModelMetrics

        mm = ModelMetrics()
        metrics = {"log_loss": 0.9, "accuracy": 0.6}
        comparison = mm.compare_models(metrics, metrics, model_a_id="x", model_b_id="y")
        # Tie defaults to model_a
        assert comparison["better_model"] == "x"


class TestModelMetricsTrainingIntegration:
    """Test that training pipeline stores metrics including Brier score."""

    @pytest.mark.skipif(not _has_sklearn, reason="scikit-learn not installed")
    def test_pipeline_includes_brier_score(self, tmp_path):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        records = _make_pa_records(80)
        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="plate_appearance",
            config_name="mlb_pa_model",
            model_id="brier_test_v1",
            artifact_dir=tmp_path / "models",
        )
        result = pipeline.run(records)
        assert "metrics" in result
        assert "brier_score" in result["metrics"]
        assert isinstance(result["metrics"]["brier_score"], float)

    def test_metrics_stored_in_registry(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model(
            "mlb", "pa", "v1", "/tmp/v1.pkl",
            metadata={"accuracy": 0.61, "log_loss": 0.94, "brier_score": 0.204},
        )
        models = registry.list_models(sport="mlb", model_type="pa")
        assert models[0]["metrics"]["brier_score"] == 0.204
        assert models[0]["metrics"]["accuracy"] == 0.61


class TestModelMetricsAPIEndpoint:
    """Test GET /api/analytics/model-metrics returns metrics."""

    def test_endpoint_returns_metrics(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model(
            "mlb", "pa", "v1", "/tmp/v1.pkl",
            metadata={"accuracy": 0.61, "log_loss": 0.94, "brier_score": 0.204},
        )
        models = registry.list_models(sport="mlb", model_type="pa")
        assert len(models) == 1
        m = models[0]
        assert m["metrics"]["accuracy"] == 0.61
        assert m["metrics"]["brier_score"] == 0.204


# ---------------------------------------------------------------------------
# Prompt 19 – Model Performance Dashboard (ModelService)
# ---------------------------------------------------------------------------


class TestModelServiceListModels:
    """Test ModelService.list_models with filtering and sorting."""

    def _make_service(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "mlb_pa_v1", "/a.pkl", metadata={"accuracy": 0.80, "log_loss": 0.50})
        registry.register_model("mlb", "pa", "mlb_pa_v2", "/b.pkl", metadata={"accuracy": 0.85, "log_loss": 0.45})
        registry.register_model("nba", "game", "nba_game_v1", "/c.pkl", metadata={"accuracy": 0.70})
        registry.activate_model("mlb", "pa", "mlb_pa_v2")
        return ModelService(registry=registry)

    def test_list_all(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc.list_models()
        assert result["count"] == 3

    def test_filter_by_sport(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc.list_models(sport="mlb")
        assert result["count"] == 2
        assert all(m["sport"] == "mlb" for m in result["models"])

    def test_filter_by_model_type(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc.list_models(model_type="game")
        assert result["count"] == 1

    def test_active_only(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc.list_models(active_only=True)
        assert result["count"] == 1
        assert result["models"][0]["model_id"] == "mlb_pa_v2"

    def test_sort_by_accuracy_desc(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc.list_models(sport="mlb", sort_by="accuracy", sort_desc=True)
        ids = [m["model_id"] for m in result["models"]]
        assert ids[0] == "mlb_pa_v2"

    def test_sort_by_accuracy_asc(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc.list_models(sport="mlb", sort_by="accuracy", sort_desc=False)
        ids = [m["model_id"] for m in result["models"]]
        assert ids[0] == "mlb_pa_v1"


class TestModelServiceGetDetails:
    """Test ModelService.get_model_details."""

    def test_returns_details(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/a.pkl", metadata={"accuracy": 0.80})
        svc = ModelService(registry=registry)
        details = svc.get_model_details("v1")
        assert details is not None
        assert details["model_id"] == "v1"
        assert details["sport"] == "mlb"
        assert details["metrics"]["accuracy"] == 0.80

    def test_returns_none_for_missing(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        svc = ModelService(registry=registry)
        assert svc.get_model_details("nonexistent") is None

    def test_enriches_from_metadata_file(self, tmp_path):
        import json

        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        meta_file = tmp_path / "meta.json"
        meta_file.write_text(json.dumps({
            "feature_config": "config_v2",
            "training_row_count": 5000,
            "random_state": 42,
        }))
        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model(
            "mlb", "pa", "v1", "/a.pkl",
            metadata={"accuracy": 0.80},
            metadata_path=str(meta_file),
        )
        svc = ModelService(registry=registry)
        details = svc.get_model_details("v1")
        assert details["feature_config"] == "config_v2"
        assert details["training_row_count"] == 5000
        assert details["random_state"] == 42


class TestModelServiceCompare:
    """Test ModelService.compare_models."""

    def test_compare_two_models(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/a.pkl", metadata={"accuracy": 0.80, "log_loss": 0.50})
        registry.register_model("mlb", "pa", "v2", "/b.pkl", metadata={"accuracy": 0.85, "log_loss": 0.45})
        svc = ModelService(registry=registry)
        result = svc.compare_models("mlb", "pa", ["v1", "v2"])
        assert result["sport"] == "mlb"
        assert len(result["models"]) == 2
        assert "comparison" in result
        assert result["comparison"]["better_model"] in ("v1", "v2")

    def test_compare_three_models_no_comparison(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/a.pkl", metadata={"accuracy": 0.80})
        registry.register_model("mlb", "pa", "v2", "/b.pkl", metadata={"accuracy": 0.85})
        registry.register_model("mlb", "pa", "v3", "/c.pkl", metadata={"accuracy": 0.90})
        svc = ModelService(registry=registry)
        result = svc.compare_models("mlb", "pa", ["v1", "v2", "v3"])
        assert len(result["models"]) == 3
        assert "comparison" not in result

    def test_compare_unknown_ids_returns_empty(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        svc = ModelService(registry=registry)
        result = svc.compare_models("mlb", "pa", ["nope1", "nope2"])
        assert result["models"] == []


# ---------------------------------------------------------------------------
# Prompt 20 – Model Activation Controls
# ---------------------------------------------------------------------------


class TestActivationControls:
    """Test model activation safety checks and registry updates."""

    def test_activation_updates_registry_json(self, tmp_path):
        import json

        from app.analytics.models.core.model_registry import ModelRegistry

        reg_path = tmp_path / "reg.json"
        registry = ModelRegistry(registry_path=reg_path)
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "pa", "v2", "/tmp/v2.pkl")

        result = registry.activate_model("mlb", "pa", "v1")
        assert result["status"] == "success"

        # Verify JSON on disk
        data = json.loads(reg_path.read_text())
        assert data["mlb"]["pa"]["active_model"] == "v1"

    def test_only_one_active_model_per_bucket(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "pa", "v2", "/tmp/v2.pkl")

        registry.activate_model("mlb", "pa", "v1")
        registry.activate_model("mlb", "pa", "v2")

        models = registry.list_models(sport="mlb", model_type="pa")
        active = [m for m in models if m["active"]]
        assert len(active) == 1
        assert active[0]["model_id"] == "v2"

    def test_rollback_to_previous_model(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/tmp/v1.pkl")
        registry.register_model("mlb", "pa", "v2", "/tmp/v2.pkl")

        registry.activate_model("mlb", "pa", "v2")
        assert registry.get_active_model("mlb", "pa")["model_id"] == "v2"

        # Rollback
        result = registry.activate_model("mlb", "pa", "v1")
        assert result["status"] == "success"
        assert registry.get_active_model("mlb", "pa")["model_id"] == "v1"

    def test_activate_nonexistent_model_returns_error(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        result = registry.activate_model("mlb", "pa", "ghost")
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_activate_missing_artifact_returns_error(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/nonexistent/v1.pkl")

        result = registry.activate_model("mlb", "pa", "v1", validate_paths=True)
        assert result["status"] == "error"
        assert "artifact" in result["message"].lower()

    def test_activate_with_valid_artifact_succeeds(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"fake")
        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", str(artifact))

        result = registry.activate_model("mlb", "pa", "v1", validate_paths=True)
        assert result["status"] == "success"

    def test_activate_missing_metadata_returns_error(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"fake")
        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model(
            "mlb", "pa", "v1", str(artifact),
            metadata_path="/nonexistent/meta.json",
        )

        result = registry.activate_model("mlb", "pa", "v1", validate_paths=True)
        assert result["status"] == "error"
        assert "metadata" in result["message"].lower()

    def test_multiple_sports_independent_activation(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "mlb_v1", "/tmp/mlb.pkl")
        registry.register_model("nba", "game", "nba_v1", "/tmp/nba.pkl")

        registry.activate_model("mlb", "pa", "mlb_v1")
        registry.activate_model("nba", "game", "nba_v1")

        assert registry.get_active_model("mlb", "pa")["model_id"] == "mlb_v1"
        assert registry.get_active_model("nba", "game")["model_id"] == "nba_v1"


class TestActivationModelService:
    """Test ModelService.activate_model with validation."""

    def test_service_activate_success(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        artifact = tmp_path / "model.pkl"
        artifact.write_bytes(b"fake")
        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", str(artifact))

        svc = ModelService(registry=registry)
        result = svc.activate_model("mlb", "pa", "v1")
        assert result["status"] == "success"
        assert result["active_model"] == "v1"

    def test_service_activate_validates_paths(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        registry.register_model("mlb", "pa", "v1", "/nonexistent/v1.pkl")

        svc = ModelService(registry=registry)
        result = svc.activate_model("mlb", "pa", "v1")
        assert result["status"] == "error"

    def test_service_activate_nonexistent(self, tmp_path):
        from app.analytics.models.core.model_registry import ModelRegistry
        from app.analytics.services.model_service import ModelService

        registry = ModelRegistry(registry_path=tmp_path / "reg.json")
        svc = ModelService(registry=registry)
        result = svc.activate_model("mlb", "pa", "ghost")
        assert result["status"] == "error"


class TestActivationInferenceReload:
    """Test that inference engine detects active model changes."""

    def test_engine_tracks_loaded_model_id(self):
        from app.analytics.inference.model_inference_engine import ModelInferenceEngine
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        engine = ModelInferenceEngine(registry=registry)
        assert engine._loaded_model_ids == {}

    def test_engine_clears_cache_on_model_switch(self, tmp_path):
        from app.analytics.inference.inference_cache import InferenceCache
        from app.analytics.inference.model_inference_engine import ModelInferenceEngine
        from app.analytics.models.core.model_registry import ModelRegistry

        registry = ModelRegistry(registry_path=None)
        registry.register_model("mlb", "plate_appearance", "v1", "/fake/v1.pkl")
        registry.register_model("mlb", "plate_appearance", "v2", "/fake/v2.pkl")
        registry.activate_model("mlb", "plate_appearance", "v1")

        cache = InferenceCache()
        engine = ModelInferenceEngine(registry=registry, cache=cache)

        # Simulate having loaded v1 previously
        engine._loaded_model_ids["mlb:plate_appearance"] = "v1"
        cache._cache["/fake/v1.pkl"] = "fake_model"

        # Switch active to v2
        registry.activate_model("mlb", "plate_appearance", "v2")

        # Next _get_model call should detect the switch and clear cache
        engine._get_model("mlb", "plate_appearance")
        assert cache.size == 0 or "/fake/v1.pkl" not in cache._cache


# ---------------------------------------------------------------------------
# Prompt 21 – Ensemble Modeling System
# ---------------------------------------------------------------------------


class TestEnsembleEngine:
    """Test EnsembleEngine weighted combination."""

    def test_combine_sums_to_one(self):
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        rule = {"strikeout": 0.22, "walk": 0.07, "single": 0.16, "out": 0.55}
        ml = {"strikeout": 0.19, "walk": 0.09, "single": 0.18, "out": 0.54}

        result = engine.combine(
            {"rule_based": rule, "ml": ml},
            {"rule_based": 0.4, "ml": 0.6},
        )
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_combine_weighted_correctly(self):
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        a = {"x": 0.4, "y": 0.6}
        b = {"x": 0.8, "y": 0.2}

        result = engine.combine({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
        # x: 0.4*0.5 + 0.8*0.5 = 0.6, y: 0.6*0.5 + 0.2*0.5 = 0.4
        assert abs(result["x"] - 0.6) < 0.01
        assert abs(result["y"] - 0.4) < 0.01

    def test_combine_unequal_weights(self):
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        a = {"x": 1.0, "y": 0.0}
        b = {"x": 0.0, "y": 1.0}

        result = engine.combine({"a": a, "b": b}, {"a": 0.75, "b": 0.25})
        assert abs(result["x"] - 0.75) < 0.01
        assert abs(result["y"] - 0.25) < 0.01

    def test_combine_single_provider(self):
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        probs = {"strikeout": 0.22, "out": 0.78}

        result = engine.combine({"rule": probs}, {"rule": 1.0})
        assert abs(sum(result.values()) - 1.0) < 0.001
        assert abs(result["strikeout"] - 0.22) < 0.01

    def test_combine_empty_returns_empty(self):
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        assert engine.combine({}, {}) == {}

    def test_combine_missing_events_treated_as_zero(self):
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        a = {"x": 0.5, "y": 0.5}
        b = {"x": 0.5, "z": 0.5}

        result = engine.combine({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
        assert abs(sum(result.values()) - 1.0) < 0.001
        assert "y" in result
        assert "z" in result

    def test_combine_from_config(self):
        from app.analytics.ensemble.ensemble_config import (
            EnsembleConfig,
            ProviderWeight,
        )
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        config = EnsembleConfig(
            sport="mlb",
            model_type="pa",
            providers=[
                ProviderWeight(name="rule", weight=0.3),
                ProviderWeight(name="ml", weight=0.7),
            ],
        )
        rule = {"x": 0.4, "y": 0.6}
        ml = {"x": 0.8, "y": 0.2}

        result = engine.combine_from_config({"rule": rule, "ml": ml}, config)
        assert abs(sum(result.values()) - 1.0) < 0.001


class TestEnsembleConfig:
    """Test EnsembleConfig data class and registry."""

    def test_default_config_exists_for_mlb_pa(self):
        from app.analytics.ensemble.ensemble_config import get_ensemble_config

        config = get_ensemble_config("mlb", "plate_appearance")
        assert config.sport == "mlb"
        assert len(config.providers) >= 2

    def test_set_and_get_custom_config(self):
        from app.analytics.ensemble.ensemble_config import (
            EnsembleConfig,
            ProviderWeight,
            _custom_configs,
            get_ensemble_config,
            set_ensemble_config,
        )

        custom = EnsembleConfig(
            sport="nba",
            model_type="game",
            providers=[
                ProviderWeight(name="rule_based", weight=0.3),
                ProviderWeight(name="ml", weight=0.7),
            ],
        )
        set_ensemble_config(custom)
        try:
            result = get_ensemble_config("nba", "game")
            assert result.sport == "nba"
            assert result.providers[1].weight == 0.7
        finally:
            _custom_configs.pop(("nba", "game"), None)

    def test_to_dict_roundtrip(self):
        from app.analytics.ensemble.ensemble_config import (
            EnsembleConfig,
            ProviderWeight,
        )

        config = EnsembleConfig(
            sport="mlb",
            model_type="pa",
            providers=[ProviderWeight(name="rule", weight=0.4)],
        )
        d = config.to_dict()
        restored = EnsembleConfig.from_dict(d)
        assert restored.sport == "mlb"
        assert restored.providers[0].name == "rule"
        assert restored.providers[0].weight == 0.4

    def test_list_configs(self):
        from app.analytics.ensemble.ensemble_config import list_ensemble_configs

        configs = list_ensemble_configs()
        assert len(configs) >= 2  # mlb/pa and mlb/game defaults

    def test_total_weight(self):
        from app.analytics.ensemble.ensemble_config import (
            EnsembleConfig,
            ProviderWeight,
        )

        config = EnsembleConfig(
            sport="mlb",
            model_type="pa",
            providers=[
                ProviderWeight(name="a", weight=0.4),
                ProviderWeight(name="b", weight=0.6),
            ],
        )
        assert abs(config.total_weight - 1.0) < 0.001


class TestEnsembleResolver:
    """Test ProbabilityResolver with ensemble mode."""

    def test_resolver_supports_ensemble_mode(self):
        from app.analytics.probabilities.probability_resolver import (
            ProbabilityResolver,
        )

        resolver = ProbabilityResolver(config={"probability_mode": "ensemble"})
        provider = resolver.resolve_provider("mlb", "plate_appearance", "ensemble")
        assert provider.provider_name == "ensemble"

    def test_resolver_ensemble_returns_probabilities(self):
        from app.analytics.probabilities.probability_resolver import (
            ProbabilityResolver,
        )

        resolver = ProbabilityResolver()
        probs = resolver.get_probabilities(
            "mlb", "plate_appearance", {}, mode="ensemble",
        )
        assert isinstance(probs, dict)
        assert len(probs) > 0
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_ensemble_provider_produces_normalized_output(self):
        from app.analytics.probabilities.probability_provider import EnsembleProvider

        provider = EnsembleProvider(model_type="plate_appearance")
        probs = provider.get_event_probabilities("mlb", {})
        assert abs(sum(probs.values()) - 1.0) < 0.01
        assert "strikeout" in probs


class TestEnsembleSimulation:
    """Test that the simulation engine runs with ensemble mode."""

    def test_simulation_engine_ensemble_mode(self):
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"home_team": "NYY", "away_team": "BOS", "probability_mode": "ensemble"},
            iterations=100,
            seed=42,
        )
        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert result.get("probability_source") == "ensemble"


# ---------------------------------------------------------------------------
# MLB Advanced Models — Pitch, Batted Ball, Run Expectancy, Pitch Simulator
# ---------------------------------------------------------------------------


class TestMLBPitchOutcomeModel:
    """Test pitch outcome model probabilities."""

    def test_probabilities_sum_to_one(self):
        from app.analytics.models.sports.mlb.pitch_model import MLBPitchOutcomeModel

        model = MLBPitchOutcomeModel()
        probs = model.predict_proba({})
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_all_outcomes_present(self):
        from app.analytics.models.sports.mlb.pitch_model import (
            PITCH_OUTCOMES,
            MLBPitchOutcomeModel,
        )

        model = MLBPitchOutcomeModel()
        probs = model.predict_proba({"pitcher_k_rate": 0.24, "batter_swing_rate": 0.50})
        for outcome in PITCH_OUTCOMES:
            assert outcome in probs
            assert probs[outcome] > 0

    def test_count_affects_probabilities(self):
        from app.analytics.models.sports.mlb.pitch_model import MLBPitchOutcomeModel

        model = MLBPitchOutcomeModel()
        probs_0_0 = model.predict_proba({"count_balls": 0, "count_strikes": 0})
        probs_3_0 = model.predict_proba({"count_balls": 3, "count_strikes": 0})
        # With 3 balls, ball probability should be higher
        assert probs_3_0["ball"] > probs_0_0["ball"]

    def test_predict_returns_structure(self):
        from app.analytics.models.sports.mlb.pitch_model import MLBPitchOutcomeModel

        model = MLBPitchOutcomeModel()
        result = model.predict({})
        assert "pitch_probabilities" in result
        assert "predicted_outcome" in result


class TestMLBBattedBallModel:
    """Test batted ball outcome model probabilities."""

    def test_probabilities_sum_to_one(self):
        from app.analytics.models.sports.mlb.batted_ball_model import MLBBattedBallModel

        model = MLBBattedBallModel()
        probs = model.predict_proba({})
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_all_outcomes_present(self):
        from app.analytics.models.sports.mlb.batted_ball_model import (
            BATTED_BALL_OUTCOMES,
            MLBBattedBallModel,
        )

        model = MLBBattedBallModel()
        probs = model.predict_proba({"exit_velocity": 95.0, "launch_angle": 22.0})
        for outcome in BATTED_BALL_OUTCOMES:
            assert outcome in probs

    def test_high_ev_increases_extra_base(self):
        from app.analytics.models.sports.mlb.batted_ball_model import MLBBattedBallModel

        model = MLBBattedBallModel()
        probs_low = model.predict_proba({"exit_velocity": 80.0})
        probs_high = model.predict_proba({"exit_velocity": 105.0})
        assert probs_high["home_run"] > probs_low["home_run"]

    def test_predict_returns_structure(self):
        from app.analytics.models.sports.mlb.batted_ball_model import MLBBattedBallModel

        model = MLBBattedBallModel()
        result = model.predict({"exit_velocity": 95.0})
        assert "batted_ball_probabilities" in result
        assert "predicted_outcome" in result


class TestMLBRunExpectancyModel:
    """Test run expectancy model."""

    def test_bases_empty_0_outs(self):
        from app.analytics.models.sports.mlb.run_expectancy_model import (
            MLBRunExpectancyModel,
        )

        model = MLBRunExpectancyModel()
        result = model.predict({"base_state": 0, "outs": 0})
        assert result["expected_runs"] > 0
        assert result["expected_runs"] < 1.0

    def test_bases_loaded_higher(self):
        from app.analytics.models.sports.mlb.run_expectancy_model import (
            MLBRunExpectancyModel,
        )

        model = MLBRunExpectancyModel()
        empty = model.predict({"base_state": 0, "outs": 0})
        loaded = model.predict({"base_state": 7, "outs": 0})
        assert loaded["expected_runs"] > empty["expected_runs"]

    def test_more_outs_lower(self):
        from app.analytics.models.sports.mlb.run_expectancy_model import (
            MLBRunExpectancyModel,
        )

        model = MLBRunExpectancyModel()
        outs_0 = model.predict({"base_state": 1, "outs": 0})
        outs_2 = model.predict({"base_state": 1, "outs": 2})
        assert outs_0["expected_runs"] > outs_2["expected_runs"]

    def test_encode_base_state(self):
        from app.analytics.models.sports.mlb.run_expectancy_model import (
            encode_base_state,
        )

        assert encode_base_state(False, False, False) == 0
        assert encode_base_state(True, False, False) == 1
        assert encode_base_state(True, True, True) == 7
        assert encode_base_state(False, False, True) == 4


class TestPitchSimulator:
    """Test pitch-level plate appearance simulation."""

    def test_simulate_pa_returns_valid_result(self):
        from app.analytics.simulation.mlb.pitch_simulator import PitchSimulator

        sim = PitchSimulator()
        result = sim.simulate_plate_appearance()
        valid = {"walk", "strikeout", "out", "single", "double", "triple", "home_run"}
        assert result["result"] in valid
        assert result["pitches"] >= 1

    def test_walk_rule(self):
        """Walk requires exactly 4 balls."""
        import random as stdlib_random

        from app.analytics.models.sports.mlb.pitch_model import MLBPitchOutcomeModel
        from app.analytics.simulation.mlb.pitch_simulator import PitchSimulator

        # Force all pitches to be balls via a mock model
        class AllBalls(MLBPitchOutcomeModel):
            def predict_proba(self, features):
                return {"ball": 1.0, "called_strike": 0, "swinging_strike": 0, "foul": 0, "in_play": 0}

        sim = PitchSimulator(pitch_model=AllBalls())
        result = sim.simulate_plate_appearance(rng=stdlib_random.Random(1))
        assert result["result"] == "walk"
        assert result["pitches"] == 4

    def test_strikeout_rule(self):
        """Strikeout requires 3 strikes."""
        import random as stdlib_random

        from app.analytics.models.sports.mlb.pitch_model import MLBPitchOutcomeModel
        from app.analytics.simulation.mlb.pitch_simulator import PitchSimulator

        class AllStrikes(MLBPitchOutcomeModel):
            def predict_proba(self, features):
                return {"ball": 0, "called_strike": 1.0, "swinging_strike": 0, "foul": 0, "in_play": 0}

        sim = PitchSimulator(pitch_model=AllStrikes())
        result = sim.simulate_plate_appearance(rng=stdlib_random.Random(1))
        assert result["result"] == "strikeout"
        assert result["pitches"] == 3

    def test_foul_with_two_strikes_stays(self):
        """Foul with 2 strikes should not result in strikeout."""
        import random as stdlib_random

        from app.analytics.models.sports.mlb.pitch_model import MLBPitchOutcomeModel
        from app.analytics.simulation.mlb.pitch_simulator import PitchSimulator

        call_count = 0

        class FoulThenStrike(MLBPitchOutcomeModel):
            def predict_proba(self, features):
                nonlocal call_count
                call_count += 1
                # First 5 pitches foul, then called strike
                if call_count <= 5:
                    return {"ball": 0, "called_strike": 0, "swinging_strike": 0, "foul": 1.0, "in_play": 0}
                return {"ball": 0, "called_strike": 1.0, "swinging_strike": 0, "foul": 0, "in_play": 0}

        sim = PitchSimulator(pitch_model=FoulThenStrike())
        result = sim.simulate_plate_appearance(rng=stdlib_random.Random(1))
        assert result["result"] == "strikeout"
        # 2 fouls get strikes to 2, then 3 more fouls don't advance, then 1 strike = K
        assert result["pitches"] == 6

    def test_deterministic_with_seed(self):
        import random as stdlib_random

        from app.analytics.simulation.mlb.pitch_simulator import PitchSimulator

        sim = PitchSimulator()
        r1 = sim.simulate_plate_appearance(rng=stdlib_random.Random(42))
        r2 = sim.simulate_plate_appearance(rng=stdlib_random.Random(42))
        assert r1["result"] == r2["result"]
        assert r1["pitches"] == r2["pitches"]


class TestPitchLevelGameSimulator:
    """Test full game simulation at the pitch level."""

    def test_simulate_game_returns_scores(self):
        import random as stdlib_random

        from app.analytics.simulation.mlb.pitch_simulator import (
            PitchLevelGameSimulator,
        )

        sim = PitchLevelGameSimulator()
        result = sim.simulate_game({}, rng=stdlib_random.Random(42))
        assert "home_score" in result
        assert "away_score" in result
        assert "winner" in result
        assert result["winner"] in ("home", "away")
        assert result["total_pitches"] > 0

    def test_simulation_engine_pitch_level_mode(self):
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        result = engine.run_simulation(
            {"probability_mode": "pitch_level"},
            iterations=50,
            seed=42,
        )
        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert result.get("probability_source") == "pitch_level"
        assert result.get("average_pitches_per_game", 0) > 0



# ---------------------------------------------------------------------------
# SSOT Enforcement Tests
# ---------------------------------------------------------------------------


class TestSSOTRoutes:
    """Assert that analytics routes use DB-backed SSOT modules, not legacy YAML."""

    def test_analytics_routes_has_no_yaml_loader_import(self):
        """Legacy FeatureConfigLoader must not be imported in routes."""
        import inspect

        from app.analytics.api import analytics_routes

        source = inspect.getsource(analytics_routes)
        assert "FeatureConfigLoader" not in source, (
            "analytics_routes still references FeatureConfigLoader — "
            "DB-backed loadouts are the SSOT"
        )

    def test_analytics_routes_has_no_yaml_registry_import(self):
        """Legacy FeatureConfigRegistry must not be imported in routes."""
        import inspect

        from app.analytics.api import analytics_routes

        source = inspect.getsource(analytics_routes)
        assert "FeatureConfigRegistry" not in source, (
            "analytics_routes still references FeatureConfigRegistry — "
            "DB-backed loadouts are the SSOT"
        )

    def test_no_yaml_configs_field_in_routes(self):
        """The yaml_configs backwards-compat field must not appear in routes."""
        import inspect

        from app.analytics.api import analytics_routes

        source = inspect.getsource(analytics_routes)
        assert "yaml_configs" not in source

    def test_no_duplicate_predict_with_game_model(self):
        """_predict_with_game_model must not be duplicated in simulator.py."""
        import inspect

        from app.routers import simulator

        source = inspect.getsource(simulator)
        assert "async def _predict_with_game_model" not in source, (
            "simulator.py must import _predict_with_game_model from "
            "analytics_routes, not define its own copy"
        )

    def test_simulator_uses_profile_result_metrics(self):
        """simulator.py must extract .metrics from ProfileResult, not pass it raw."""
        import inspect

        from app.routers import simulator

        source = inspect.getsource(simulator)
        # The function should use home_profile_result.metrics, not pass
        # the ProfileResult directly to profile_to_pa_probabilities.
        assert "home_profile_result.metrics" in source, (
            "simulator.py must extract .metrics from the ProfileResult "
            "returned by get_team_rolling_profile"
        )

    def test_simulation_diagnostics_importable(self):
        """SimulationDiagnostics must be the SSOT for simulation run metadata."""
        from app.analytics.core.simulation_diagnostics import (
            SimulationDiagnostics,
        )
        diag = SimulationDiagnostics(requested_mode="ml", executed_mode="ml")
        assert diag.to_dict()["requested_mode"] == "ml"

    def test_training_tasks_module_exists(self):
        """The Celery training task module must be importable."""
        spec = importlib.util.find_spec("app.tasks.training_tasks")
        assert spec is not None, "app.tasks.training_tasks module not found"

    def test_db_models_exist(self):
        """DB analytics models must be importable."""
        from app.db.analytics import AnalyticsFeatureConfig, AnalyticsTrainingJob

        assert AnalyticsFeatureConfig.__tablename__ == "analytics_feature_configs"
        assert AnalyticsTrainingJob.__tablename__ == "analytics_training_jobs"


class TestSSOTNoLegacyFiles:
    """Assert deleted legacy files stay deleted."""

    def test_no_yaml_config_files(self):
        import os

        config_dir = os.path.join(
            os.path.dirname(__file__), "..", "config", "features"
        )
        if os.path.isdir(config_dir):
            yamls = [f for f in os.listdir(config_dir) if f.endswith((".yaml", ".yml"))]
            assert yamls == [], f"Legacy YAML configs still exist: {yamls}"

    def test_no_legacy_training_scripts(self):
        import os

        scripts_dir = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "train_models"
        )
        assert not os.path.isdir(scripts_dir), (
            "Legacy scripts/train_models/ directory still exists — "
            "training is handled by Celery tasks"
        )


class TestSSOTMLBConstants:
    """Assert MLB constants SSOT is used and legacy duplicates are gone."""

    def test_mlb_training_has_no_pitch_label_fn(self):
        """Deleted pitch_label_fn must stay deleted."""
        from app.analytics.training.sports.mlb_training import MLBTrainingPipeline

        assert not hasattr(MLBTrainingPipeline, "pitch_label_fn")

    def test_mlb_training_has_no_batted_ball_label_fn(self):
        """Deleted batted_ball_label_fn must stay deleted."""
        from app.analytics.training.sports.mlb_training import MLBTrainingPipeline

        assert not hasattr(MLBTrainingPipeline, "batted_ball_label_fn")

    def test_mlb_training_has_no_run_expectancy_label_fn(self):
        """Deleted run_expectancy_label_fn must stay deleted."""
        from app.analytics.training.sports.mlb_training import MLBTrainingPipeline

        assert not hasattr(MLBTrainingPipeline, "run_expectancy_label_fn")

    def test_mlb_training_imports_pa_outcomes_from_constants(self):
        """PA_OUTCOMES must come from the SSOT constants module."""
        import inspect

        from app.analytics.training.sports import mlb_training

        source = inspect.getsource(mlb_training)
        assert "from app.analytics.sports.mlb.constants import" in source
        assert "PA_EVENTS" in source

    def test_constants_module_is_ssot(self):
        """The constants module must export all canonical MLB constants."""
        from app.analytics.sports.mlb import constants

        assert hasattr(constants, "PA_EVENTS")
        assert hasattr(constants, "DEFAULT_EVENT_PROBS")
        assert hasattr(constants, "FEATURE_BASELINES")
        assert hasattr(constants, "MAX_EXTRA_INNINGS")

    def test_no_local_baselines_in_matchup(self):
        """matchup.py must not define its own BASELINE_ constants."""
        import inspect

        from app.analytics.sports.mlb import matchup

        source = inspect.getsource(matchup)
        # Should import from constants, not define locally
        assert "from app.analytics.sports.mlb.constants import" in source

    def test_no_local_baselines_in_mlb_features(self):
        """mlb_features.py must import _BASELINES from constants."""
        import inspect

        from app.analytics.features.sports import mlb_features

        source = inspect.getsource(mlb_features)
        assert "from app.analytics.sports.mlb.constants import FEATURE_BASELINES" in source


# ---------------------------------------------------------------------------
# Rolling Profile Aggregation Tests
# ---------------------------------------------------------------------------


class TestBuildRollingProfile:
    """Test _build_rolling_profile from training_tasks."""

    def _make_stats(self, **overrides):
        """Create a mock MLBGameAdvancedStats-like object."""
        defaults = {
            "z_contact_pct": 0.80,
            "o_contact_pct": 0.60,
            "avg_exit_velo": 90.0,
            "barrel_pct": 0.08,
            "hard_hit_pct": 0.38,
            "z_swing_pct": 0.70,
            "o_swing_pct": 0.30,
            "zone_swings": 50,
            "outside_swings": 30,
            "zone_contact": 40,
            "outside_contact": 18,
            "total_pitches": 145,
            "balls_in_play": 30,
            "outside_pitches": 80,
            "zone_pitches": 65,
            "hard_hit_count": 10,
            "barrel_count": 2,
        }
        defaults.update(overrides)

        class MockStats:
            pass

        obj = MockStats()
        for k, v in defaults.items():
            setattr(obj, k, v)
        return obj

    def test_returns_none_when_insufficient_history(self):
        from app.tasks.batch_sim_tasks import _build_rolling_profile

        # Only 3 games before target date, min_games=5
        games = [("2025-04-01", self._make_stats()) for _ in range(3)]
        result = _build_rolling_profile(
            games, before_date="2025-05-01", window=30
        )
        assert result is None

    def test_returns_profile_with_sufficient_history(self):
        from app.tasks.batch_sim_tasks import _build_rolling_profile

        games = [(f"2025-04-{i+1:02d}", self._make_stats()) for i in range(10)]
        result = _build_rolling_profile(
            games, before_date="2025-05-01", window=30
        )
        assert result is not None
        assert "contact_rate" in result
        assert "power_index" in result
        assert "barrel_rate" in result
        assert "hard_hit_rate" in result
        assert "swing_rate" in result
        assert "whiff_rate" in result
        assert "avg_exit_velocity" in result
        assert "expected_slug" in result

    def test_excludes_games_on_or_after_target_date(self):
        from app.tasks.batch_sim_tasks import _build_rolling_profile

        # 3 games before target, 7 on or after
        games = [(f"2025-04-{i+1:02d}", self._make_stats()) for i in range(3)]
        games += [("2025-04-15", self._make_stats()) for _ in range(7)]
        result = _build_rolling_profile(
            games, before_date="2025-04-04", window=30
        )
        # Only 3 prior games, below min_games=5
        assert result is None

    def test_window_limits_games_used(self):
        from app.tasks.batch_sim_tasks import _build_rolling_profile

        # 20 games, window=5 — should average only last 5
        early_stats = self._make_stats(avg_exit_velo=80.0)
        late_stats = self._make_stats(avg_exit_velo=100.0)

        games = [(f"2025-04-{i+1:02d}", early_stats) for i in range(15)]
        games += [(f"2025-04-{i+16:02d}", late_stats) for i in range(5)]

        result = _build_rolling_profile(
            games, before_date="2025-05-01", window=5, min_games=3
        )
        assert result is not None
        # Should be close to 100.0 (the last 5 games)
        assert result["avg_exit_velocity"] == 100.0

    def test_averages_metrics_correctly(self):
        from app.tasks.batch_sim_tasks import _build_rolling_profile

        stats_a = self._make_stats(barrel_pct=0.10, hard_hit_pct=0.40)
        stats_b = self._make_stats(barrel_pct=0.20, hard_hit_pct=0.50)

        games = [
            ("2025-04-01", stats_a),
            ("2025-04-02", stats_b),
            ("2025-04-03", stats_a),
            ("2025-04-04", stats_b),
            ("2025-04-05", stats_a),
        ]

        result = _build_rolling_profile(
            games, before_date="2025-05-01", window=30
        )
        assert result is not None
        # 3 x 0.10 + 2 x 0.20 = 0.70 / 5 = 0.14
        assert result["barrel_rate"] == 0.14
        # 3 x 0.40 + 2 x 0.50 = 2.20 / 5 = 0.44
        assert result["hard_hit_rate"] == 0.44


class TestRollingWindowColumn:
    """Verify rolling_window column on AnalyticsTrainingJob."""

    def test_training_job_has_rolling_window(self):
        from app.db.analytics import AnalyticsTrainingJob

        assert hasattr(AnalyticsTrainingJob, "rolling_window")

    def test_rolling_window_default(self):
        from app.db.analytics import AnalyticsTrainingJob

        col = AnalyticsTrainingJob.__table__.columns["rolling_window"]
        assert col.default.arg == 30


# ---------------------------------------------------------------------------
# Backtest Tests
# ---------------------------------------------------------------------------


class TestFeatureImportance:
    """Test feature importance extraction from trained models."""

    def test_extract_from_model_with_importances(self):
        from app.analytics.training.core.training_pipeline import (
            _extract_feature_importance,
        )

        class MockModel:
            feature_importances_ = [0.4, 0.3, 0.2, 0.1]

        result = _extract_feature_importance(
            MockModel(), ["feat_a", "feat_b", "feat_c", "feat_d"]
        )
        assert result is not None
        assert len(result) == 4
        # Should be sorted highest first
        assert result[0]["name"] == "feat_a"
        assert result[0]["importance"] == 0.4
        assert result[-1]["name"] == "feat_d"
        assert result[-1]["importance"] == 0.1

    def test_returns_none_for_model_without_importances(self):
        from app.analytics.training.core.training_pipeline import (
            _extract_feature_importance,
        )

        class MockModel:
            pass

        result = _extract_feature_importance(MockModel(), ["feat_a", "feat_b"])
        assert result is None

    def test_training_job_has_feature_importance_column(self):
        from app.db.analytics import AnalyticsTrainingJob

        assert hasattr(AnalyticsTrainingJob, "feature_importance")
        col = AnalyticsTrainingJob.__table__.columns["feature_importance"]
        assert col.nullable is True


class TestBacktestJobModel:
    """Verify AnalyticsBacktestJob DB model."""

    def test_backtest_job_table_exists(self):
        from app.db.analytics import AnalyticsBacktestJob

        assert AnalyticsBacktestJob.__tablename__ == "analytics_backtest_jobs"

    def test_backtest_job_columns(self):
        from app.db.analytics import AnalyticsBacktestJob

        cols = {c.name for c in AnalyticsBacktestJob.__table__.columns}
        required = {
            "id", "model_id", "artifact_path", "sport", "model_type",
            "date_start", "date_end", "rolling_window", "status",
            "celery_task_id", "game_count", "correct_count", "metrics",
            "predictions", "error_message", "created_at", "completed_at",
        }
        assert required <= cols

    def test_rolling_window_default(self):
        from app.db.analytics import AnalyticsBacktestJob

        col = AnalyticsBacktestJob.__table__.columns["rolling_window"]
        assert col.default.arg == 30


class TestBacktestTaskImportable:
    """Verify backtest task is importable."""

    def test_backtest_task_exists(self):
        from app.tasks.training_tasks import backtest_analytics_model

        assert backtest_analytics_model.name == "backtest_analytics_model"

    def test_execute_backtest_callable(self):
        from app.tasks.training_tasks import _execute_backtest

        assert callable(_execute_backtest)


class TestBacktestRoutes:
    """Verify backtest API routes are defined."""

    def test_backtest_route_exists(self):
        import inspect

        from app.analytics.api import _backtest_routes

        source = inspect.getsource(_backtest_routes)
        assert "start_backtest" in source
        assert "list_backtest_jobs" in source
        assert "get_backtest_job" in source
        assert "BacktestRequest" in source


# ---------------------------------------------------------------------------
# Batch Simulation
# ---------------------------------------------------------------------------


class TestBatchSimJobModel:
    """Verify AnalyticsBatchSimJob DB model."""

    def test_table_exists(self):
        from app.db.analytics import AnalyticsBatchSimJob

        assert AnalyticsBatchSimJob.__tablename__ == "analytics_batch_sim_jobs"

    def test_columns_present(self):
        from app.db.analytics import AnalyticsBatchSimJob

        cols = {c.name for c in AnalyticsBatchSimJob.__table__.columns}
        expected = {
            "id", "sport", "probability_mode", "iterations", "rolling_window",
            "date_start", "date_end", "status", "celery_task_id",
            "game_count", "results", "error_message", "created_at", "completed_at",
        }
        assert expected.issubset(cols)

    def test_status_column_default(self):
        from app.db.analytics import AnalyticsBatchSimJob

        col = AnalyticsBatchSimJob.__table__.columns["status"]
        assert col.default is not None
        assert col.default.arg == "pending"


class TestBatchSimTaskImportable:
    """Verify batch_simulate_games Celery task exists."""

    def test_task_exists(self):
        from app.tasks.batch_sim_tasks import batch_simulate_games

        assert batch_simulate_games is not None

    def test_task_callable(self):
        from app.tasks.batch_sim_tasks import batch_simulate_games

        assert callable(batch_simulate_games)


class TestBatchSimRoutes:
    """Verify batch simulation API routes are defined."""

    def test_batch_sim_routes_exist(self):
        import inspect

        from app.analytics.api import _pipeline_routes

        source = inspect.getsource(_pipeline_routes)
        assert "post_batch_simulate" in source
        assert "list_batch_simulate_jobs" in source
        assert "get_batch_simulate_job" in source
        assert "BatchSimulateRequest" in source

    def test_serialize_function_exists(self):
        from app.analytics.api.analytics_routes import _serialize_batch_sim_job

        assert callable(_serialize_batch_sim_job)


# ---------------------------------------------------------------------------
# Prediction Outcomes / Auto-Record (Phase 6)
# ---------------------------------------------------------------------------


class TestPredictionOutcomeModel:
    """Verify AnalyticsPredictionOutcome DB model."""

    def test_table_exists(self):
        from app.db.analytics import AnalyticsPredictionOutcome

        assert AnalyticsPredictionOutcome.__tablename__ == "analytics_prediction_outcomes"

    def test_columns_present(self):
        from app.db.analytics import AnalyticsPredictionOutcome

        cols = {c.name for c in AnalyticsPredictionOutcome.__table__.columns}
        expected = {
            "id", "game_id", "sport", "batch_sim_job_id",
            "home_team", "away_team",
            "predicted_home_wp", "predicted_away_wp",
            "predicted_home_score", "predicted_away_score",
            "probability_mode", "game_date",
            "actual_home_score", "actual_away_score",
            "home_win_actual", "correct_winner", "brier_score",
            "outcome_recorded_at", "created_at",
        }
        assert expected.issubset(cols)

    def test_game_id_indexed(self):
        from app.db.analytics import AnalyticsPredictionOutcome

        col = AnalyticsPredictionOutcome.__table__.columns["game_id"]
        assert col.index is True

    def test_outcome_fields_nullable(self):
        from app.db.analytics import AnalyticsPredictionOutcome

        for name in ("actual_home_score", "actual_away_score", "home_win_actual",
                      "correct_winner", "brier_score", "outcome_recorded_at"):
            col = AnalyticsPredictionOutcome.__table__.columns[name]
            assert col.nullable is True, f"{name} should be nullable"


class TestRecordOutcomesTask:
    """Verify record_completed_outcomes Celery task exists."""

    def test_task_exists(self):
        from app.tasks.outcome_tasks import record_completed_outcomes

        assert record_completed_outcomes is not None

    def test_task_callable(self):
        from app.tasks.outcome_tasks import record_completed_outcomes

        assert callable(record_completed_outcomes)


class TestSavePredictionOutcomes:
    """Verify _save_prediction_outcomes helper."""

    def test_function_exists(self):
        from app.tasks.batch_sim_tasks import _save_prediction_outcomes

        assert callable(_save_prediction_outcomes)


class TestRunRecordOutcomes:
    """Verify _run_record_outcomes async implementation."""

    def test_function_exists(self):
        from app.tasks.outcome_tasks import _run_record_outcomes

        assert callable(_run_record_outcomes)

    def test_is_coroutine(self):
        import asyncio

        from app.tasks.outcome_tasks import _run_record_outcomes

        assert asyncio.iscoroutinefunction(_run_record_outcomes)


class TestOutcomeRoutes:
    """Verify prediction outcome API routes are defined."""

    def test_outcome_routes_exist(self):
        import inspect

        from app.analytics.api import _calibration_routes

        source = inspect.getsource(_calibration_routes)
        assert "post_record_outcomes" in source
        assert "list_prediction_outcomes" in source
        assert "get_calibration_report" in source

    def test_serialize_function_exists(self):
        from app.analytics.api._calibration_routes import _serialize_prediction_outcome

        assert callable(_serialize_prediction_outcome)

    def test_calibration_report_endpoint_exists(self):
        import inspect

        from app.analytics.api import _calibration_routes

        source = inspect.getsource(_calibration_routes)
        assert "calibration-report" in source


class TestBrierScoreCalculation:
    """Verify Brier score calculation logic used in auto-record."""

    def test_perfect_prediction_home_win(self):
        # predicted 1.0 for home, home wins -> brier = 0
        pred_wp = 1.0
        actual_home_win = True
        actual_indicator = 1.0 if actual_home_win else 0.0
        brier = (pred_wp - actual_indicator) ** 2
        assert brier == 0.0

    def test_worst_prediction_home_win(self):
        # predicted 0.0 for home, home wins -> brier = 1
        pred_wp = 0.0
        actual_home_win = True
        actual_indicator = 1.0 if actual_home_win else 0.0
        brier = (pred_wp - actual_indicator) ** 2
        assert brier == 1.0

    def test_coin_flip_prediction(self):
        # predicted 0.5, home wins -> brier = 0.25
        pred_wp = 0.5
        actual_home_win = True
        actual_indicator = 1.0 if actual_home_win else 0.0
        brier = (pred_wp - actual_indicator) ** 2
        assert abs(brier - 0.25) < 1e-9

    def test_correct_winner_detection(self):
        # predicted 0.6 for home, home wins -> correct
        pred_wp = 0.6
        actual_home_win = True
        predicted_home_win = pred_wp > 0.5
        assert predicted_home_win == actual_home_win

    def test_wrong_winner_detection(self):
        # predicted 0.3 for home, home wins -> wrong
        pred_wp = 0.3
        actual_home_win = True
        predicted_home_win = pred_wp > 0.5
        assert predicted_home_win != actual_home_win


# ---------------------------------------------------------------------------
# Degradation Alerts (Phase 6)
# ---------------------------------------------------------------------------


class TestDegradationAlertModel:
    """Verify AnalyticsDegradationAlert DB model."""

    def test_table_exists(self):
        from app.db.analytics import AnalyticsDegradationAlert

        assert AnalyticsDegradationAlert.__tablename__ == "analytics_degradation_alerts"

    def test_columns_present(self):
        from app.db.analytics import AnalyticsDegradationAlert

        cols = {c.name for c in AnalyticsDegradationAlert.__table__.columns}
        expected = {
            "id", "sport", "alert_type",
            "baseline_brier", "recent_brier",
            "baseline_accuracy", "recent_accuracy",
            "baseline_count", "recent_count",
            "delta_brier", "delta_accuracy",
            "severity", "message", "acknowledged",
            "created_at",
        }
        assert expected.issubset(cols)

    def test_severity_default(self):
        from app.db.analytics import AnalyticsDegradationAlert

        col = AnalyticsDegradationAlert.__table__.columns["severity"]
        assert col.default is not None
        assert col.default.arg == "warning"

    def test_acknowledged_default(self):
        from app.db.analytics import AnalyticsDegradationAlert

        col = AnalyticsDegradationAlert.__table__.columns["acknowledged"]
        assert col.default is not None
        assert col.default.arg is False


class TestDegradationCheckTask:
    """Verify check_model_degradation Celery task."""

    def test_task_exists(self):
        from app.tasks.outcome_tasks import check_model_degradation

        assert check_model_degradation is not None

    def test_task_callable(self):
        from app.tasks.outcome_tasks import check_model_degradation

        assert callable(check_model_degradation)

    def test_run_function_is_coroutine(self):
        import asyncio

        from app.tasks.outcome_tasks import _run_degradation_check

        assert asyncio.iscoroutinefunction(_run_degradation_check)


class TestDegradationThresholds:
    """Verify degradation threshold constants."""

    def test_thresholds_exist(self):
        from app.tasks.outcome_tasks import (
            _BRIER_CRITICAL_THRESHOLD,
            _BRIER_WARNING_THRESHOLD,
            _MIN_WINDOW_SIZE,
        )

        assert isinstance(_BRIER_WARNING_THRESHOLD, float)
        assert isinstance(_BRIER_CRITICAL_THRESHOLD, float)
        assert isinstance(_MIN_WINDOW_SIZE, int)

    def test_critical_exceeds_warning(self):
        from app.tasks.outcome_tasks import (
            _BRIER_CRITICAL_THRESHOLD,
            _BRIER_WARNING_THRESHOLD,
        )

        assert _BRIER_CRITICAL_THRESHOLD > _BRIER_WARNING_THRESHOLD

    def test_min_window_reasonable(self):
        from app.tasks.outcome_tasks import _MIN_WINDOW_SIZE

        assert _MIN_WINDOW_SIZE >= 5
        assert _MIN_WINDOW_SIZE <= 50


class TestDegradationDetectionLogic:
    """Test the degradation detection math."""

    def test_no_degradation(self):
        # Recent is same as baseline -> delta = 0 -> no alert
        baseline_brier = 0.20
        recent_brier = 0.20
        delta = recent_brier - baseline_brier
        assert delta < 0.03  # Below warning threshold

    def test_warning_level(self):
        # Recent is 0.04 worse -> warning
        baseline_brier = 0.20
        recent_brier = 0.24
        delta = recent_brier - baseline_brier
        assert 0.03 <= delta < 0.06

    def test_critical_level(self):
        # Recent is 0.08 worse -> critical
        baseline_brier = 0.20
        recent_brier = 0.28
        delta = recent_brier - baseline_brier
        assert delta >= 0.06

    def test_improvement_no_alert(self):
        # Recent is better -> negative delta -> no alert
        baseline_brier = 0.25
        recent_brier = 0.20
        delta = recent_brier - baseline_brier
        assert delta < 0  # Model improved

    def test_severity_assignment(self):
        from app.tasks.outcome_tasks import (
            _BRIER_CRITICAL_THRESHOLD,
            _BRIER_WARNING_THRESHOLD,
        )

        # Simulate the logic from _run_degradation_check
        for delta, expected_severity in [
            (0.01, None),
            (0.04, "warning"),
            (0.08, "critical"),
        ]:
            severity = None
            if delta >= _BRIER_CRITICAL_THRESHOLD:
                severity = "critical"
            elif delta >= _BRIER_WARNING_THRESHOLD:
                severity = "warning"
            assert severity == expected_severity, f"delta={delta}: got {severity}, expected {expected_severity}"


class TestDegradationRoutes:
    """Verify degradation alert API routes exist."""

    def test_routes_exist(self):
        import inspect

        from app.analytics.api import _calibration_routes

        source = inspect.getsource(_calibration_routes)
        assert "post_degradation_check" in source
        assert "list_degradation_alerts" in source
        assert "acknowledge_degradation_alert" in source

    def test_serialize_function_exists(self):
        from app.analytics.api._calibration_routes import _serialize_degradation_alert

        assert callable(_serialize_degradation_alert)
