"""NBA possession outcome model."""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel
from app.analytics.sports.nba.constants import DEFAULT_EVENT_PROBS

FEATURE_KEYS = [
    "off_rating",
    "def_rating",
    "pace",
    "efg_pct",
    "ts_pct",
    "tov_pct",
    "orb_pct",
    "ft_rate",
    "fg3_pct",
]


class NBAPossessionModel(BaseModel):
    """Predicts NBA possession outcomes from team/lineup features.

    With a trained model loaded, uses it to predict event probabilities.
    Without a trained model, uses a rule-based approach that adjusts
    league-average baselines by shooting efficiency and turnover rate.
    """

    model_type = "possession"
    sport = "nba"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Predict the most likely possession outcome.

        Args:
            features: Possession-level feature dict.

        Returns:
            Dict with ``event_probabilities`` and ``predicted_event``.
        """
        probs = self.predict_proba(features)
        best = max(probs, key=probs.get)
        return {"event_probabilities": probs, "predicted_event": best}

    def predict_proba(self, features: dict[str, Any]) -> dict[str, float]:
        """Return probability distribution over possession events.

        Args:
            features: Possession-level feature dict.

        Returns:
            Dict mapping event labels to probabilities.
        """
        if self._model is not None:
            return self._predict_with_model(features)
        return self._predict_rule_based(features)

    def _predict_rule_based(self, features: dict[str, Any]) -> dict[str, float]:
        """Adjust league-average baselines using efficiency features."""
        probs = dict(DEFAULT_EVENT_PROBS)

        efg = features.get("efg_pct", 0.0)
        tov = features.get("tov_pct", 0.0)

        if efg > 0:
            adj = (efg - 0.54) * 0.2
            probs["two_pt_make"] = max(0.10, probs["two_pt_make"] + adj)
            probs["three_pt_make"] = max(0.05, probs["three_pt_make"] + adj * 0.5)

        if tov > 0:
            tov_adj = (tov - 0.13) * 0.3
            probs["turnover"] = max(0.05, probs["turnover"] + tov_adj)

        # Normalize: two_pt_miss absorbs remainder
        named = sum(v for k, v in probs.items() if k != "two_pt_miss")
        probs["two_pt_miss"] = max(0.05, 1.0 - named)

        return {k: round(v, 4) for k, v in probs.items()}

    def _predict_with_model(self, features: dict[str, Any]) -> dict[str, float]:
        """Use the loaded ML model to predict event probabilities."""
        fv = [features.get(k, 0.0) for k in FEATURE_KEYS]
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba([fv])[0]
            classes = list(self._model.classes_)
            return {str(c): round(float(p), 4) for c, p in zip(classes, proba)}
        return self._predict_rule_based(features)
