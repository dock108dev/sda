"""Model evaluation utilities.

Computes classification and regression metrics for trained models,
returning structured JSON-serializable evaluation output.

Usage::

    evaluator = ModelEvaluator()
    results = evaluator.evaluate_classifier(model, X_test, y_test)
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class ModelEvaluator:
    """Evaluate trained scikit-learn models."""

    def evaluate_classifier(
        self,
        model: Any,
        X_test: list[list[float]],
        y_test: list[Any],
    ) -> dict[str, Any]:
        """Evaluate a classification model.

        Args:
            model: Trained scikit-learn classifier.
            X_test: Test feature matrix.
            y_test: Test labels.

        Returns:
            Dict with accuracy, log_loss (if available), sample_count,
            and class_distribution.
        """
        if not X_test or not y_test:
            return {"accuracy": 0.0, "sample_count": 0}

        from sklearn.metrics import accuracy_score, log_loss

        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        result: dict[str, Any] = {
            "accuracy": round(accuracy, 4),
            "sample_count": len(y_test),
        }

        if hasattr(model, "predict_proba"):
            try:
                y_proba = model.predict_proba(X_test)
                result["log_loss"] = round(log_loss(y_test, y_proba), 4)
            except Exception as exc:
                logger.debug("log_loss_computation_failed", extra={"error": str(exc)})

        result["class_distribution"] = _class_distribution(y_test)
        return result

    def evaluate_regressor(
        self,
        model: Any,
        X_test: list[list[float]],
        y_test: list[float],
    ) -> dict[str, Any]:
        """Evaluate a regression model.

        Args:
            model: Trained scikit-learn regressor.
            X_test: Test feature matrix.
            y_test: Test labels.

        Returns:
            Dict with mae, rmse, and sample_count.
        """
        if not X_test or not y_test:
            return {"mae": 0.0, "rmse": 0.0, "sample_count": 0}

        from sklearn.metrics import mean_absolute_error, mean_squared_error

        y_pred = model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        mse = mean_squared_error(y_test, y_pred)
        rmse = math.sqrt(mse)

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "sample_count": len(y_test),
        }


def _class_distribution(labels: list[Any]) -> dict[str, int]:
    """Count occurrences of each label."""
    dist: dict[str, int] = {}
    for label in labels:
        key = str(label)
        dist[key] = dist.get(key, 0) + 1
    return dist
