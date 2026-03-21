"""Tests for calibration dataset builder and SimCalibrator.

Phase 2 of the fair-odds pipeline.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.analytics.calibration.calibrator import SimCalibrator
from app.analytics.calibration.dataset import (
    CalibrationRow,
    _devig_closing_lines,
)


# ---------------------------------------------------------------------------
# SimCalibrator tests
# ---------------------------------------------------------------------------


class TestSimCalibrator:
    """Test the isotonic regression calibrator."""

    def _make_dataset(self, n: int = 100, bias: float = 0.0):
        """Generate synthetic sim WPs and outcomes.

        bias > 0 means the sim overestimates home win probability.
        """
        import random

        rng = random.Random(42)
        sim_wps: list[float] = []
        actuals: list[bool] = []
        for _ in range(n):
            true_p = rng.uniform(0.3, 0.7)
            sim_p = min(0.99, max(0.01, true_p + bias))
            outcome = rng.random() < true_p
            sim_wps.append(sim_p)
            actuals.append(outcome)
        return sim_wps, actuals

    def test_train_returns_metrics(self):
        sim_wps, actuals = self._make_dataset()
        cal = SimCalibrator()
        metrics = cal.train(sim_wps, actuals)

        assert metrics.sample_count == 100
        assert 0.0 <= metrics.brier_before <= 1.0
        assert 0.0 <= metrics.brier_after <= 1.0
        assert cal.is_trained

    def test_calibrate_requires_training(self):
        cal = SimCalibrator()
        with pytest.raises(RuntimeError, match="not been trained"):
            cal.calibrate(0.55)

    def test_calibrate_returns_bounded_value(self):
        sim_wps, actuals = self._make_dataset()
        cal = SimCalibrator()
        cal.train(sim_wps, actuals)

        result = cal.calibrate(0.55)
        assert 0.01 <= result <= 0.99

    def test_calibrate_preserves_ordering(self):
        """Isotonic regression is monotonic — higher input → higher output."""
        sim_wps, actuals = self._make_dataset(n=200)
        cal = SimCalibrator()
        cal.train(sim_wps, actuals)

        low = cal.calibrate(0.35)
        mid = cal.calibrate(0.50)
        high = cal.calibrate(0.65)

        assert low <= mid <= high

    def test_calibrate_edge_cases(self):
        sim_wps, actuals = self._make_dataset()
        cal = SimCalibrator()
        cal.train(sim_wps, actuals)

        # Extreme values should be clamped
        assert cal.calibrate(0.01) >= 0.01
        assert cal.calibrate(0.99) <= 0.99
        # 50/50 should remain near 50%
        mid = cal.calibrate(0.50)
        assert 0.30 <= mid <= 0.70

    def test_biased_sim_gets_corrected(self):
        """A sim that systematically overestimates should be pulled down."""
        sim_wps, actuals = self._make_dataset(n=200, bias=0.08)
        cal = SimCalibrator()
        metrics = cal.train(sim_wps, actuals)

        # Calibration should improve Brier score when there's bias
        assert metrics.brier_after <= metrics.brier_before
        assert metrics.brier_improvement >= 0

    def test_train_too_few_samples_raises(self):
        cal = SimCalibrator()
        with pytest.raises(ValueError, match="at least 10"):
            cal.train([0.5] * 5, [True] * 5)

    def test_save_load_roundtrip(self):
        sim_wps, actuals = self._make_dataset()
        cal = SimCalibrator()
        cal.train(sim_wps, actuals)
        original = cal.calibrate(0.55)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_cal.joblib"
            cal.save(path)

            cal2 = SimCalibrator()
            cal2.load(path)
            loaded = cal2.calibrate(0.55)

        assert abs(original - loaded) < 1e-9

    def test_evaluate_without_training_raises(self):
        cal = SimCalibrator()
        with pytest.raises(RuntimeError, match="not been trained"):
            cal.evaluate([0.5], [True])

    def test_evaluate_returns_metrics(self):
        sim_wps, actuals = self._make_dataset(n=200)
        # Split into train/test
        train_wps, test_wps = sim_wps[:150], sim_wps[150:]
        train_act, test_act = actuals[:150], actuals[150:]

        cal = SimCalibrator()
        cal.train(train_wps, train_act)
        metrics = cal.evaluate(test_wps, test_act)

        assert metrics.sample_count == 50
        assert 0.0 <= metrics.brier_before <= 1.0
        assert 0.0 <= metrics.brier_after <= 1.0

    def test_reliability_bins_populated(self):
        sim_wps, actuals = self._make_dataset(n=200)
        cal = SimCalibrator()
        metrics = cal.train(sim_wps, actuals)

        assert len(metrics.reliability_bins) > 0
        for b in metrics.reliability_bins:
            assert "bin_start" in b
            assert "count" in b
            assert b["count"] > 0


# ---------------------------------------------------------------------------
# Dataset builder helper tests
# ---------------------------------------------------------------------------


class TestDevigClosingLines:
    """Test the _devig_closing_lines helper."""

    def _mock_remove_vig(self, implied_probs):
        """Simple additive normalization for testing."""
        total = sum(implied_probs)
        return [p / total for p in implied_probs]

    def _mock_american_to_implied(self, price):
        if price >= 100:
            return 100.0 / (price + 100.0)
        elif price <= -100:
            return abs(price) / (abs(price) + 100.0)
        raise ValueError(f"Invalid price: {price}")

    def test_two_lines_matched_by_name(self):
        lines = [("New York Yankees", -150.0), ("Boston Red Sox", +130.0)]
        result = _devig_closing_lines(
            lines, "New York Yankees", "Boston Red Sox",
            self._mock_remove_vig, self._mock_american_to_implied,
        )
        assert result is not None
        assert 0.5 < result < 0.7  # Yankees favored

    def test_insufficient_lines_returns_none(self):
        lines = [("Yankees", -150.0)]
        result = _devig_closing_lines(
            lines, "Yankees", "Red Sox",
            self._mock_remove_vig, self._mock_american_to_implied,
        )
        assert result is None

    def test_empty_lines_returns_none(self):
        result = _devig_closing_lines(
            [], "Yankees", "Red Sox",
            self._mock_remove_vig, self._mock_american_to_implied,
        )
        assert result is None

    def test_unmatched_names_uses_fallback_order(self):
        """If team names don't match selections, fall back to positional."""
        lines = [("team:some_slug", -120.0), ("team:other_slug", +100.0)]
        result = _devig_closing_lines(
            lines, "Yankees", "Red Sox",
            self._mock_remove_vig, self._mock_american_to_implied,
        )
        # Should still return a value via fallback
        assert result is not None
        assert 0.0 < result < 1.0

    def test_symmetric_odds_return_near_fifty(self):
        """Both sides at -110 should devig to ~50%."""
        lines = [("Yankees", -110.0), ("Red Sox", -110.0)]
        result = _devig_closing_lines(
            lines, "Yankees", "Red Sox",
            self._mock_remove_vig, self._mock_american_to_implied,
        )
        assert result is not None
        assert abs(result - 0.5) < 0.02
