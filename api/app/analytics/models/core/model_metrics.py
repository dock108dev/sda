"""Standardized model evaluation metrics.

Computes classification and regression metrics for trained models,
builds structured performance reports, and compares model versions.

Usage::

    metrics = ModelMetrics()
    result = metrics.evaluate_classifier(
        y_true=[1, 0, 1],
        y_pred=[1, 0, 0],
        y_proba=[[0.2, 0.8], [0.7, 0.3], [0.6, 0.4]],
    )
    report = metrics.build_report(
        model_id="mlb_pa_v1",
        model_type="plate_appearance",
        sport="mlb",
        evaluation=result,
    )
"""

from __future__ import annotations

import math
from typing import Any


class ModelMetrics:
    """Compute and compare model evaluation metrics.

    Supports both classification (accuracy, log loss, Brier score)
    and regression (MAE, RMSE) models.
    """

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def evaluate_classifier(
        self,
        y_true: list[Any],
        y_pred: list[Any],
        y_proba: list[list[float]] | list[float] | None = None,
        *,
        labels: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate a classification model.

        Args:
            y_true: Ground truth labels.
            y_pred: Predicted labels.
            y_proba: Predicted probabilities. For binary classification
                this can be a 1-D list of positive-class probabilities.
                For multiclass, a 2-D list of shape (n, n_classes).
            labels: Optional ordered class labels for log_loss.

        Returns:
            Dict with accuracy, log_loss, brier_score, sample_count,
            and class_distribution.
        """
        n = len(y_true)
        if n == 0:
            return {"accuracy": 0.0, "sample_count": 0}

        correct = sum(1 for a, p in zip(y_true, y_pred, strict=False) if a == p)
        accuracy = correct / n

        result: dict[str, Any] = {
            "accuracy": round(accuracy, 4),
            "sample_count": n,
            "class_distribution": _class_distribution(y_true),
        }

        if y_proba is not None:
            proba_2d = _ensure_2d(y_proba)
            result["log_loss"] = round(_log_loss(y_true, proba_2d, labels), 4)
            result["brier_score"] = round(_brier_score(y_true, proba_2d, labels), 4)

        return result

    # ------------------------------------------------------------------
    # Regression
    # ------------------------------------------------------------------

    def evaluate_regressor(
        self,
        y_true: list[float],
        y_pred: list[float],
    ) -> dict[str, Any]:
        """Evaluate a regression model.

        Args:
            y_true: Ground truth values.
            y_pred: Predicted values.

        Returns:
            Dict with mae, rmse, and sample_count.
        """
        n = len(y_true)
        if n == 0:
            return {"mae": 0.0, "rmse": 0.0, "sample_count": 0}

        abs_errors = [abs(a - p) for a, p in zip(y_true, y_pred, strict=False)]
        sq_errors = [(a - p) ** 2 for a, p in zip(y_true, y_pred, strict=False)]

        mae = sum(abs_errors) / n
        rmse = math.sqrt(sum(sq_errors) / n)

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "sample_count": n,
        }

    # ------------------------------------------------------------------
    # Report building
    # ------------------------------------------------------------------

    def build_report(
        self,
        model_id: str,
        model_type: str,
        sport: str,
        evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a standardized performance report.

        Args:
            model_id: Unique model identifier.
            model_type: Model type (e.g., ``"plate_appearance"``).
            sport: Sport code.
            evaluation: Evaluation dict from ``evaluate_classifier``
                or ``evaluate_regressor``.

        Returns:
            Structured report dict.
        """
        return {
            "model_id": model_id,
            "model_type": model_type,
            "sport": sport,
            "dataset_size": evaluation.get("sample_count", 0),
            "metrics": {
                k: v
                for k, v in evaluation.items()
                if k not in ("sample_count", "class_distribution")
            },
        }

    # ------------------------------------------------------------------
    # Model comparison
    # ------------------------------------------------------------------

    def compare_models(
        self,
        metrics_a: dict[str, Any],
        metrics_b: dict[str, Any],
        *,
        model_a_id: str = "model_a",
        model_b_id: str = "model_b",
    ) -> dict[str, Any]:
        """Compare two sets of evaluation metrics.

        For accuracy and winner_accuracy, higher is better.
        For log_loss, brier_score, mae, rmse — lower is better.

        Args:
            metrics_a: Metrics dict for model A.
            metrics_b: Metrics dict for model B.
            model_a_id: Identifier for model A.
            model_b_id: Identifier for model B.

        Returns:
            Dict with ``better_model`` and ``metric_differences``.
        """
        lower_is_better = {"log_loss", "brier_score", "mae", "rmse", "mae_score", "mae_total"}
        higher_is_better = {"accuracy", "winner_accuracy"}

        diffs: dict[str, float] = {}
        a_wins = 0
        b_wins = 0

        all_keys = set(metrics_a.keys()) | set(metrics_b.keys())
        for key in all_keys:
            val_a = metrics_a.get(key)
            val_b = metrics_b.get(key)
            if not isinstance(val_a, int | float) or not isinstance(val_b, int | float):
                continue

            diff = val_b - val_a
            diffs[key] = round(diff, 4)

            if key in lower_is_better:
                if val_b < val_a:
                    b_wins += 1
                elif val_a < val_b:
                    a_wins += 1
            elif key in higher_is_better:
                if val_b > val_a:
                    b_wins += 1
                elif val_a > val_b:
                    a_wins += 1

        better = model_b_id if b_wins > a_wins else model_a_id

        return {
            "better_model": better,
            "metric_differences": diffs,
            "model_a": model_a_id,
            "model_b": model_b_id,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _class_distribution(labels: list[Any]) -> dict[str, int]:
    """Count occurrences of each label."""
    dist: dict[str, int] = {}
    for label in labels:
        key = str(label)
        dist[key] = dist.get(key, 0) + 1
    return dist


def _ensure_2d(proba: list[list[float]] | list[float]) -> list[list[float]]:
    """Convert 1-D probability list to 2-D (binary classification)."""
    if not proba:
        return []
    if isinstance(proba[0], list | tuple):
        return proba  # type: ignore[return-value]
    # 1-D: treat as positive class probability for binary
    return [[1.0 - p, p] for p in proba]  # type: ignore[union-attr]


def _log_loss(
    y_true: list[Any],
    y_proba: list[list[float]],
    labels: list[Any] | None = None,
) -> float:
    """Compute log loss (cross-entropy).

    Handles both binary and multiclass cases without requiring
    scikit-learn at import time.
    """
    if not y_true or not y_proba:
        return 0.0

    if labels is None:
        labels = sorted(set(y_true))

    label_to_idx = {label: i for i, label in enumerate(labels)}
    eps = 1e-15
    total = 0.0
    n = len(y_true)

    for true_label, probs in zip(y_true, y_proba, strict=False):
        idx = label_to_idx.get(true_label)
        if idx is None or idx >= len(probs):
            total += -math.log(eps)
            continue
        p = max(eps, min(1.0 - eps, probs[idx]))
        total += -math.log(p)

    return total / n


def _brier_score(
    y_true: list[Any],
    y_proba: list[list[float]],
    labels: list[Any] | None = None,
) -> float:
    """Compute Brier score (mean squared error of probabilities).

    For binary: (predicted_prob - actual_outcome)^2
    For multiclass: sum of squared errors across classes, averaged.
    """
    if not y_true or not y_proba:
        return 0.0

    if labels is None:
        labels = sorted(set(y_true))

    label_to_idx = {label: i for i, label in enumerate(labels)}
    n_classes = len(labels)
    total = 0.0
    n = len(y_true)

    for true_label, probs in zip(y_true, y_proba, strict=False):
        one_hot = [0.0] * n_classes
        idx = label_to_idx.get(true_label)
        if idx is not None and idx < n_classes:
            one_hot[idx] = 1.0

        for j in range(min(len(probs), n_classes)):
            total += (probs[j] - one_hot[j]) ** 2

    return total / n
