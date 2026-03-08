"""Tests for feature config enforcement through the training pipeline chain.

Verifies that DB-backed feature configurations (enabled/weight) are
properly threaded from training_tasks → TrainingPipeline → DatasetBuilder
→ FeatureBuilder._apply_config().
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.analytics.features.core.feature_builder import FeatureBuilder, _apply_config
from app.analytics.features.core.feature_vector import FeatureVector
from app.analytics.training.core.dataset_builder import DatasetBuilder
from app.tasks.training_tasks import _feature_config_to_dict


class TestFeatureConfigToDict:
    """Verify the DB → dict converter in training_tasks."""

    def test_none_input_returns_none(self) -> None:
        assert _feature_config_to_dict(None) is None

    def test_empty_features_returns_none(self) -> None:
        class FakeConfig:
            features = []

        assert _feature_config_to_dict(FakeConfig()) is None

    def test_no_features_attr_returns_none(self) -> None:
        class FakeConfig:
            pass

        assert _feature_config_to_dict(FakeConfig()) is None

    def test_converts_jsonb_array_to_dict(self) -> None:
        class FakeConfig:
            features = [
                {"name": "contact_rate", "enabled": True, "weight": 0.9},
                {"name": "power_index", "enabled": False, "weight": 1.0},
                {"name": "barrel_rate", "enabled": True, "weight": 1.5},
            ]

        result = _feature_config_to_dict(FakeConfig())
        assert result == {
            "contact_rate": {"enabled": True, "weight": 0.9},
            "power_index": {"enabled": False, "weight": 1.0},
            "barrel_rate": {"enabled": True, "weight": 1.5},
        }

    def test_defaults_enabled_true_weight_one(self) -> None:
        class FakeConfig:
            features = [{"name": "feat_a"}]

        result = _feature_config_to_dict(FakeConfig())
        assert result == {"feat_a": {"enabled": True, "weight": 1.0}}

    def test_skips_entries_without_name(self) -> None:
        class FakeConfig:
            features = [
                {"name": "valid", "enabled": True},
                {"enabled": False, "weight": 0.5},  # no name
            ]

        result = _feature_config_to_dict(FakeConfig())
        assert result == {"valid": {"enabled": True, "weight": 1.0}}


class TestApplyConfig:
    """Verify _apply_config filters disabled features and applies weights."""

    def test_disabled_feature_excluded(self) -> None:
        vec = FeatureVector(
            {"feat_a": 1.0, "feat_b": 2.0, "feat_c": 3.0},
            feature_order=["feat_a", "feat_b", "feat_c"],
        )
        config = {
            "feat_a": {"enabled": True, "weight": 1.0},
            "feat_b": {"enabled": False, "weight": 1.0},
            "feat_c": {"enabled": True, "weight": 1.0},
        }
        result = _apply_config(vec, config)
        assert result.feature_names == ["feat_a", "feat_c"]
        assert result.to_array() == [1.0, 3.0]

    def test_weight_applied(self) -> None:
        vec = FeatureVector({"feat_a": 2.0, "feat_b": 4.0})
        config = {
            "feat_a": {"enabled": True, "weight": 0.5},
            "feat_b": {"enabled": True, "weight": 2.0},
        }
        result = _apply_config(vec, config)
        assert result.to_array() == [1.0, 8.0]

    def test_unconfigured_features_pass_through(self) -> None:
        vec = FeatureVector({"known": 1.0, "unknown": 5.0})
        config = {"known": {"enabled": True, "weight": 1.0}}
        result = _apply_config(vec, config)
        assert "unknown" in result.feature_names
        assert result.get("unknown") == 5.0

    def test_empty_config_passes_all_through(self) -> None:
        vec = FeatureVector({"a": 1.0, "b": 2.0})
        result = _apply_config(vec, {})
        assert result.feature_names == ["a", "b"]
        assert result.to_array() == [1.0, 2.0]


class TestDatasetBuilderConfigPropagation:
    """Verify DatasetBuilder passes config through to FeatureBuilder."""

    def test_config_reaches_feature_builder(self) -> None:
        config = {
            "feat_a": {"enabled": True, "weight": 1.0},
            "feat_b": {"enabled": False, "weight": 1.0},
        }
        builder = DatasetBuilder("mlb", "plate_appearance", feature_config=config)
        assert builder._config == config

    def test_no_config_defaults_to_none(self) -> None:
        builder = DatasetBuilder("mlb", "plate_appearance")
        assert builder._config is None

    def test_build_passes_config_to_feature_builder(self) -> None:
        """Config dict is passed through to FeatureBuilder.build_features()."""
        config = {
            "batter_contact_rate": {"enabled": True, "weight": 1.0},
            "batter_power_index": {"enabled": False, "weight": 1.0},
        }

        # After _apply_config, only enabled features remain
        filtered_vec = FeatureVector(
            {"batter_contact_rate": 0.8},
            feature_order=["batter_contact_rate"],
        )

        builder = DatasetBuilder("mlb", "plate_appearance", feature_config=config)

        with patch.object(
            builder._feature_builder,
            "build_features",
            return_value=filtered_vec,
        ) as mock_build:
            records = [{"label": "strikeout", "batter_profile": {}, "pitcher_profile": {}}]
            X, y, names = builder.build(records, label_fn=lambda r: r.get("label"))

        mock_build.assert_called_once()
        # Verify config was passed to build_features
        _, kwargs = mock_build.call_args
        assert kwargs.get("config") == config

        assert names == ["batter_contact_rate"]
        assert len(X) == 1
        assert X[0] == [0.8]
