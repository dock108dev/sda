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
    """Verify MetricsEngine interface."""

    def test_init_stores_sport(self) -> None:
        engine = MetricsEngine("mlb")
        assert engine.sport == "mlb"

    def test_calculate_player_metrics_returns_dict(self) -> None:
        engine = MetricsEngine("mlb")
        result = engine.calculate_player_metrics({})
        assert isinstance(result, dict)

    def test_calculate_team_metrics_returns_dict(self) -> None:
        engine = MetricsEngine("mlb")
        result = engine.calculate_team_metrics({})
        assert isinstance(result, dict)


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

    def test_simulation_result_defaults(self) -> None:
        s = SimulationResult(sport="mlb")
        assert s.iterations == 0
        assert s.outcomes == []
        assert s.summary == {}


class TestMLBMetrics:
    """Verify MLB metrics module."""

    def test_build_player_profile(self) -> None:
        m = MLBMetrics()
        profile = m.build_player_profile({"player_id": "123"})
        assert isinstance(profile, PlayerProfile)
        assert profile.sport == "mlb"

    def test_build_team_profile(self) -> None:
        m = MLBMetrics()
        profile = m.build_team_profile({"team_id": "NYY"})
        assert isinstance(profile, TeamProfile)
        assert profile.sport == "mlb"


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
