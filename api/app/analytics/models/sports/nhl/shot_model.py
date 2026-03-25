"""NHL shot outcome model.

Predicts shot-level outcomes (goal, save, blocked, missed) from
shot and game-state features. Can use a trained model or fall back
to a rule-based approach that adjusts league-average baselines by
shooting percentage.

Usage::

    model = NHLShotModel()
    pred = model.predict({"shooting_pct": 0.11, "save_pct": 0.90, ...})
    # -> {"event_probabilities": {...}, "predicted_event": "save"}
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel
from app.analytics.sports.nhl.constants import DEFAULT_EVENT_PROBS, SHOT_EVENTS

FEATURE_KEYS = [
    "shooting_pct",
    "save_pct",
    "corsi_pct",
    "high_danger_rate",
    "high_danger_goal_pct",
    "shots_per_game",
    "xgoals_for",
    "xgoals_against",
]


class NHLShotModel(BaseModel):
    """Predicts NHL shot outcomes from shot and game-state features.

    With a trained model loaded, uses it to predict event probabilities.
    Without a trained model, uses a rule-based approach that adjusts
    league-average baselines by shooting percentage and danger level.
    """

    model_type = "shot"
    sport = "nhl"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Predict the most likely shot outcome.

        Args:
            features: Shot-level feature dict.

        Returns:
            Dict with ``event_probabilities`` and ``predicted_event``.
        """
        probs = self.predict_proba(features)
        best = max(probs, key=probs.get)
        return {"event_probabilities": probs, "predicted_event": best}

    def predict_proba(self, features: dict[str, Any]) -> dict[str, float]:
        """Return probability distribution over shot events.

        Args:
            features: Shot-level feature dict.

        Returns:
            Dict mapping event labels to probabilities.
        """
        if self._model is not None:
            return self._predict_with_model(features)
        return self._predict_rule_based(features)

    def _predict_rule_based(self, features: dict[str, Any]) -> dict[str, float]:
        """Adjust league-average baselines using shooting features."""
        probs = dict(DEFAULT_EVENT_PROBS)

        shooting_pct = features.get("shooting_pct", 0.0)
        high_danger_rate = features.get("high_danger_rate", 0.0)

        if shooting_pct > 0:
            goal_adj = (shooting_pct - 0.09) * 0.5
            probs["goal"] = max(0.02, probs["goal"] + goal_adj)

        if high_danger_rate > 0:
            hd_adj = (high_danger_rate - 0.25) * 0.1
            probs["goal"] = max(0.02, probs["goal"] + hd_adj)

        # Normalize: save absorbs remainder
        named = sum(v for k, v in probs.items() if k != "save")
        probs["save"] = max(0.30, 1.0 - named)

        return {k: round(v, 4) for k, v in probs.items()}

    def _predict_with_model(self, features: dict[str, Any]) -> dict[str, float]:
        """Use the loaded ML model to predict shot outcome probabilities."""
        fv = [features.get(k, 0.0) for k in FEATURE_KEYS]
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba([fv])[0]
            classes = list(self._model.classes_)
            return {str(c): round(float(p), 4) for c, p in zip(classes, proba)}
        return self._predict_rule_based(features)
