"""Tests for analytics models, feature builder, training labels, and ensemble engine."""

from __future__ import annotations

import os
import pickle
from unittest.mock import MagicMock, Mock, patch

import pytest

# ── Batted ball model ──────────────────────────────────────────────

from app.analytics.models.sports.mlb.batted_ball_model import (
    BATTED_BALL_OUTCOMES,
    FEATURE_KEYS as BB_FEATURE_KEYS,
    MLBBattedBallModel,
    _normalize as bb_normalize,
)


class TestBattedBallNormalize:
    def test_zero_total_returns_uniform(self):
        probs = {k: 0.0 for k in BATTED_BALL_OUTCOMES}
        result = bb_normalize(probs)
        expected_val = round(1.0 / len(BATTED_BALL_OUTCOMES), 4)
        for k in BATTED_BALL_OUTCOMES:
            assert result[k] == expected_val

    def test_normal_case(self):
        probs = {"out": 0.6, "single": 0.2, "double": 0.1, "triple": 0.05, "home_run": 0.05}
        result = bb_normalize(probs)
        assert abs(sum(result.values()) - 1.0) < 0.01


class TestBattedBallModelPredict:
    def test_predict_proba_with_mock_model(self):
        model = MLBBattedBallModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = len(BB_FEATURE_KEYS)
        mock_ml.predict_proba.return_value = [[0.6, 0.2, 0.1, 0.05, 0.05]]
        mock_ml.classes_ = BATTED_BALL_OUTCOMES
        model._model = mock_ml

        result = model.predict_proba({"exit_velocity": 95.0})
        assert isinstance(result, dict)
        assert abs(sum(result.values()) - 1.0) < 0.01
        mock_ml.predict_proba.assert_called_once()

    def test_predict_with_model_feature_count_mismatch(self):
        """When n_features_in_ != len(FEATURE_KEYS), uses sorted keys."""
        model = MLBBattedBallModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = 3  # Different from len(FEATURE_KEYS)
        mock_ml.predict_proba.return_value = [[0.5, 0.2, 0.15, 0.1, 0.05]]
        mock_ml.classes_ = BATTED_BALL_OUTCOMES
        model._model = mock_ml

        features = {"a": 1.0, "b": 2.0, "c": 3.0}
        result = model._predict_with_model(features)
        assert isinstance(result, dict)
        # Should have called predict_proba with sorted keys [1.0, 2.0, 3.0]
        call_args = mock_ml.predict_proba.call_args[0][0]
        assert call_args == [[1.0, 2.0, 3.0]]

    def test_predict_with_model_no_predict_proba(self):
        """Model without predict_proba falls back to rule-based."""
        model = MLBBattedBallModel()
        mock_ml = MagicMock(spec=[])  # No predict_proba attr
        mock_ml.n_features_in_ = len(BB_FEATURE_KEYS)
        model._model = mock_ml

        result = model._predict_with_model({"exit_velocity": 90.0})
        assert isinstance(result, dict)
        assert abs(sum(result.values()) - 1.0) < 0.01

    def test_rule_based_launch_angle_gt_50(self):
        model = MLBBattedBallModel()
        result = model._predict_rule_based({"launch_angle": 55.0})
        assert result["out"] > 0.7  # Should increase out probability

    def test_rule_based_barrel_rate_gt_006(self):
        model = MLBBattedBallModel()
        result = model._predict_rule_based({"batter_barrel_rate": 0.10})
        assert isinstance(result, dict)
        assert abs(sum(result.values()) - 1.0) < 0.01

    def test_rule_based_power_index_with_ev_zero(self):
        model = MLBBattedBallModel()
        result = model._predict_rule_based({
            "batter_power_index": 1.5,
            "exit_velocity": 0,
        })
        assert isinstance(result, dict)
        assert abs(sum(result.values()) - 1.0) < 0.01

    def test_rule_based_hard_hit_rate_gt_035(self):
        model = MLBBattedBallModel()
        result = model._predict_rule_based({"batter_hard_hit_rate": 0.45})
        assert isinstance(result, dict)

    def test_rule_based_park_factor_not_1(self):
        model = MLBBattedBallModel()
        result = model._predict_rule_based({"park_factor": 1.15})
        assert isinstance(result, dict)
        assert abs(sum(result.values()) - 1.0) < 0.01


