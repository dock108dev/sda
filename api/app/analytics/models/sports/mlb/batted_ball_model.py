"""MLB batted ball outcome model wrapper.

Predicts the result of a ball put into play using Statcast-style
features. Wraps a trained RandomForestClassifier or uses rule-based
defaults.

Batted ball outcomes:
    out, single, double, triple, home_run

Usage::

    model = MLBBattedBallModel()
    probs = model.predict_proba({
        "exit_velocity": 95.0, "launch_angle": 22.0,
        "batter_barrel_rate": 0.09,
    })
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel

BATTED_BALL_OUTCOMES: list[str] = [
    "out",
    "single",
    "double",
    "triple",
    "home_run",
]

FEATURE_KEYS = [
    "exit_velocity",
    "launch_angle",
    "spray_angle",
    "batter_barrel_rate",
    "batter_hard_hit_rate",
    "pitcher_hard_hit_allowed",
    "park_factor",
    "batter_power_index",
]

# League-average batted ball outcome rates.
_DEFAULT_PROBS: dict[str, float] = {
    "out": 0.72,
    "single": 0.15,
    "double": 0.07,
    "triple": 0.01,
    "home_run": 0.05,
}


def _normalize(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        uniform = 1.0 / len(BATTED_BALL_OUTCOMES)
        return {k: round(uniform, 4) for k in BATTED_BALL_OUTCOMES}
    return {k: round(v / total, 4) for k, v in probs.items()}


class MLBBattedBallModel(BaseModel):
    """Predicts batted ball outcome probabilities."""

    model_type = "batted_ball"
    sport = "mlb"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        probs = self.predict_proba(features)
        best = max(probs, key=probs.get)  # type: ignore[arg-type]
        return {"batted_ball_probabilities": probs, "predicted_outcome": best}

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

        ev = features.get("exit_velocity", 0.0)
        la = features.get("launch_angle", 0.0)
        barrel = features.get("batter_barrel_rate", 0.0)
        power = features.get("batter_power_index", 0.0)
        hard_hit = features.get("batter_hard_hit_rate", 0.0)
        park = features.get("park_factor", 1.0) or 1.0

        # Exit velocity adjustments
        if ev > 0:
            ev_adj = (ev - 88.0) / 100.0  # 88 mph is ~average
            probs["home_run"] += ev_adj * 0.08
            probs["double"] += ev_adj * 0.04
            probs["out"] -= ev_adj * 0.10

        # Launch angle: sweet spot 15-35 degrees
        if la > 0:
            if 15 <= la <= 35:
                probs["home_run"] += 0.03
                probs["double"] += 0.02
                probs["out"] -= 0.04
            elif la > 50:
                probs["out"] += 0.10
                probs["home_run"] -= 0.03

        # Barrel rate
        if barrel > 0:
            b_adj = (barrel - 0.06) * 0.3
            probs["home_run"] += b_adj
            probs["double"] += b_adj * 0.5
            probs["out"] -= b_adj * 1.2

        # Power index fallback
        if power > 0 and ev == 0:
            p_adj = (power - 1.0) * 0.03
            probs["home_run"] += p_adj
            probs["double"] += p_adj * 0.5

        # Hard hit rate
        if hard_hit > 0:
            hh_adj = (hard_hit - 0.35) * 0.1
            probs["single"] += hh_adj
            probs["out"] -= hh_adj

        # Park factor
        if park != 1.0:
            pf_adj = (park - 1.0) * 0.05
            probs["home_run"] += pf_adj

        probs = {k: max(0.005, v) for k, v in probs.items()}
        return _normalize(probs)
