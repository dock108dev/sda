"""Core training pipeline orchestrator.

Coordinates the full model training lifecycle: data loading,
feature extraction, model training, evaluation, and artifact
serialization.

Usage::

    pipeline = TrainingPipeline(
        sport="mlb",
        model_type="plate_appearance",
        config_name="mlb_pa_model",
    )
    result = pipeline.run(records)
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from .dataset_builder import DatasetBuilder
from .model_evaluator import ModelEvaluator
from .training_metadata import TrainingMetadata

logger = logging.getLogger(__name__)

_DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parents[3] / ".." / "models"

# Registry: (sport, model_type) -> (module_path, class_name)
_SPORT_TRAINING: dict[tuple[str, str], tuple[str, str]] = {
    ("mlb", "plate_appearance"): (
        "app.analytics.training.sports.mlb_training",
        "MLBTrainingPipeline",
    ),
    ("mlb", "game"): (
        "app.analytics.training.sports.mlb_training",
        "MLBTrainingPipeline",
    ),
}


class TrainingPipeline:
    """Orchestrate end-to-end model training.

    Args:
        sport: Sport code (e.g., ``"mlb"``).
        model_type: Model type (e.g., ``"plate_appearance"``, ``"game"``).
        config_name: Feature config name (YAML file stem).
        model_id: Unique identifier for this model version.
        random_state: Seed for reproducibility.
        test_size: Fraction of data held out for evaluation.
        artifact_dir: Base directory for saving artifacts.
    """

    def __init__(
        self,
        sport: str,
        model_type: str,
        config_name: str = "",
        *,
        model_id: str = "",
        random_state: int = 42,
        test_size: float = 0.2,
        artifact_dir: str | Path | None = None,
        feature_config: dict[str, Any] | None = None,
    ) -> None:
        self.sport = sport.lower()
        self.model_type = model_type
        self.config_name = config_name
        self.model_id = model_id or f"{sport}_{model_type}_v1"
        self.random_state = random_state
        self.test_size = test_size
        self.artifact_dir = Path(artifact_dir) if artifact_dir else _DEFAULT_ARTIFACT_DIR.resolve()

        self._dataset_builder = DatasetBuilder(
            sport=self.sport,
            model_type=self.model_type,
            config_name=self.config_name or None,
            feature_config=feature_config,
        )
        self._evaluator = ModelEvaluator()
        self._sport_pipeline = self._load_sport_pipeline()

        self._model: Any = None
        self._X_train: list[list[float]] = []
        self._X_test: list[list[float]] = []
        self._y_train: list[Any] = []
        self._y_test: list[Any] = []
        self._feature_names: list[str] = []
        self._metadata = TrainingMetadata(
            model_id=self.model_id,
            sport=self.sport,
            model_type=self.model_type,
            feature_config=self.config_name,
            random_state=self.random_state,
        )

    def _load_sport_pipeline(self) -> Any:
        """Lazily load sport-specific training pipeline."""
        entry = _SPORT_TRAINING.get((self.sport, self.model_type))
        if entry is None:
            return None
        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls()

    def load_training_data(
        self,
        records: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Load or accept training data.

        If ``records`` is provided, uses them directly.
        Otherwise delegates to the sport-specific pipeline.

        Args:
            records: Pre-loaded training records.

        Returns:
            List of training record dicts.
        """
        if records is not None:
            return records

        if self._sport_pipeline is not None:
            if self.model_type == "plate_appearance":
                return self._sport_pipeline.load_plate_appearance_training_data()
            if self.model_type == "game":
                return self._sport_pipeline.load_game_training_data()

        return []

    def build_dataset(
        self,
        records: list[dict[str, Any]],
        label_fn: Any | None = None,
    ) -> tuple[list[list[float]], list[Any], list[str]]:
        """Build feature matrix and labels from records.

        Args:
            records: Training record dicts.
            label_fn: Custom label extraction function.

        Returns:
            Tuple of ``(X, y, feature_names)``.
        """
        label_extractor = label_fn
        if label_extractor is None and self._sport_pipeline is not None:
            if self.model_type == "plate_appearance":
                label_extractor = self._sport_pipeline.pa_label_fn
            elif self.model_type == "game":
                label_extractor = self._sport_pipeline.game_label_fn

        X, y, names = self._dataset_builder.build(records, label_fn=label_extractor)
        self._feature_names = names
        return X, y, names

    def train_model(
        self,
        X_train: list[list[float]],
        y_train: list[Any],
        *,
        sklearn_model: Any = None,
    ) -> Any:
        """Train a scikit-learn model.

        Args:
            X_train: Training feature matrix.
            y_train: Training labels.
            sklearn_model: Optional pre-configured sklearn estimator.
                If ``None``, uses a default model for the model type.

        Returns:
            Trained model.
        """
        if sklearn_model is None:
            sklearn_model = self._default_model()

        sklearn_model.fit(X_train, y_train)
        # Attach feature names so inference can filter to the correct features
        sklearn_model._training_feature_names = list(self._feature_names)
        self._model = sklearn_model
        return sklearn_model

    def evaluate_model(
        self,
        model: Any,
        X_test: list[list[float]],
        y_test: list[Any],
    ) -> dict[str, Any]:
        """Evaluate the trained model.

        Uses ModelEvaluator for basic metrics and ModelMetrics for
        Brier score (classifiers only).

        Returns:
            Dict of evaluation metrics.
        """
        if self.model_type in ("plate_appearance", "game"):
            result = self._evaluator.evaluate_classifier(model, X_test, y_test)
            # Add Brier score via ModelMetrics
            if hasattr(model, "predict_proba") and X_test and y_test:
                try:
                    from app.analytics.models.core.model_metrics import ModelMetrics
                    y_pred = model.predict(X_test)
                    y_proba = model.predict_proba(X_test).tolist()
                    labels = list(model.classes_) if hasattr(model, "classes_") else None
                    mm = ModelMetrics()
                    mm_result = mm.evaluate_classifier(
                        list(y_test), list(y_pred), y_proba, labels=labels,
                    )
                    if "brier_score" in mm_result:
                        result["brier_score"] = mm_result["brier_score"]
                except Exception:
                    pass
            return result
        return self._evaluator.evaluate_regressor(model, X_test, y_test)

    def save_artifact(self, model: Any) -> tuple[str, str]:
        """Save model artifact and metadata.

        Returns:
            Tuple of ``(artifact_path, metadata_path)``.
        """
        sport_dir = self.artifact_dir / self.sport
        artifact_path = sport_dir / "artifacts" / f"{self.model_id}.pkl"
        metadata_path = sport_dir / "metadata" / f"{self.model_id}.json"

        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        import joblib
        joblib.dump(model, artifact_path)
        self._metadata.record_artifact(str(artifact_path))
        self._metadata.save(metadata_path)

        logger.info(
            "model_artifact_saved",
            extra={"artifact": str(artifact_path), "metadata": str(metadata_path)},
        )
        return str(artifact_path), str(metadata_path)

    def run(
        self,
        records: list[dict[str, Any]] | None = None,
        *,
        label_fn: Any | None = None,
        sklearn_model: Any = None,
    ) -> dict[str, Any]:
        """Execute the full training pipeline.

        Args:
            records: Training records. Loaded from sport pipeline if None.
            label_fn: Custom label extraction function.
            sklearn_model: Optional pre-configured sklearn estimator.

        Returns:
            Dict with artifact_path, metadata_path, metrics,
            feature_names, and sample counts.
        """
        data = self.load_training_data(records)
        if not data:
            return {"error": "no_training_data", "model_id": self.model_id}

        X, y, feature_names = self.build_dataset(data, label_fn=label_fn)
        if not X or not y:
            return {"error": "empty_dataset", "model_id": self.model_id}

        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=self.test_size, random_state=self.random_state,
        )

        self._X_train = X_train
        self._X_test = X_test
        self._y_train = y_train
        self._y_test = y_test

        model = self.train_model(X_train, y_train, sklearn_model=sklearn_model)
        metrics = self.evaluate_model(model, X_test, y_test)

        self._metadata.record_split(
            train_count=len(X_train),
            test_count=len(X_test),
            train_split=1.0 - self.test_size,
            test_split=self.test_size,
        )
        self._metadata.record_metrics(metrics)

        artifact_path, metadata_path = self.save_artifact(model)

        self._register_model(artifact_path, metadata_path, metrics)

        # Extract feature importance if available (tree-based models)
        feature_importance = _extract_feature_importance(model, feature_names)

        return {
            "model_id": self.model_id,
            "artifact_path": artifact_path,
            "metadata_path": metadata_path,
            "metrics": metrics,
            "feature_names": feature_names,
            "feature_importance": feature_importance,
            "train_count": len(X_train),
            "test_count": len(X_test),
        }

    def _register_model(
        self,
        artifact_path: str,
        metadata_path: str,
        metrics: dict[str, Any],
    ) -> None:
        """Register the trained model in the model registry.

        Uses the registry file co-located with the artifact directory
        so that test pipelines (which use tmp_path) don't pollute
        the production registry.
        """
        try:
            from app.analytics.models.core.model_registry import ModelRegistry
            registry_path = self.artifact_dir / "registry" / "registry.json"
            registry = ModelRegistry(registry_path=registry_path)
            registry.register_model(
                sport=self.sport,
                model_type=self.model_type,
                model_id=self.model_id,
                artifact_path=artifact_path,
                metadata=metrics,
                metadata_path=metadata_path,
            )
            logger.info(
                "model_registered_in_registry",
                extra={"model_id": self.model_id},
            )
        except Exception as exc:
            logger.warning(
                "model_registration_failed",
                extra={"model_id": self.model_id, "error": str(exc)},
            )

    def _default_model(self) -> Any:
        """Return a default sklearn model for the model type."""
        if self.model_type == "plate_appearance":
            from sklearn.ensemble import GradientBoostingClassifier
            return GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                random_state=self.random_state,
            )

        if self.model_type == "game":
            from sklearn.ensemble import GradientBoostingClassifier
            return GradientBoostingClassifier(
                n_estimators=100,
                max_depth=4,
                random_state=self.random_state,
            )

        from sklearn.ensemble import GradientBoostingRegressor
        return GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            random_state=self.random_state,
        )


def _extract_feature_importance(
    model: Any,
    feature_names: list[str],
) -> list[dict[str, Any]] | None:
    """Extract feature importance from a trained sklearn model.

    Returns a sorted list of {name, importance} dicts (highest first),
    or None if the model doesn't support feature_importances_.
    """
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return None

    items = []
    for name, imp in zip(feature_names, importances):
        items.append({"name": name, "importance": round(float(imp), 6)})

    items.sort(key=lambda x: x["importance"], reverse=True)
    return items