# ── Pitch model ────────────────────────────────────────────────────

from app.analytics.models.sports.mlb.pitch_model import (
    FEATURE_KEYS as PITCH_FEATURE_KEYS,
    MLBPitchOutcomeModel,
    PITCH_OUTCOMES,
    _normalize as pitch_normalize,
)


class TestPitchNormalize:
    def test_zero_total_returns_uniform(self):
        probs = {k: 0.0 for k in PITCH_OUTCOMES}
        result = pitch_normalize(probs)
        expected_val = round(1.0 / len(PITCH_OUTCOMES), 4)
        for k in PITCH_OUTCOMES:
            assert result[k] == expected_val


class TestPitchModelPredict:
    def test_predict_proba_with_mock_model(self):
        model = MLBPitchOutcomeModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = len(PITCH_FEATURE_KEYS)
        mock_ml.predict_proba.return_value = [[0.3, 0.2, 0.15, 0.2, 0.15]]
        mock_ml.classes_ = PITCH_OUTCOMES
        model._model = mock_ml

        result = model.predict_proba({"pitcher_k_rate": 0.24})
        assert isinstance(result, dict)
        assert abs(sum(result.values()) - 1.0) < 0.01

    def test_predict_with_model_feature_count_mismatch(self):
        model = MLBPitchOutcomeModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = 2
        mock_ml.predict_proba.return_value = [[0.3, 0.2, 0.15, 0.2, 0.15]]
        mock_ml.classes_ = PITCH_OUTCOMES
        model._model = mock_ml

        features = {"x": 1.0, "y": 2.0}
        result = model._predict_with_model(features)
        call_args = mock_ml.predict_proba.call_args[0][0]
        assert call_args == [[1.0, 2.0]]

    def test_predict_with_model_no_predict_proba(self):
        model = MLBPitchOutcomeModel()
        mock_ml = MagicMock(spec=[])
        mock_ml.n_features_in_ = len(PITCH_FEATURE_KEYS)
        model._model = mock_ml

        result = model._predict_with_model({"pitcher_k_rate": 0.24})
        assert isinstance(result, dict)
        assert abs(sum(result.values()) - 1.0) < 0.01


# ── Game model ─────────────────────────────────────────────────────

from app.analytics.models.sports.mlb.game_model import (
    FEATURE_KEYS as GAME_FEATURE_KEYS,
    MLBGameModel,
)


class TestGameModelPredict:
    def test_predict_proba_with_mock_model(self):
        model = MLBGameModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = len(GAME_FEATURE_KEYS)
        mock_ml.predict_proba.return_value = [[0.4, 0.6]]
        model._model = mock_ml

        result = model.predict_proba({"home_contact_rate": 0.8})
        assert "home_win" in result
        assert "away_win" in result
        assert abs(result["home_win"] + result["away_win"] - 1.0) < 0.01

    def test_predict_with_model_predict_proba(self):
        model = MLBGameModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = len(GAME_FEATURE_KEYS)
        mock_ml.predict_proba.return_value = [[0.35, 0.65]]
        model._model = mock_ml

        result = model._predict_with_model({"home_contact_rate": 0.8})
        assert result["home_win_probability"] == 0.65

    def test_predict_with_model_no_predict_proba_uses_predict(self):
        model = MLBGameModel()
        mock_ml = MagicMock(spec=["predict", "n_features_in_"])
        mock_ml.n_features_in_ = len(GAME_FEATURE_KEYS)
        mock_ml.predict.return_value = [0.7]
        model._model = mock_ml

        result = model._predict_with_model({"home_contact_rate": 0.8})
        assert result["home_win_probability"] == 0.7

    def test_predict_with_model_no_predict_methods(self):
        """Model without predict_proba or predict uses default."""
        model = MLBGameModel()
        mock_ml = MagicMock(spec=["n_features_in_"])
        mock_ml.n_features_in_ = len(GAME_FEATURE_KEYS)
        model._model = mock_ml

        result = model._predict_with_model({})
        assert result["home_win_probability"] == 0.54

    def test_predict_with_model_feature_count_mismatch(self):
        model = MLBGameModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = 2
        mock_ml.predict_proba.return_value = [[0.4, 0.6]]
        model._model = mock_ml

        features = {"a": 1.0, "b": 2.0}
        result = model._predict_with_model(features)
        call_args = mock_ml.predict_proba.call_args[0][0]
        assert call_args == [[1.0, 2.0]]


