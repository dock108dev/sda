"""Tests for simulation engine, training pipeline, and analysis modules.

Covers uncovered lines in:
- app.analytics.core.simulation_engine
- app.analytics.training.core.training_pipeline
- app.analytics.core.simulation_analysis
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# simulation_engine: helper functions
# ---------------------------------------------------------------------------

class TestExtractProfileMetrics:
    """Test _extract_profile_metrics with various input types."""

    def test_empty_profile_returns_empty_dict(self):
        from app.analytics.core.simulation_engine import _extract_profile_metrics

        assert _extract_profile_metrics(None) == {}
        assert _extract_profile_metrics({}) == {}
        assert _extract_profile_metrics("") == {}

    def test_dict_with_metrics_key(self):
        from app.analytics.core.simulation_engine import _extract_profile_metrics

        profile = {"metrics": {"k_rate": 0.25, "bb_rate": 0.10}}
        result = _extract_profile_metrics(profile)
        assert result == {"k_rate": 0.25, "bb_rate": 0.10}

    def test_flat_dict_without_metrics_key(self):
        from app.analytics.core.simulation_engine import _extract_profile_metrics

        profile = {"k_rate": 0.25, "bb_rate": 0.10}
        result = _extract_profile_metrics(profile)
        assert result == {"k_rate": 0.25, "bb_rate": 0.10}

    def test_object_with_metrics_attribute(self):
        from app.analytics.core.simulation_engine import _extract_profile_metrics

        obj = SimpleNamespace(metrics={"k_rate": 0.30})
        result = _extract_profile_metrics(obj)
        assert result == {"k_rate": 0.30}

    def test_object_without_metrics_attribute(self):
        from app.analytics.core.simulation_engine import _extract_profile_metrics

        obj = SimpleNamespace(name="test")
        result = _extract_profile_metrics(obj)
        assert result == {}


class TestProfileToPitchFeatures:
    """Test _profile_to_pitch_features key mapping."""

    def test_all_keys_present_with_defaults(self):
        from app.analytics.core.simulation_engine import _profile_to_pitch_features

        result = _profile_to_pitch_features({}, {})
        expected_keys = {
            "pitcher_k_rate", "pitcher_walk_rate", "pitcher_zone_rate",
            "pitcher_contact_allowed", "batter_contact_rate",
            "batter_swing_rate", "batter_zone_swing_rate",
            "batter_chase_rate", "batter_barrel_rate",
            "batter_hard_hit_rate", "batter_power_index",
            "pitcher_hard_hit_allowed", "exit_velocity",
        }
        assert set(result.keys()) == expected_keys
        # Verify defaults are reasonable floats
        for v in result.values():
            assert isinstance(v, float)

    def test_with_real_values(self):
        from app.analytics.core.simulation_engine import _profile_to_pitch_features

        batting = {
            "contact_rate": 0.80,
            "swing_rate": 0.50,
            "zone_swing_rate": 0.70,
            "chase_rate": 0.25,
            "barrel_rate": 0.08,
            "hard_hit_rate": 0.40,
            "power_index": 1.2,
            "avg_exit_velocity": 90.5,
        }
        pitching = {
            "k_rate": 0.28,
            "bb_rate": 0.06,
            "zone_swing_rate": 0.50,
            "whiff_rate": 0.30,
            "hard_hit_pct_against": 0.32,
        }
        result = _profile_to_pitch_features(batting, pitching)

        assert result["pitcher_k_rate"] == 0.28
        assert result["pitcher_walk_rate"] == 0.06
        assert result["pitcher_zone_rate"] == 0.50
        assert result["pitcher_contact_allowed"] == pytest.approx(0.70)
        assert result["batter_contact_rate"] == 0.80
        assert result["batter_swing_rate"] == 0.50
        assert result["batter_zone_swing_rate"] == 0.70
        assert result["batter_chase_rate"] == 0.25
        assert result["batter_barrel_rate"] == 0.08
        assert result["batter_hard_hit_rate"] == 0.40
        assert result["batter_power_index"] == 1.2
        assert result["pitcher_hard_hit_allowed"] == 0.32
        assert result["exit_velocity"] == 90.5

    def test_alternate_key_names(self):
        """Fallback keys (strikeout_rate, walk_rate, avg_exit_velo)."""
        from app.analytics.core.simulation_engine import _profile_to_pitch_features

        pitching = {"strikeout_rate": 0.27, "walk_rate": 0.09}
        batting = {"avg_exit_velo": 89.0}
        result = _profile_to_pitch_features(batting, pitching)

        assert result["pitcher_k_rate"] == 0.27
        assert result["pitcher_walk_rate"] == 0.09
        assert result["exit_velocity"] == 89.0


class TestLoadPitchModels:
    """Test _load_pitch_models with mocked ModelRegistry."""

    def test_success_path_loads_both_models(self):
        from app.analytics.core.simulation_engine import _load_pitch_models

        mock_registry_instance = MagicMock()
        mock_registry_instance.get_active_model.side_effect = [
            {"artifact_path": "/fake/pitch.pkl"},
            {"artifact_path": "/fake/bb.pkl"},
        ]

        # Patch BaseModel.load so it doesn't hit the filesystem
        with patch(
            "app.analytics.models.core.model_registry.ModelRegistry",
            return_value=mock_registry_instance,
        ), patch(
            "app.analytics.models.core.model_interface.BaseModel.load",
        ):
            pitch_model, bb_model = _load_pitch_models()

        assert pitch_model is not None
        assert bb_model is not None

    def test_exception_path_returns_none(self):
        from app.analytics.core.simulation_engine import _load_pitch_models

        with patch(
            "app.analytics.core.simulation_engine.importlib.import_module",
            side_effect=Exception("no module"),
        ):
            # _load_pitch_models catches all exceptions
            pitch_model, bb_model = _load_pitch_models()
            assert pitch_model is None
            assert bb_model is None

    def test_no_active_models_returns_none(self):
        from app.analytics.core.simulation_engine import _load_pitch_models

        mock_registry = MagicMock()
        mock_registry.get_active_model.return_value = None

        with patch.dict("sys.modules", {
            "app.analytics.models.core.model_registry": MagicMock(
                ModelRegistry=lambda: mock_registry
            ),
        }):
            pitch_model, bb_model = _load_pitch_models()
            assert pitch_model is None
            assert bb_model is None


class TestToSimulationKeys:
    """Test _to_simulation_keys key transformation."""

    def test_skips_underscore_prefixed_keys(self):
        from app.analytics.core.simulation_engine import _to_simulation_keys

        probs = {"_meta": "info", "strikeout": 0.22}
        result = _to_simulation_keys(probs)
        assert "_meta" not in result
        assert "strikeout_probability" in result

    def test_adds_probability_suffix(self):
        from app.analytics.core.simulation_engine import _to_simulation_keys

        probs = {"strikeout": 0.22, "walk_or_hbp": 0.08, "single": 0.15}
        result = _to_simulation_keys(probs)
        assert result == {
            "strikeout_probability": 0.22,
            "walk_or_hbp_probability": 0.08,
            "single_probability": 0.15,
        }

    def test_preserves_existing_probability_suffix(self):
        from app.analytics.core.simulation_engine import _to_simulation_keys

        probs = {"strikeout_probability": 0.22}
        result = _to_simulation_keys(probs)
        assert result == {"strikeout_probability": 0.22}

    def test_empty_input(self):
        from app.analytics.core.simulation_engine import _to_simulation_keys

        assert _to_simulation_keys({}) == {}

    def test_mixed_keys(self):
        from app.analytics.core.simulation_engine import _to_simulation_keys

        probs = {
            "_internal": 0.5,
            "walk_or_hbp": 0.08,
            "home_run_probability": 0.03,
        }
        result = _to_simulation_keys(probs)
        assert result == {
            "walk_or_hbp_probability": 0.08,
            "home_run_probability": 0.03,
        }


class TestRunPitchLevel:
    """Test pitch_level mode via run_simulation."""

    def test_pitch_level_with_profiles(self):
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        ctx = {
            "probability_mode": "pitch_level",
            "profiles": {
                "home_profile": {"metrics": {"k_rate": 0.22, "contact_rate": 0.78}},
                "away_profile": {"metrics": {"k_rate": 0.25, "contact_rate": 0.75}},
            },
        }
        result = engine.run_simulation(ctx, iterations=10, seed=42)

        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert "average_home_score" in result
        assert "average_away_score" in result
        assert result["probability_source"] == "pitch_level"
        assert result["iterations"] == 10

    def test_pitch_level_without_profiles(self):
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        ctx = {"probability_mode": "pitch_level"}
        result = engine.run_simulation(ctx, iterations=5, seed=99)

        assert result["probability_source"] == "pitch_level"
        assert result["iterations"] == 5

    def test_pitch_level_computes_average_pitches(self):
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("mlb")
        ctx = {"probability_mode": "pitch_level"}
        result = engine.run_simulation(ctx, iterations=20, seed=7)

        # average_pitches_per_game should be present when raw_results had data
        assert "average_pitches_per_game" in result
        assert result["average_pitches_per_game"] > 0


class TestSimulationEngineNoSimulator:
    """Test SimulationEngine with unsupported sport."""

    def test_unsupported_sport_returns_zeros(self):
        from app.analytics.core.simulation_engine import SimulationEngine

        engine = SimulationEngine("cricket")
        result = engine.run_simulation({}, iterations=100)
        assert result["home_win_probability"] == 0.0
        assert result["away_win_probability"] == 0.0
        assert result["iterations"] == 0


# ---------------------------------------------------------------------------
# training_pipeline: _default_model and run()
# ---------------------------------------------------------------------------

class TestDefaultModel:
    """Test TrainingPipeline._default_model() for various model types."""

    def test_pitch_model_type(self):
        """Pitch model should be RandomForestClassifier with balanced class weights."""
        from sklearn.ensemble import RandomForestClassifier

        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="pitch",
            config_name="test",
        )
        model = pipeline._default_model()
        assert isinstance(model, RandomForestClassifier)
        assert model.class_weight == "balanced"

    def test_batted_ball_model_type(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="batted_ball",
            config_name="test",
        )
        model = pipeline._default_model()

        from sklearn.ensemble import RandomForestClassifier
        assert isinstance(model, RandomForestClassifier)
        assert model.class_weight == "balanced"
        assert model.n_estimators == 100
        assert model.max_depth == 8

    def test_plate_appearance_model_type(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="plate_appearance",
            config_name="test",
        )
        model = pipeline._default_model()

        from sklearn.ensemble import GradientBoostingClassifier
        assert isinstance(model, GradientBoostingClassifier)
        assert model.max_depth == 5

    def test_game_model_type(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="game",
            config_name="test",
        )
        model = pipeline._default_model()

        from sklearn.ensemble import GradientBoostingClassifier
        assert isinstance(model, GradientBoostingClassifier)
        assert model.max_depth == 4

    def test_fallback_regressor(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="unknown_type",
            config_name="test",
        )
        model = pipeline._default_model()

        from sklearn.ensemble import GradientBoostingRegressor
        assert isinstance(model, GradientBoostingRegressor)


class TestBuildDatasetRouting:
    """Test that build_dataset routes to the correct label function."""

    def test_pitch_label_fn_routing(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="pitch",
            config_name="test",
        )

        # Mock the sport pipeline to verify routing
        mock_sport = MagicMock()
        mock_sport.pitch_label_fn = lambda r: r.get("pitch_result")
        pipeline._sport_pipeline = mock_sport

        # Mock the dataset builder to capture the label_fn
        mock_builder = MagicMock()
        mock_builder.build.return_value = ([[1.0]], ["strike"], ["feat1"])
        pipeline._dataset_builder = mock_builder

        records = [{"pitch_result": "strike"}]
        X, y, names = pipeline.build_dataset(records)

        # Verify build was called (label_fn should be pitch_label_fn)
        mock_builder.build.assert_called_once()
        call_kwargs = mock_builder.build.call_args
        assert call_kwargs[1]["label_fn"] == mock_sport.pitch_label_fn

    def test_batted_ball_label_fn_routing(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="batted_ball",
            config_name="test",
        )

        mock_sport = MagicMock()
        mock_sport.batted_ball_label_fn = lambda r: r.get("bb_result")
        pipeline._sport_pipeline = mock_sport

        mock_builder = MagicMock()
        mock_builder.build.return_value = ([[1.0]], ["ground_ball"], ["feat1"])
        pipeline._dataset_builder = mock_builder

        records = [{"bb_result": "ground_ball"}]
        X, y, names = pipeline.build_dataset(records)

        mock_builder.build.assert_called_once()
        call_kwargs = mock_builder.build.call_args
        assert call_kwargs[1]["label_fn"] == mock_sport.batted_ball_label_fn

    def test_custom_label_fn_overrides_routing(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="pitch",
            config_name="test",
        )

        custom_fn = lambda r: "custom"
        mock_builder = MagicMock()
        mock_builder.build.return_value = ([[1.0]], ["custom"], ["feat1"])
        pipeline._dataset_builder = mock_builder

        pipeline.build_dataset([{"x": 1}], label_fn=custom_fn)

        call_kwargs = mock_builder.build.call_args
        assert call_kwargs[1]["label_fn"] == custom_fn


class TestEvaluateModel:
    """Test evaluate_model routing for classifier types."""

    def test_pitch_type_uses_classifier_evaluation(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="pitch",
            config_name="test",
        )

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_classifier.return_value = {"accuracy": 0.65}
        pipeline._evaluator = mock_evaluator

        mock_model = MagicMock()
        mock_model.predict_proba = None  # no predict_proba
        del mock_model.predict_proba

        result = pipeline.evaluate_model(mock_model, [[1.0, 2.0]], ["strike"])
        mock_evaluator.evaluate_classifier.assert_called_once()
        assert result["accuracy"] == 0.65

    def test_batted_ball_type_uses_classifier_evaluation(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="batted_ball",
            config_name="test",
        )

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_classifier.return_value = {"accuracy": 0.55}
        pipeline._evaluator = mock_evaluator

        mock_model = MagicMock()
        del mock_model.predict_proba

        result = pipeline.evaluate_model(mock_model, [[1.0]], ["fly_ball"])
        mock_evaluator.evaluate_classifier.assert_called_once()

    def test_unknown_type_uses_regressor_evaluation(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="unknown_type",
            config_name="test",
        )

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_regressor.return_value = {"mae": 0.5, "rmse": 0.7}
        pipeline._evaluator = mock_evaluator

        mock_model = MagicMock()
        result = pipeline.evaluate_model(mock_model, [[1.0]], [3.5])
        mock_evaluator.evaluate_regressor.assert_called_once()


class TestTrainingPipelineRun:
    """Test run() with empty data returns error dict."""

    def test_run_with_no_data(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="pitch",
            config_name="test",
        )

        # Mock sport pipeline to return empty list
        mock_sport = MagicMock()
        mock_sport.load_plate_appearance_training_data.return_value = []
        pipeline._sport_pipeline = mock_sport

        result = pipeline.run(records=[])
        assert result["error"] == "no_training_data"
        assert "model_id" in result

    def test_run_with_empty_dataset(self):
        from app.analytics.training.core.training_pipeline import TrainingPipeline

        pipeline = TrainingPipeline(
            sport="mlb",
            model_type="pitch",
            config_name="test",
        )

        # Records exist but build_dataset returns empty
        mock_builder = MagicMock()
        mock_builder.build.return_value = ([], [], [])
        pipeline._dataset_builder = mock_builder

        result = pipeline.run(records=[{"some": "data"}])
        assert result["error"] == "empty_dataset"


# ---------------------------------------------------------------------------
# simulation_analysis
# ---------------------------------------------------------------------------

class TestSummarizeDistribution:
    """Test SimulationAnalysis.summarize_distribution."""

    def test_empty_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        result = analysis.summarize_distribution([])
        assert result == {"score_distribution": {}, "top_scores": []}

    def test_with_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        results = [
            {"home_score": 4, "away_score": 3, "winner": "home"},
            {"home_score": 4, "away_score": 3, "winner": "home"},
            {"home_score": 5, "away_score": 2, "winner": "home"},
            {"home_score": 3, "away_score": 6, "winner": "away"},
        ]
        dist = analysis.summarize_distribution(results)

        assert "score_distribution" in dist
        assert "top_scores" in dist
        assert "4-3" in dist["score_distribution"]
        assert dist["score_distribution"]["4-3"] == 0.5
        assert len(dist["top_scores"]) <= 20


class TestSummarizeTeamTotals:
    """Test SimulationAnalysis.summarize_team_totals."""

    def test_empty_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        result = analysis.summarize_team_totals([])
        assert result["home_score_distribution"] == {}
        assert result["away_score_distribution"] == {}
        assert result["average_home_score"] == 0.0
        assert result["median_home_score"] == 0.0

    def test_with_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        results = [
            {"home_score": 4, "away_score": 3},
            {"home_score": 6, "away_score": 2},
            {"home_score": 4, "away_score": 5},
        ]
        totals = analysis.summarize_team_totals(results)

        assert totals["average_home_score"] == pytest.approx(4.67, abs=0.01)
        assert totals["average_away_score"] == pytest.approx(3.33, abs=0.01)
        assert "4" in totals["home_score_distribution"]
        assert totals["median_home_score"] == 4.0
        assert totals["median_away_score"] == 3.0


class TestMedian:
    """Test _median helper."""

    def test_empty_list(self):
        from app.analytics.core.simulation_analysis import _median

        assert _median([]) == 0.0

    def test_odd_count(self):
        from app.analytics.core.simulation_analysis import _median

        assert _median([1, 3, 5]) == 3.0
        assert _median([7]) == 7.0

    def test_even_count(self):
        from app.analytics.core.simulation_analysis import _median

        assert _median([1, 3]) == 2.0
        assert _median([2, 4, 6, 8]) == 5.0

    def test_unsorted_input(self):
        from app.analytics.core.simulation_analysis import _median

        assert _median([5, 1, 3]) == 3.0


class TestScoreDistribution:
    """Test _score_distribution helper."""

    def test_with_scores(self):
        from app.analytics.core.simulation_analysis import _score_distribution

        scores = [3, 4, 4, 5, 3, 3]
        dist = _score_distribution(scores, len(scores))

        assert dist["3"] == pytest.approx(0.5)
        assert dist["4"] == pytest.approx(0.3333, abs=0.001)
        assert dist["5"] == pytest.approx(0.1667, abs=0.001)
        # Keys should be sorted
        assert list(dist.keys()) == ["3", "4", "5"]


class TestSpreadAnalysis:
    """Test summarize_spreads with push outcomes."""

    def test_spread_with_push(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        # Home wins by exactly 2. Spread is -2.0, so margin + spread = 0 -> push
        results = [
            {"home_score": 5, "away_score": 3},
            {"home_score": 5, "away_score": 3},
            {"home_score": 5, "away_score": 3},
            {"home_score": 5, "away_score": 3},
        ]
        spread = analysis.summarize_spreads(results, spread_line=-2.0)

        assert spread["push_probability"] == 1.0
        assert spread["home_cover_probability"] == 0.0
        assert spread["away_cover_probability"] == 0.0

    def test_spread_empty_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        spread = analysis.summarize_spreads([], spread_line=-1.5)
        assert spread["home_cover_probability"] == 0.0

    def test_spread_mixed(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        results = [
            {"home_score": 5, "away_score": 3},  # margin=2, +(-1.5)=0.5 -> home cover
            {"home_score": 3, "away_score": 5},  # margin=-2, +(-1.5)=-3.5 -> away cover
        ]
        spread = analysis.summarize_spreads(results, spread_line=-1.5)
        assert spread["home_cover_probability"] == 0.5
        assert spread["away_cover_probability"] == 0.5


class TestTotalAnalysis:
    """Test summarize_totals with push outcomes."""

    def test_total_with_push(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        # Total is exactly 8 every game, line is 8.0 -> push
        results = [
            {"home_score": 5, "away_score": 3},
            {"home_score": 4, "away_score": 4},
        ]
        totals = analysis.summarize_totals(results, total_line=8.0)

        assert totals["push_probability"] == 1.0
        assert totals["over_probability"] == 0.0
        assert totals["under_probability"] == 0.0

    def test_total_empty_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        totals = analysis.summarize_totals([], total_line=8.5)
        assert totals["over_probability"] == 0.0

    def test_total_mixed(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        results = [
            {"home_score": 5, "away_score": 4},  # total=9 > 8.5 -> over
            {"home_score": 4, "away_score": 3},  # total=7 < 8.5 -> under
        ]
        totals = analysis.summarize_totals(results, total_line=8.5)
        assert totals["over_probability"] == 0.5
        assert totals["under_probability"] == 0.5
        assert totals["push_probability"] == 0.0


class TestSummarizeResults:
    """Test summarize_results top-level summary."""

    def test_empty_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        result = analysis.summarize_results([])
        assert result["iterations"] == 0
        assert result["home_win_probability"] == 0.0

    def test_with_results(self):
        from app.analytics.core.simulation_analysis import SimulationAnalysis

        analysis = SimulationAnalysis("mlb")
        results = [
            {"home_score": 5, "away_score": 3, "winner": "home"},
            {"home_score": 3, "away_score": 4, "winner": "away"},
            {"home_score": 6, "away_score": 2, "winner": "home"},
            {"home_score": 7, "away_score": 1, "winner": "home"},
        ]
        summary = analysis.summarize_results(results)

        assert summary["iterations"] == 4
        assert summary["home_win_probability"] == 0.75
        assert summary["away_win_probability"] == 0.25
        assert summary["average_home_score"] == pytest.approx(5.25)
        assert summary["average_away_score"] == 2.5
        assert "most_common_scores" in summary
        assert "average_total" in summary
        assert "median_total" in summary


class TestCheckSimulationSanity:
    """Test check_simulation_sanity warnings."""

    def test_reasonable_stats_no_warnings(self):
        from app.analytics.core.simulation_analysis import check_simulation_sanity

        event_summary = {
            "home": {
                "avg_runs": 4.5,
                "avg_pa": 38,
                "avg_hr": 1.2,
                "pa_rates": {"k_pct": 0.22, "bb_pct": 0.08},
            },
            "away": {
                "avg_runs": 4.0,
                "avg_pa": 37,
                "avg_hr": 1.0,
                "pa_rates": {"k_pct": 0.20, "bb_pct": 0.07},
            },
            "game": {"extra_innings_pct": 0.10},
        }
        warnings = check_simulation_sanity(event_summary)
        assert warnings == []

    def test_unrealistic_runs_triggers_warning(self):
        from app.analytics.core.simulation_analysis import check_simulation_sanity

        event_summary = {
            "home": {
                "avg_runs": 20,
                "avg_pa": 38,
                "avg_hr": 1,
                "pa_rates": {"k_pct": 0.22, "bb_pct": 0.08},
            },
            "away": {
                "avg_runs": 0.5,
                "avg_pa": 38,
                "avg_hr": 1,
                "pa_rates": {"k_pct": 0.22, "bb_pct": 0.08},
            },
            "game": {"extra_innings_pct": 0.10},
        }
        warnings = check_simulation_sanity(event_summary)
        assert any("unrealistically high" in w for w in warnings)
        assert any("unrealistically low" in w for w in warnings)


class TestCheckBatchSanity:
    """Test check_batch_sanity flat WP detection."""

    def test_flat_wp_warning(self):
        from app.analytics.core.simulation_analysis import check_batch_sanity

        results = [
            {"home_win_probability": 0.50, "away_win_probability": 0.50},
            {"home_win_probability": 0.505, "away_win_probability": 0.495},
        ]
        warnings = check_batch_sanity(results)
        assert any("flat" in w.lower() or "49-51%" in w for w in warnings)

    def test_no_warning_for_varied_wp(self):
        from app.analytics.core.simulation_analysis import check_batch_sanity

        results = [
            {"home_win_probability": 0.65, "away_win_probability": 0.35},
            {"home_win_probability": 0.40, "away_win_probability": 0.60},
        ]
        warnings = check_batch_sanity(results)
        assert warnings == []
