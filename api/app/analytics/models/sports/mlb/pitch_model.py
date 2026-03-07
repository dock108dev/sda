"""MLB pitch outcome model wrapper.

Predicts the result of each individual pitch using batter/pitcher
profiles and count state. Wraps a trained GradientBoostingClassifier
or uses rule-based defaults.

Pitch outcomes:
    ball, called_strike, swinging_strike, foul, in_play

Usage::

    model = MLBPitchOutcomeModel()
    probs = model.predict_proba({
        "pitcher_k_rate": 0.24, "batter_contact_rate": 0.80,
        "count_balls": 1, "count_strikes": 1,
    })
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel

PITCH_OUTCOMES: list[str] = [
    "ball",
    "called_strike",
    "swinging_strike",
    "foul",
    "in_play",
]

FEATURE_KEYS = [
    "pitcher_k_rate",
    "pitcher_walk_rate",
    "pitcher_zone_rate",
    "pitcher_contact_allowed",
    "batter_contact_rate",
    "batter_swing_rate",
    "batter_zone_swing_rate",
    "batter_chase_rate",
    "count_balls",
    "count_strikes",
]

# League-average pitch outcome rates.
_DEFAULT_PROBS: dict[str, float] = {
    "ball": 0.35,
    "called_strike": 0.17,
    "swinging_strike": 0.11,
    "foul": 0.18,
    "in_play": 0.19,
}


def _normalize(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        uniform = 1.0 / len(PITCH_OUTCOMES)
        return {k: round(uniform, 4) for k in PITCH_OUTCOMES}
    return {k: round(v / total, 4) for k, v in probs.items()}


class MLBPitchOutcomeModel(BaseModel):
    """Predicts individual pitch outcome probabilities."""

    model_type = "pitch"
    sport = "mlb"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        probs = self.predict_proba(features)
        best = max(probs, key=probs.get)  # type: ignore[arg-type]
        return {"pitch_probabilities": probs, "predicted_outcome": best}

    def predict_proba(self, features: dict[str, Any]) -> dict[str, float]:
        if self._model is not None:
            return self._predict_with_model(features)
        return self._predict_rule_based(features)

    def _predict_with_model(self, features: dict[str, Any]) -> dict[str, float]:
        n_expected = getattr(self._model, "n_features_in_", len(FEATURE_KEYS))
        if n_expected == len(FEATURE_KEYS):
            vec = [features.get(k, 0.0) for k in FEATURE_KEYS]
        else:
            vec = [float(features.get(k, 0.0)) for k in sorted(features.keys())]

        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba([vec])[0]
            classes = list(self._model.classes_)
            return _normalize({str(c): float(p) for c, p in zip(classes, proba)})
        return self._predict_rule_based(features)

    def _predict_rule_based(self, features: dict[str, Any]) -> dict[str, float]:
        probs = dict(_DEFAULT_PROBS)
        balls = features.get("count_balls", 0)
        strikes = features.get("count_strikes", 0)

        # Count adjustments: deeper counts shift probabilities
        if balls >= 3:
            probs["ball"] += 0.05
            probs["in_play"] += 0.03
            probs["called_strike"] -= 0.04
            probs["swinging_strike"] -= 0.02
        elif strikes >= 2:
            probs["foul"] += 0.06
            probs["swinging_strike"] += 0.03
            probs["ball"] -= 0.04
            probs["in_play"] += 0.02

        # Batter swing tendencies
        swing_rate = features.get("batter_swing_rate", 0.0)
        if swing_rate > 0:
            adj = (swing_rate - 0.50) * 0.08
            probs["swinging_strike"] += adj * 0.5
            probs["foul"] += adj * 0.3
            probs["called_strike"] -= adj * 0.4
            probs["ball"] -= adj * 0.3

        # Pitcher strikeout tendency
        k_rate = features.get("pitcher_k_rate", 0.0)
        if k_rate > 0:
            k_adj = (k_rate - 0.22) * 0.1
            probs["swinging_strike"] += k_adj
            probs["in_play"] -= k_adj * 0.5

        # Clamp negatives
        probs = {k: max(0.01, v) for k, v in probs.items()}
        return _normalize(probs)