# ── Run expectancy model ──────────────────────────────────────────

from app.analytics.models.sports.mlb.run_expectancy_model import (
    FEATURE_KEYS as RE_FEATURE_KEYS,
    MLBRunExpectancyModel,
)


class TestRunExpectancyModel:
    def test_predict_proba_path(self):
        model = MLBRunExpectancyModel()
        result = model.predict_proba({"base_state": 0, "outs": 0})
        assert "expected_runs" in result
        assert result["expected_runs"] > 0

    def test_predict_value_path(self):
        model = MLBRunExpectancyModel()
        val = model.predict_value({"base_state": 7, "outs": 0})
        assert val > 2.0

    def test_rule_based_batter_quality_gt_0(self):
        model = MLBRunExpectancyModel()
        base = model._predict_rule_based({"base_state": 1, "outs": 1})
        adjusted = model._predict_rule_based({
            "base_state": 1, "outs": 1, "batter_quality": 1.0,
        })
        assert adjusted > base * 0.99  # Should be ~1.2x

    def test_rule_based_pitcher_quality_gt_0(self):
        model = MLBRunExpectancyModel()
        base = model._predict_rule_based({"base_state": 1, "outs": 1})
        adjusted = model._predict_rule_based({
            "base_state": 1, "outs": 1, "pitcher_quality": 1.0,
        })
        assert adjusted < base  # Good pitcher reduces run expectancy

    def test_predict_value_with_mock_model(self):
        model = MLBRunExpectancyModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = len(RE_FEATURE_KEYS)
        mock_ml.predict.return_value = [1.5]
        model._model = mock_ml

        result = model.predict_value({"base_state": 3, "outs": 1})
        assert result == 1.5

    def test_predict_value_with_model_feature_mismatch(self):
        model = MLBRunExpectancyModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = 2
        mock_ml.predict.return_value = [0.8]
        model._model = mock_ml

        result = model.predict_value({"a": 1.0, "b": 2.0})
        assert result == 0.8

    def test_predict_value_with_model_negative_clamped(self):
        model = MLBRunExpectancyModel()
        mock_ml = MagicMock()
        mock_ml.n_features_in_ = len(RE_FEATURE_KEYS)
        mock_ml.predict.return_value = [-0.5]
        model._model = mock_ml

        result = model.predict_value({})
        assert result == 0.0


# ── Model interface ───────────────────────────────────────────────

from app.analytics.models.core.model_interface import BaseModel


class ConcreteModel(BaseModel):
    model_type = "test"
    sport = "test"

    def predict(self, features):
        return {}

    def predict_proba(self, features):
        return {}


class TestBaseModelLoad:
    def test_load_none_path_no_op(self):
        model = ConcreteModel()
        model.load(None)
        assert model._model is None
        assert model._loaded is False

    def test_load_with_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODEL_SIGNING_KEY", "a" * 32)

        model_file = tmp_path / "model.pkl"
        dummy = {"type": "dummy_model"}
        with open(model_file, "wb") as f:
            pickle.dump(dummy, f)

        from app.analytics.models.core.artifact_signing import sign_artifact
        sign_artifact(str(model_file))

        model = ConcreteModel()
        model.load(str(model_file))
        assert model._loaded is True
        assert model._model == dummy

    def test_get_info(self):
        model = ConcreteModel()
        info = model.get_info()
        assert info["model_type"] == "test"
        assert info["sport"] == "test"
        assert info["loaded"] is False


