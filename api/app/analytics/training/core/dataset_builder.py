"""Dataset builder for ML training.

Transforms raw historical records into supervised learning datasets
using the existing analytics pipeline (Aggregation -> Metrics ->
Profiles -> FeatureBuilder).

Usage::

    builder = DatasetBuilder("mlb", "plate_appearance", "mlb_pa_model")
    X, y, feature_names = builder.build(raw_records)
"""

from __future__ import annotations

import logging
from typing import Any

from app.analytics.features.core.feature_builder import FeatureBuilder

logger = logging.getLogger(__name__)


class DatasetBuilder:
    """Build training datasets from raw historical records.

    Delegates feature extraction to the FeatureBuilder and applies
    feature configuration for consistent feature selection.
    """

    def __init__(
        self,
        sport: str,
        model_type: str,
        config_name: str | None = None,
        *,
        feature_config: dict[str, Any] | None = None,
    ) -> None:
        self.sport = sport.lower()
        self.model_type = model_type
        self.config_name = config_name
        self._feature_builder = FeatureBuilder()
        self._config = feature_config or self._load_config()

    def _load_config(self) -> dict[str, Any] | None:
        """Load feature config if a config name is specified.

        Currently returns None — feature configs are loaded from the
        DB-backed ``AnalyticsFeatureConfig`` and passed directly to
        the training pipeline rather than being resolved by name here.
        """
        return None

    def build(
        self,
        records: list[dict[str, Any]],
        label_fn: Any | None = None,
    ) -> tuple[list[list[float]], list[Any], list[str]]:
        """Build feature matrix and labels from records.

        Args:
            records: List of dicts, each containing entity profiles
                and a label. Profile keys depend on sport and model type.
            label_fn: Callable that extracts a label from a record.
                If ``None``, looks for a ``"label"`` key.

        Returns:
            Tuple of ``(X, y, feature_names)`` where X is the feature
            matrix, y is the label vector, and feature_names is the
            ordered list of feature names.
        """
        if not records:
            return [], [], []

        if label_fn is None:
            label_fn = _default_label_fn

        X: list[list[float]] = []
        y: list[Any] = []
        feature_names: list[str] = []

        for i, record in enumerate(records):
            label = label_fn(record)
            if label is None:
                continue

            vec = self._feature_builder.build_features(
                self.sport,
                record,
                self.model_type,
                config=self._config,
            )

            if i == 0:
                feature_names = vec.feature_names

            X.append(vec.to_array())
            y.append(label)

        return X, y, feature_names

    def build_training_examples(
        self,
        raw_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Transform raw records into training-ready examples.

        Subclasses or sport-specific modules can override this to
        add preprocessing. Default pass-through.
        """
        return raw_records

    def build_feature_matrix(
        self,
        examples: list[dict[str, Any]],
    ) -> tuple[list[list[float]], list[str]]:
        """Build feature matrix without labels."""
        return self._feature_builder.build_dataset(
            self.sport,
            examples,
            self.model_type,
            config=self._config,
        )

    def build_labels(
        self,
        examples: list[dict[str, Any]],
        label_fn: Any | None = None,
    ) -> list[Any]:
        """Extract labels from examples."""
        if label_fn is None:
            label_fn = _default_label_fn
        return [label_fn(e) for e in examples if label_fn(e) is not None]


def _default_label_fn(record: dict[str, Any]) -> Any:
    """Default label extractor: looks for 'label' key."""
    return record.get("label")
