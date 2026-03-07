"""Tests for the analytics framework scaffolding."""

from __future__ import annotations

import pytest

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

    def test_simulate_game_returns_result(self) -> None:
        engine = SimulationEngine("mlb")
        result = engine.simulate_game({}, iterations=100)
        assert isinstance(result, SimulationResult)
        assert result.sport == "mlb"
        assert result.iterations == 100


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
        assert "contact_probability" in probs
        assert "strikeout_probability" in probs
        assert "walk_probability" in probs
        assert "single_probability" in probs
        assert "double_probability" in probs
        assert "triple_probability" in probs
        assert "home_run_probability" in probs

    def test_probabilities_are_normalized(self) -> None:
        from app.analytics.core.matchup_engine import MatchupEngine

        engine = MatchupEngine("mlb")
        result = engine.calculate_player_vs_player(
            self._batter_profile(), self._pitcher_profile()
        )
        total = sum(result.probabilities.values())
        assert abs(total - 1.0) < 0.01

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
        assert "contact_probability" in result.probabilities

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
        assert "contact_probability" in result.probabilities

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
        assert result.probabilities["contact_probability"] > 0


class TestMLBMatchup:
    """Verify MLB matchup probability calculations directly."""

    def test_normalize_probabilities(self) -> None:
        from app.analytics.sports.mlb.matchup import normalize_probabilities

        raw = {"a": 0.3, "b": 0.7}
        result = normalize_probabilities(raw)
        assert abs(sum(result.values()) - 1.0) < 0.001

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
        assert abs(sum(result.values()) - 1.0) < 0.01
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
        assert "contact_probability" in matchup.probabilities
        assert "home_run_probability" in matchup.probabilities
        assert abs(sum(matchup.probabilities.values()) - 1.0) < 0.01


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

    def test_simulate_game_backward_compat(self) -> None:
        engine = SimulationEngine("mlb")
        result = engine.simulate_game({}, iterations=50)
        assert isinstance(result, SimulationResult)
        assert result.iterations == 50
        assert result.sport == "mlb"


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
        from app.analytics.core.simulation_runner import SimulationRunner
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
        runner = SimulationRunner()
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

    def test_run_simulation(self) -> None:
        svc = AnalyticsService()
        result = svc.run_simulation("mlb", {}, iterations=50)
        assert isinstance(result, SimulationResult)
        assert result.iterations == 50
