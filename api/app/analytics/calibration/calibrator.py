"""Probability calibration via isotonic regression.

Trains on (raw_sim_wp, actual_outcome) pairs to produce a monotonic
mapping from raw sim probability to historically-accurate probability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    """Evaluation metrics for a calibration model."""

    brier_before: float
    brier_after: float
    brier_improvement: float
    sample_count: int
    reliability_bins: list[dict[str, float]]


class SimCalibrator:
    """Isotonic regression calibrator for sim win probabilities.

    Maps raw Monte Carlo sim WP to historically-calibrated probabilities.
    The mapping is monotonic — if the sim says team A is more likely
    than team B, calibration preserves that ordering.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._trained: bool = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(
        self,
        sim_wps: list[float],
        actual_outcomes: list[bool],
    ) -> CalibrationMetrics:
        """Train the calibrator on historical data.

        Args:
            sim_wps: Raw sim home win probabilities (0-1).
            actual_outcomes: True if home team won, False otherwise.

        Returns:
            CalibrationMetrics with before/after Brier scores.
        """
        from sklearn.isotonic import IsotonicRegression

        if len(sim_wps) < 10:
            raise ValueError(
                f"Need at least 10 samples for calibration, got {len(sim_wps)}"
            )

        y = [1.0 if o else 0.0 for o in actual_outcomes]

        # Brier before calibration
        brier_before = sum((p - a) ** 2 for p, a in zip(sim_wps, y)) / len(y)

        # Fit isotonic regression
        self._model = IsotonicRegression(
            y_min=0.01, y_max=0.99, out_of_bounds="clip",
        )
        self._model.fit(sim_wps, y)
        self._trained = True

        # Brier after calibration
        calibrated = [self.calibrate(p) for p in sim_wps]
        brier_after = sum((c - a) ** 2 for c, a in zip(calibrated, y)) / len(y)

        # Reliability diagram bins
        bins = _reliability_bins(sim_wps, calibrated, y)

        return CalibrationMetrics(
            brier_before=round(brier_before, 6),
            brier_after=round(brier_after, 6),
            brier_improvement=round(brier_before - brier_after, 6),
            sample_count=len(sim_wps),
            reliability_bins=bins,
        )

    def calibrate(self, raw_wp: float) -> float:
        """Calibrate a single raw win probability.

        Args:
            raw_wp: Raw sim home win probability (0-1).

        Returns:
            Calibrated probability (0-1).

        Raises:
            RuntimeError: If the calibrator has not been trained.
        """
        if not self._trained or self._model is None:
            raise RuntimeError("Calibrator has not been trained. Call train() first.")

        result = self._model.predict([raw_wp])[0]
        return float(max(0.01, min(0.99, result)))

    def save(self, path: str | Path) -> None:
        """Save the trained model to disk."""
        import joblib

        if not self._trained:
            raise RuntimeError("Cannot save untrained calibrator.")
        joblib.dump(self._model, str(path))
        try:
            from app.analytics.models.core.artifact_signing import sign_artifact
            sign_artifact(path)
        except (RuntimeError, Exception):
            logger.warning("calibrator_signing_skipped", extra={"path": str(path)})
        logger.info("calibrator_saved", extra={"path": str(path)})

    def load(self, path: str | Path) -> None:
        """Load a trained model from disk."""
        import joblib

        self._model = joblib.load(str(path))
        self._trained = True
        logger.info("calibrator_loaded", extra={"path": str(path)})

    def evaluate(
        self,
        sim_wps: list[float],
        actual_outcomes: list[bool],
    ) -> CalibrationMetrics:
        """Evaluate the calibrator on a held-out dataset.

        Does not retrain — uses the existing model to calibrate and
        computes metrics on the provided data.
        """
        if not self._trained:
            raise RuntimeError("Calibrator has not been trained.")

        y = [1.0 if o else 0.0 for o in actual_outcomes]
        brier_before = sum((p - a) ** 2 for p, a in zip(sim_wps, y)) / len(y)

        calibrated = [self.calibrate(p) for p in sim_wps]
        brier_after = sum((c - a) ** 2 for c, a in zip(calibrated, y)) / len(y)

        bins = _reliability_bins(sim_wps, calibrated, y)

        return CalibrationMetrics(
            brier_before=round(brier_before, 6),
            brier_after=round(brier_after, 6),
            brier_improvement=round(brier_before - brier_after, 6),
            sample_count=len(sim_wps),
            reliability_bins=bins,
        )


def _reliability_bins(
    raw_wps: list[float],
    calibrated_wps: list[float],
    actuals: list[float],
    n_bins: int = 10,
) -> list[dict[str, float]]:
    """Build reliability diagram bins for evaluation."""
    bins: list[dict[str, float]] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        indices = [
            j for j, p in enumerate(raw_wps) if lo <= p < hi
        ]
        if not indices:
            continue
        avg_predicted = sum(raw_wps[j] for j in indices) / len(indices)
        avg_calibrated = sum(calibrated_wps[j] for j in indices) / len(indices)
        avg_actual = sum(actuals[j] for j in indices) / len(indices)
        bins.append({
            "bin_start": round(lo, 2),
            "bin_end": round(hi, 2),
            "count": len(indices),
            "avg_predicted": round(avg_predicted, 4),
            "avg_calibrated": round(avg_calibrated, 4),
            "avg_actual": round(avg_actual, 4),
        })
    return bins
