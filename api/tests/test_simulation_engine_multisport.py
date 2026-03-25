"""Integration tests for multi-sport SimulationEngine."""
import pytest
from app.analytics.core.simulation_engine import SimulationEngine, _SPORT_SIMULATORS


class TestSportSimulatorRegistry:
    """Verify all sports are registered."""

    def test_mlb_registered(self):
        assert "mlb" in _SPORT_SIMULATORS

    def test_nba_registered(self):
        assert "nba" in _SPORT_SIMULATORS

    def test_nhl_registered(self):
        assert "nhl" in _SPORT_SIMULATORS

    def test_ncaab_registered(self):
        assert "ncaab" in _SPORT_SIMULATORS

    def test_unknown_sport_not_registered(self):
        assert "cricket" not in _SPORT_SIMULATORS


class TestSimulationEngineMLB:
    """Verify MLB still works through engine."""

    def test_mlb_simulation(self):
        engine = SimulationEngine("mlb")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=100, seed=42)
        assert result["iterations"] == 100
        assert 0.0 < result["home_win_probability"] < 1.0
        assert result["average_home_score"] > 0
        assert result["average_away_score"] > 0
        assert len(result["score_distribution"]) > 0


class TestSimulationEngineNBA:
    def test_nba_simulation(self):
        engine = SimulationEngine("nba")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=100, seed=42)
        assert result["iterations"] == 100
        assert 0.0 < result["home_win_probability"] < 1.0
        assert result["average_home_score"] > 80  # NBA scores should be high
        assert result["average_away_score"] > 80

    def test_nba_deterministic(self):
        engine = SimulationEngine("nba")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r1 = engine.run_simulation(ctx, iterations=50, seed=42)
        engine2 = SimulationEngine("nba")
        r2 = engine2.run_simulation(ctx, iterations=50, seed=42)
        assert r1["home_win_probability"] == r2["home_win_probability"]

    def test_nba_score_range(self):
        engine = SimulationEngine("nba")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=200, seed=123)
        avg_total = result["average_home_score"] + result["average_away_score"]
        assert 180 < avg_total < 260


class TestSimulationEngineNHL:
    def test_nhl_simulation(self):
        engine = SimulationEngine("nhl")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=100, seed=42)
        assert result["iterations"] == 100
        assert 0.0 < result["home_win_probability"] < 1.0
        assert result["average_home_score"] > 0

    def test_nhl_score_range(self):
        engine = SimulationEngine("nhl")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=200, seed=123)
        avg_total = result["average_home_score"] + result["average_away_score"]
        assert 3 < avg_total < 9


class TestSimulationEngineNCAAB:
    def test_ncaab_simulation(self):
        engine = SimulationEngine("ncaab")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=100, seed=42)
        assert result["iterations"] == 100
        assert 0.0 < result["home_win_probability"] < 1.0

    def test_ncaab_score_range(self):
        engine = SimulationEngine("ncaab")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=200, seed=123)
        avg_total = result["average_home_score"] + result["average_away_score"]
        assert 110 < avg_total < 180


class TestUnknownSport:
    def test_unknown_returns_empty(self):
        engine = SimulationEngine("cricket")
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        result = engine.run_simulation(ctx, iterations=10, seed=42)
        assert result["iterations"] == 0
        assert result["home_win_probability"] == 0.0


class TestAllSportsComparison:
    """Verify score ranges are sport-appropriate across all sports."""

    def test_score_ordering(self):
        """NBA should have highest scores, NHL lowest."""
        ctx = {"home_probabilities": {}, "away_probabilities": {}}

        nba = SimulationEngine("nba").run_simulation(ctx, iterations=200, seed=42)
        ncaab = SimulationEngine("ncaab").run_simulation(ctx, iterations=200, seed=42)
        mlb = SimulationEngine("mlb").run_simulation(ctx, iterations=200, seed=42)
        nhl = SimulationEngine("nhl").run_simulation(ctx, iterations=200, seed=42)

        nba_total = nba["average_home_score"] + nba["average_away_score"]
        ncaab_total = ncaab["average_home_score"] + ncaab["average_away_score"]
        mlb_total = mlb["average_home_score"] + mlb["average_away_score"]
        nhl_total = nhl["average_home_score"] + nhl["average_away_score"]

        assert nba_total > ncaab_total > mlb_total > nhl_total
