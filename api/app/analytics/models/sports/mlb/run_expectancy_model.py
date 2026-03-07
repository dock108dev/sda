"""MLB run expectancy model wrapper.

Estimates expected runs remaining given a game state (base runners,
outs, inning, score differential, lineup quality). Wraps a trained
GradientBoostingRegressor or uses a static run expectancy matrix.

Usage::

    model = MLBRunExpectancyModel()
    result = model.predict({"base_state": 5, "outs": 1, "batter_quality": 0.8})
    # -> {"expected_runs": 0.63}
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel

FEATURE_KEYS = [
    "base_state",
    "outs",
    "inning",
    "score_diff",
    "batter_quality",
    "pitcher_quality",
]

# Static run expectancy matrix: (base_state, outs) -> expected runs.
# Base state encoding: 0=empty, 1=1B, 2=2B, 3=1B+2B, 4=3B,
# 5=1B+3B, 6=2B+3B, 7=loaded
_RE_MATRIX: dict[tuple[int, int], float] = {
    (0, 0): 0.481, (0, 1): 0.254, (0, 2): 0.098,
    (1, 0): 0.862, (1, 1): 0.509, (1, 2): 0.214,
    (2, 0): 1.100, (2, 1): 0.664, (2, 2): 0.319,
    (3, 0): 1.437, (3, 1): 0.884, (3, 2): 0.429,
    (4, 0): 1.350, (4, 1): 0.950, (4, 2): 0.353,
    (5, 0): 1.784, (5, 1): 1.130, (5, 2): 0.478,
    (6, 0): 1.964, (6, 1): 1.376, (6, 2): 0.580,
    (7, 0): 2.282, (7, 1): 1.520, (7, 2): 0.752,
}


def encode_base_state(first: bool, second: bool, third: bool) -> int:
    """Encode base runner state as a single integer (0-7)."""
    return int(first) + int(second) * 2 + int(third) * 4


class MLBRunExpectancyModel(BaseModel):
    """Estimates expected runs from a game state."""

    model_type = "run_expectancy"
    sport = "mlb"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        expected = self.predict_value(features)
        return {"expected_runs": round(expected, 3)}

    def predict_proba(self, features: dict[str, Any]) -> dict[str, float]:
        expected = self.predict_value(features)
        return {"expected_runs": round(expected, 3)}

    def predict_value(self, features: dict[str, Any]) -> float:
        """Predict expected runs as a float."""
        if self._model is not None:
            return self._predict_with_model(features)
        return self._predict_rule_based(features)

    def _predict_with_model(self, features: dict[str, Any]) -> float:
        n_expected = getattr(self._model, "n_features_in_", len(FEATURE_KEYS))
        if n_expected == len(FEATURE_KEYS):
            vec = [features.get(k, 0.0) for k in FEATURE_KEYS]
        else:
            vec = [float(features.get(k, 0.0)) for k in sorted(features.keys())]
        pred = self._model.predict([vec])[0]
        return max(0.0, float(pred))

    def _predict_rule_based(self, features: dict[str, Any]) -> float:
        base_state = int(features.get("base_state", 0))
        outs = int(features.get("outs", 0))
        outs = min(max(outs, 0), 2)
        base_state = min(max(base_state, 0), 7)

        base_re = _RE_MATRIX.get((base_state, outs), 0.3)

        # Adjust for batter/pitcher quality
        batter_q = features.get("batter_quality", 0.0)
        pitcher_q = features.get("pitcher_quality", 0.0)
        if batter_q > 0:
            base_re *= 0.8 + batter_q * 0.4  # 1.0 quality = 1.2x
        if pitcher_q > 0:
            base_re *= 1.2 - pitcher_q * 0.4  # 1.0 quality = 0.8x

        return max(0.0, base_re)
