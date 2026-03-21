"""Tests for simulation variance computation and prediction outcome persistence.

Phase 1 of the fair-odds pipeline: verify that SimulationRunner emits
variance metrics and that batch sim persistence populates the new columns.
"""

from __future__ import annotations

import math

from app.analytics.core.simulation_runner import SimulationRunner


class TestAggregateResultsVariance:
    """Verify variance fields in aggregate_results()."""

    def test_empty_results_include_variance_fields(self):
        runner = SimulationRunner()
        summary = runner.aggregate_results([])
        assert summary["home_wp_std_dev"] == 0.0
        assert summary["score_std_home"] == 0.0
        assert summary["score_std_away"] == 0.0

    def test_all_home_wins_zero_variance(self):
        """When every iteration produces the same winner, WP std dev is ~0."""
        results = [
            {"home_score": 5, "away_score": 2, "winner": "home"}
            for _ in range(100)
        ]
        runner = SimulationRunner()
        summary = runner.aggregate_results(results)

        assert summary["home_win_probability"] == 1.0
        assert summary["away_win_probability"] == 0.0
        # Bernoulli std dev of p=1.0 is 0
        assert summary["home_wp_std_dev"] == 0.0

    def test_all_same_score_zero_score_variance(self):
        """When every iteration produces identical scores, score std dev is 0."""
        results = [
            {"home_score": 4, "away_score": 3, "winner": "home"}
            for _ in range(50)
        ]
        runner = SimulationRunner()
        summary = runner.aggregate_results(results)

        assert summary["score_std_home"] == 0.0
        assert summary["score_std_away"] == 0.0

    def test_balanced_matchup_has_positive_variance(self):
        """A 50/50 matchup should have measurable WP std dev."""
        results = []
        for i in range(1000):
            if i % 2 == 0:
                results.append({"home_score": 5, "away_score": 3, "winner": "home"})
            else:
                results.append({"home_score": 3, "away_score": 5, "winner": "away"})

        runner = SimulationRunner()
        summary = runner.aggregate_results(results)

        assert summary["home_win_probability"] == 0.5
        # Bernoulli: sqrt(0.5 * 0.5 / 1000) ≈ 0.0158
        expected_std = math.sqrt(0.5 * 0.5 / 1000)
        assert abs(summary["home_wp_std_dev"] - expected_std) < 0.001

    def test_score_variance_computed_correctly(self):
        """Verify score std dev against hand-calculated values."""
        # Scores: 3, 5, 3, 5 → mean=4, variance=((1+1+1+1)/3)=1.333, std=1.155
        results = [
            {"home_score": 3, "away_score": 2, "winner": "home"},
            {"home_score": 5, "away_score": 2, "winner": "home"},
            {"home_score": 3, "away_score": 2, "winner": "home"},
            {"home_score": 5, "away_score": 2, "winner": "home"},
        ]
        runner = SimulationRunner()
        summary = runner.aggregate_results(results)

        expected_home_std = math.sqrt(((3 - 4) ** 2 + (5 - 4) ** 2 + (3 - 4) ** 2 + (5 - 4) ** 2) / 3)
        assert abs(summary["score_std_home"] - expected_home_std) < 0.01
        # Away scores are all 2 → std = 0
        assert summary["score_std_away"] == 0.0

    def test_single_result_zero_variance(self):
        """Single iteration should produce zero variance (no spread to measure)."""
        results = [{"home_score": 4, "away_score": 3, "winner": "home"}]
        runner = SimulationRunner()
        summary = runner.aggregate_results(results)

        assert summary["home_wp_std_dev"] == 0.0
        assert summary["score_std_home"] == 0.0
        assert summary["score_std_away"] == 0.0

    def test_variance_fields_coexist_with_existing_fields(self):
        """Variance fields don't break existing summary structure."""
        results = [
            {"home_score": 4, "away_score": 3, "winner": "home"},
            {"home_score": 2, "away_score": 5, "winner": "away"},
        ]
        runner = SimulationRunner()
        summary = runner.aggregate_results(results)

        # Existing fields still present
        assert "home_win_probability" in summary
        assert "away_win_probability" in summary
        assert "average_home_score" in summary
        assert "average_away_score" in summary
        assert "score_distribution" in summary
        assert "iterations" in summary
        # New fields present
        assert "home_wp_std_dev" in summary
        assert "score_std_home" in summary
        assert "score_std_away" in summary


class TestPredictionOutcomeColumns:
    """Verify the AnalyticsPredictionOutcome model has the new columns."""

    def test_model_has_observability_columns(self):
        from app.db.analytics import AnalyticsPredictionOutcome

        # Check column names exist on the mapper
        columns = {c.name for c in AnalyticsPredictionOutcome.__table__.columns}
        expected_new = {
            "sim_wp_std_dev",
            "sim_iterations",
            "sim_score_std_home",
            "sim_score_std_away",
            "profile_games_home",
            "profile_games_away",
            "sim_probability_source",
            "feature_snapshot",
        }
        assert expected_new.issubset(columns), f"Missing columns: {expected_new - columns}"

    def test_new_columns_are_nullable(self):
        from app.db.analytics import AnalyticsPredictionOutcome

        table = AnalyticsPredictionOutcome.__table__
        for col_name in (
            "sim_wp_std_dev", "sim_iterations", "sim_score_std_home",
            "sim_score_std_away", "profile_games_home", "profile_games_away",
            "sim_probability_source", "feature_snapshot",
        ):
            col = table.c[col_name]
            assert col.nullable, f"Column {col_name} should be nullable"