# ── Model loader ──────────────────────────────────────────────────

from app.analytics.models.core.model_loader import ModelLoader


class TestModelLoader:
    def test_file_not_found(self):
        loader = ModelLoader()
        with pytest.raises(FileNotFoundError):
            loader.load_model("/nonexistent/path/model.pkl")

    def test_joblib_failure_falls_back_to_pickle(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODEL_SIGNING_KEY", "a" * 32)
        from app.analytics.models.core.artifact_signing import sign_artifact

        model_file = tmp_path / "model.pkl"
        dummy = {"fallback": True}
        with open(model_file, "wb") as f:
            pickle.dump(dummy, f)
        sign_artifact(str(model_file))

        loader = ModelLoader()
        # Patch joblib to fail, so it falls back to pickle
        with patch.object(loader, "_load_joblib", side_effect=Exception("joblib fail")):
            result = loader.load_model(str(model_file))
        assert result == dummy

    def test_both_failures_raise_runtime_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODEL_SIGNING_KEY", "a" * 32)
        from app.analytics.models.core.artifact_signing import sign_artifact

        model_file = tmp_path / "model.bin"
        model_file.write_bytes(b"not a valid model")
        sign_artifact(str(model_file))

        loader = ModelLoader()
        with patch.object(loader, "_load_joblib", side_effect=Exception("joblib fail")):
            with patch.object(loader, "_load_pickle", side_effect=Exception("pickle fail")):
                with pytest.raises(RuntimeError, match="Failed to load model"):
                    loader.load_model(str(model_file))


# ── MLB feature builder ──────────────────────────────────────────

from app.analytics.features.sports.mlb_features import MLBFeatureBuilder


class TestMLBFeatureBuilder:
    def test_build_features_pitch(self):
        builder = MLBFeatureBuilder()
        profiles = {
            "batter_profile": {"contact_rate": 0.8, "swing_rate": 0.5,
                               "zone_swing_rate": 0.65, "chase_rate": 0.3},
            "pitcher_profile": {"k_rate": 0.24, "walk_rate": 0.08,
                                "zone_rate": 0.5, "contact_allowed": 0.78},
            "context": {"count_balls": 2, "count_strikes": 1},
        }
        result = builder.build_features(profiles, model_type="pitch")
        d = result.to_dict()
        assert "pitcher_k_rate" in d
        assert "count_balls" in d

    def test_build_features_batted_ball(self):
        builder = MLBFeatureBuilder()
        profiles = {
            "batter_profile": {"barrel_rate": 0.09, "hard_hit_rate": 0.4,
                               "power_index": 1.1},
            "pitcher_profile": {"hard_hit_pct_against": 0.35},
            "context": {"exit_velocity": 100.0, "launch_angle": 25.0,
                        "spray_angle": 10.0, "park_factor": 1.05},
        }
        result = builder.build_features(profiles, model_type="batted_ball")
        d = result.to_dict()
        assert "exit_velocity" in d
        assert "batter_barrel_rate" in d

    def test_build_pitch_features_directly(self):
        builder = MLBFeatureBuilder()
        batter = {"contact_rate": 0.8, "swing_rate": 0.5,
                  "zone_swing_rate": 0.65, "chase_rate": 0.3}
        pitcher = {"k_rate": 0.24, "walk_rate": 0.08,
                   "zone_rate": 0.5, "contact_allowed": 0.78}
        context = {"count_balls": 1, "count_strikes": 2}
        result = builder.build_pitch_features(batter, pitcher, context)
        assert result.size == 10  # 10 features in _PITCH_FEATURES

    def test_build_batted_ball_features_directly(self):
        builder = MLBFeatureBuilder()
        batter = {"barrel_rate": 0.09, "hard_hit_rate": 0.4, "power_index": 1.1}
        pitcher = {"hard_hit_pct_against": 0.35}
        context = {"exit_velocity": 100.0, "launch_angle": 25.0,
                   "spray_angle": 10.0, "park_factor": 1.05}
        result = builder.build_batted_ball_features(batter, pitcher, context)
        assert result.size == 8  # 8 features in _BATTED_BALL_FEATURES

    def test_build_features_unknown_model_type(self):
        builder = MLBFeatureBuilder()
        result = builder.build_features({}, model_type="unknown_type")
        assert result.size == 0


# ── MLB training labels ──────────────────────────────────────────

from app.analytics.training.sports.mlb_training import MLBTrainingPipeline


class TestMLBTrainingPipeline:
    def test_pitch_label_fn_valid(self):
        result = MLBTrainingPipeline.pitch_label_fn({"outcome": "ball"})
        assert result == "ball"

    def test_pitch_label_fn_invalid(self):
        result = MLBTrainingPipeline.pitch_label_fn({"outcome": "garbage"})
        assert result is None

    def test_pitch_label_fn_none(self):
        result = MLBTrainingPipeline.pitch_label_fn({})
        assert result is None

    def test_batted_ball_label_fn_valid(self):
        result = MLBTrainingPipeline.batted_ball_label_fn({"outcome": "single"})
        assert result == "single"

    def test_batted_ball_label_fn_invalid(self):
        result = MLBTrainingPipeline.batted_ball_label_fn({"outcome": "error"})
        assert result is None

    def test_batted_ball_label_fn_none(self):
        result = MLBTrainingPipeline.batted_ball_label_fn({})
        assert result is None

    def test_game_label_fn_with_label_key(self):
        result = MLBTrainingPipeline.game_label_fn({"label": 1})
        assert result == 1

    def test_game_label_fn_with_label_key_zero(self):
        result = MLBTrainingPipeline.game_label_fn({"label": 0})
        assert result == 0

    def test_pa_label_fn_v2_outcome(self):
        result = MLBTrainingPipeline.pa_label_fn({"outcome": "walk_or_hbp"})
        assert result == "walk_or_hbp"

    def test_pa_label_fn_v2_ball_in_play_out(self):
        result = MLBTrainingPipeline.pa_label_fn({"outcome": "ball_in_play_out"})
        assert result == "ball_in_play_out"

    def test_pa_label_fn_none(self):
        result = MLBTrainingPipeline.pa_label_fn({})
        assert result is None

    def test_pa_label_fn_invalid(self):
        result = MLBTrainingPipeline.pa_label_fn({"outcome": "balk"})
        assert result is None


# ── Ensemble engine ───────────────────────────────────────────────

from app.analytics.ensemble.ensemble_engine import EnsembleEngine, _normalize as ens_normalize


class TestEnsembleEngine:
    def test_combine_with_zero_weights(self):
        engine = EnsembleEngine()
        preds = {
            "a": {"win": 0.6, "lose": 0.4},
            "b": {"win": 0.8, "lose": 0.2},
        }
        weights = {"a": 0.0, "b": 0.0}
        result = engine.combine(preds, weights)
        # Zero weights -> uniform weighting
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_combine_with_negative_weights(self):
        engine = EnsembleEngine()
        preds = {
            "a": {"win": 0.6, "lose": 0.4},
            "b": {"win": 0.8, "lose": 0.2},
        }
        weights = {"a": -1.0, "b": -1.0}
        result = engine.combine(preds, weights)
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_combine_empty_predictions(self):
        engine = EnsembleEngine()
        result = engine.combine({}, {"a": 1.0})
        assert result == {}


class TestEnsembleNormalize:
    def test_zero_total(self):
        result = ens_normalize({"a": 0.0, "b": 0.0})
        assert abs(result["a"] - 0.5) < 0.001
        assert abs(result["b"] - 0.5) < 0.001

    def test_empty_dict(self):
        result = ens_normalize({})
        assert result == {}
