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
