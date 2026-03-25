"""NBA game-level model.

Predicts game-level outcomes (win probability, expected scores) from
team-level features. Can use a trained model or fall back to a
rule-based approach using offensive and defensive ratings.

Usage::

    model = NBAGameModel()
    pred = model.predict({"home_off_rating": 116.0, "away_off_rating": 112.0, ...})
    # -> {"home_win_probability": 0.63, "expected_home_score": 119.3, ...}
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel

FEATURE_KEYS = [
    "home_off_rating",
    "home_def_rating",
    "home_pace",
    "away_off_rating",
    "away_def_rating",
    "away_pace",
]

_DEFAULT_HOME_WP = 0.60  # NBA home advantage is significant
_DEFAULT_HOME_PTS = 114.0
_DEFAULT_AWAY_PTS = 110.0


class NBAGameModel(BaseModel):
    """Predicts NBA game outcomes from team features.

    With a trained model loaded, uses it to predict win probability
    and expected scores. Without a trained model, uses a simple
    home-advantage baseline with offensive/defensive rating adjustments.
    """

    model_type = "game"
    sport = "nba"

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
            "expected_home_score": round(_DEFAULT_HOME_PTS * (wp / _DEFAULT_HOME_WP), 1),
            "expected_away_score": round(
                _DEFAULT_AWAY_PTS * ((1.0 - wp) / (1.0 - _DEFAULT_HOME_WP)), 1,
            ),
        }

    def _predict_rule_based(self, features: dict[str, Any]) -> dict[str, Any]:
        """Simple home-advantage baseline with rating adjustments."""
        wp = _DEFAULT_HOME_WP

        h_off = features.get("home_off_rating", 0.0)
        a_off = features.get("away_off_rating", 0.0)
        h_def = features.get("home_def_rating", 0.0)
        a_def = features.get("away_def_rating", 0.0)

        if h_off > 0 and a_off > 0:
            off_diff = (h_off - a_off) * 0.003
            def_diff = (a_def - h_def) * 0.003  # lower def rating is better
            wp += off_diff + def_diff

        wp = max(0.20, min(0.80, wp))

        return {
            "home_win_probability": round(wp, 4),
            "away_win_probability": round(1.0 - wp, 4),
            "expected_home_score": round(_DEFAULT_HOME_PTS * (wp / _DEFAULT_HOME_WP), 1),
            "expected_away_score": round(
                _DEFAULT_AWAY_PTS * ((1.0 - wp) / (1.0 - _DEFAULT_HOME_WP)), 1,
            ),
        }
