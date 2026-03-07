"""MLB game-level ML model wrapper.

Predicts game-level outcomes (win probability, expected runs) from
team-level features. Can use a trained model or fall back to a
rule-based approach that delegates to the simulation engine.

Usage::

    model = MLBGameModel()
    pred = model.predict({"home_team": "LAD", "away_team": "TOR", ...})
    # -> {"home_win_probability": 0.61, "expected_home_score": 4.8, ...}
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel

# Feature keys for the game model.
FEATURE_KEYS = [
    "home_contact_rate",
    "home_power_index",
    "home_expected_slug",
    "away_contact_rate",
    "away_power_index",
    "away_expected_slug",
]

# Default league-average home win probability.
_DEFAULT_HOME_WP = 0.54
_DEFAULT_HOME_RUNS = 4.5
_DEFAULT_AWAY_RUNS = 4.2


class MLBGameModel(BaseModel):
    """Predicts MLB game outcomes from team features.

    With a trained model loaded, uses it to predict win probability
    and expected scores. Without a trained model, uses a simple
    home-advantage baseline with feature adjustments.
    """

    model_type = "game"
    sport = "mlb"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Predict game outcome.

        Args:
            features: Team-level feature dict.

        Returns:
            Dict with ``home_win_probability``, ``expected_home_score``,
            ``expected_away_score``.
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
        home_wp = result.get("home_win_probability", _DEFAULT_HOME_WP)
        return {
            "home_win": round(home_wp, 4),
            "away_win": round(1.0 - home_wp, 4),
        }

    def _predict_with_model(self, features: dict[str, Any]) -> dict[str, Any]:
        """Use the loaded ML model.

        Builds a feature vector from the input dict. If the model
        expects more features than ``FEATURE_KEYS``, uses
        all float values from the dict in sorted key order.
        """
        n_expected = getattr(self._model, "n_features_in_", len(FEATURE_KEYS))

        if n_expected == len(FEATURE_KEYS):
            feature_vector = [features.get(k, 0.0) for k in FEATURE_KEYS]
        else:
            feature_vector = [
                float(features.get(k, 0.0))
                for k in sorted(features.keys())
            ]

        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba([feature_vector])[0]
            home_wp = float(proba[1]) if len(proba) > 1 else float(proba[0])
        elif hasattr(self._model, "predict"):
            pred = self._model.predict([feature_vector])[0]
            home_wp = float(pred)
        else:
            home_wp = _DEFAULT_HOME_WP

        home_wp = max(0.01, min(0.99, home_wp))

        return {
            "home_win_probability": round(home_wp, 4),
            "away_win_probability": round(1.0 - home_wp, 4),
            "expected_home_score": round(_DEFAULT_HOME_RUNS * (home_wp / _DEFAULT_HOME_WP), 1),
            "expected_away_score": round(_DEFAULT_AWAY_RUNS * ((1.0 - home_wp) / (1.0 - _DEFAULT_HOME_WP)), 1),
        }

    def _predict_rule_based(self, features: dict[str, Any]) -> dict[str, Any]:
        """Simple home-advantage baseline with feature adjustments."""
        home_wp = _DEFAULT_HOME_WP

        home_power = features.get("home_power_index", 0.0)
        away_power = features.get("away_power_index", 0.0)
        home_contact = features.get("home_contact_rate", 0.0)
        away_contact = features.get("away_contact_rate", 0.0)

        # Adjust based on power differential
        if home_power > 0 and away_power > 0:
            power_diff = (home_power - away_power) * 0.05
            home_wp += power_diff

        # Adjust based on contact differential
        if home_contact > 0 and away_contact > 0:
            contact_diff = (home_contact - away_contact) * 0.03
            home_wp += contact_diff

        home_wp = max(0.20, min(0.80, home_wp))

        exp_home = round(_DEFAULT_HOME_RUNS * (home_wp / _DEFAULT_HOME_WP), 1)
        exp_away = round(_DEFAULT_AWAY_RUNS * ((1.0 - home_wp) / (1.0 - _DEFAULT_HOME_WP)), 1)

        return {
            "home_win_probability": round(home_wp, 4),
            "away_win_probability": round(1.0 - home_wp, 4),
            "expected_home_score": exp_home,
            "expected_away_score": exp_away,
        }
