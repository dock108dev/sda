"""NHL game-level model.

Predicts game-level outcomes (win probability, expected goals) from
team-level features. Can use a trained model or fall back to a
rule-based approach using expected goals.

Usage::

    model = NHLGameModel()
    pred = model.predict({"home_xgoals_for": 3.1, "away_xgoals_for": 2.5, ...})
    # -> {"home_win_probability": 0.58, "expected_home_score": 3.0, ...}
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel

FEATURE_KEYS = [
    "home_xgoals_for",
    "home_xgoals_against",
    "home_corsi_pct",
    "away_xgoals_for",
    "away_xgoals_against",
    "away_corsi_pct",
]

_DEFAULT_HOME_WP = 0.55  # NHL home advantage is moderate
_DEFAULT_HOME_GOALS = 3.0
_DEFAULT_AWAY_GOALS = 2.8


class NHLGameModel(BaseModel):
    """Predicts NHL game outcomes from team features.

    With a trained model loaded, uses it to predict win probability
    and expected goals. Without a trained model, uses a simple
    home-advantage baseline with xGoals-based adjustments.
    """

    model_type = "game"
    sport = "nhl"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Predict game outcome.

        Args:
            features: Team-level feature dict.

        Returns:
            Dict with ``home_win_probability``, ``away_win_probability``,
            ``expected_home_score``, ``expected_away_score``.
        """
        if self._model is not None:
            return self._predict_with_model(features)
        return self._predict_rule_based(features)

    def predict_proba(self, features: dict[str, Any]) -> dict[str, float]:
        """Return win probability distribution.

        Args:
            features: Team-level feature dict.

        Returns:
            Dict with ``home_win`` and ``away_win`` probabilities.
        """
        result = self.predict(features)
        wp = result.get("home_win_probability", _DEFAULT_HOME_WP)
        return {"home_win": round(wp, 4), "away_win": round(1.0 - wp, 4)}

    def _predict_with_model(self, features: dict[str, Any]) -> dict[str, Any]:
        """Use the loaded ML model."""
        fv = [features.get(k, 0.0) for k in FEATURE_KEYS]
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba([fv])[0]
            wp = float(proba[1]) if len(proba) > 1 else float(proba[0])
        else:
            wp = _DEFAULT_HOME_WP
        wp = max(0.01, min(0.99, wp))
        return {
            "home_win_probability": round(wp, 4),
            "away_win_probability": round(1.0 - wp, 4),
            "expected_home_score": round(_DEFAULT_HOME_GOALS * (wp / _DEFAULT_HOME_WP), 1),
            "expected_away_score": round(
                _DEFAULT_AWAY_GOALS * ((1.0 - wp) / (1.0 - _DEFAULT_HOME_WP)), 1,
            ),
        }

    def _predict_rule_based(self, features: dict[str, Any]) -> dict[str, Any]:
        """Simple home-advantage baseline with xGoals adjustments."""
        wp = _DEFAULT_HOME_WP

        h_xgf = features.get("home_xgoals_for", 0.0)
        a_xgf = features.get("away_xgoals_for", 0.0)
        h_xga = features.get("home_xgoals_against", 0.0)
        a_xga = features.get("away_xgoals_against", 0.0)

        if h_xgf > 0 and a_xgf > 0:
            off_diff = (h_xgf - a_xgf) * 0.05
            def_diff = (a_xga - h_xga) * 0.05  # higher xGA against opponent is better
            wp += off_diff + def_diff

        wp = max(0.20, min(0.80, wp))

        return {
            "home_win_probability": round(wp, 4),
            "away_win_probability": round(1.0 - wp, 4),
            "expected_home_score": round(_DEFAULT_HOME_GOALS * (wp / _DEFAULT_HOME_WP), 1),
            "expected_away_score": round(
                _DEFAULT_AWAY_GOALS * ((1.0 - wp) / (1.0 - _DEFAULT_HOME_WP)), 1,
            ),
        }
