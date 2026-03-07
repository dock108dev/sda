"""MLB plate-appearance ML model wrapper.

Wraps a trained ML model (or uses rule-based defaults) to produce
event probability distributions for plate appearances. Output is
consumed directly by the simulation engine.

Usage::

    model = MLBPlateAppearanceModel()
    probs = model.predict_proba({"zone_swing_pct": 0.72, ...})
    # -> {"strikeout": 0.21, "walk": 0.08, "single": 0.17, ...}
"""

from __future__ import annotations

from typing import Any

from app.analytics.models.core.model_interface import BaseModel

# Default (league-average) event probabilities when no trained model
# is loaded. These match the simulation engine defaults.
_DEFAULT_EVENT_PROBS: dict[str, float] = {
    "strikeout": 0.22,
    "out": 0.46,
    "walk": 0.08,
    "single": 0.15,
    "double": 0.05,
    "triple": 0.01,
    "home_run": 0.03,
}

# Feature keys this model expects.
FEATURE_KEYS = [
    "zone_swing_pct",
    "outside_swing_pct",
    "zone_contact_pct",
    "outside_contact_pct",
    "avg_exit_velocity",
    "hard_hit_pct",
    "barrel_pct",
    "contact_rate",
    "power_index",
]


class MLBPlateAppearanceModel(BaseModel):
    """Predicts plate-appearance outcome probabilities for MLB.

    When a trained scikit-learn model is loaded, it produces event
    probabilities from batter/pitcher features. Without a trained
    model, returns rule-based defaults adjusted by input features.
    """

    model_type = "plate_appearance"
    sport = "mlb"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Predict plate-appearance outcome.

        Args:
            features: Batter/pitcher feature dict.

        Returns:
            Dict with ``event_probabilities`` and ``predicted_event``.
        """
        probs = self.predict_proba(features)
        best_event = max(probs, key=probs.get)  # type: ignore[arg-type]
        return {
            "event_probabilities": probs,
            "predicted_event": best_event,
        }

    def predict_proba(self, features: dict[str, Any]) -> dict[str, float]:
        """Generate event probability distribution.

        If a trained model is loaded, uses it. Otherwise applies
        rule-based adjustments to league-average defaults.

        Args:
            features: Batter/pitcher feature dict.

        Returns:
            Dict mapping event names to probabilities (sums to ~1.0).
        """
        if self._model is not None:
            return self._predict_with_model(features)
        return self._predict_rule_based(features)

    def _predict_with_model(self, features: dict[str, Any]) -> dict[str, float]:
        """Use the loaded ML model for prediction.

        Builds a feature vector from the input dict. If the model
        expects more features than ``FEATURE_KEYS``, uses
        all float values from the dict in sorted key order.
        """
        n_expected = getattr(self._model, "n_features_in_", len(FEATURE_KEYS))

        if n_expected == len(FEATURE_KEYS):
            feature_vector = [features.get(k, 0.0) for k in FEATURE_KEYS]
        else:
            # Use all numeric features in sorted order (from FeatureBuilder)
            feature_vector = [
                float(features.get(k, 0.0))
                for k in sorted(features.keys())
            ]

        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba([feature_vector])[0]
            classes = list(self._model.classes_)
            return {str(c): round(float(p), 4) for c, p in zip(classes, proba)}

        # Fallback: model only has predict()
        return self._predict_rule_based(features)

    def _predict_rule_based(self, features: dict[str, Any]) -> dict[str, float]:
        """Apply rule-based adjustments to defaults based on features."""
        probs = dict(_DEFAULT_EVENT_PROBS)

        contact_rate = features.get("contact_rate", 0.0)
        power_index = features.get("power_index", 0.0)

        if contact_rate > 0:
            # Higher contact rate -> fewer strikeouts, more singles
            k_adj = (0.80 - contact_rate) * 0.15  # positive if low contact
            probs["strikeout"] = max(0.05, probs["strikeout"] + k_adj)
            probs["single"] = max(0.05, probs["single"] - k_adj * 0.5)

        if power_index > 0:
            # Higher power -> more extra-base hits
            pwr_adj = (power_index - 1.0) * 0.02
            probs["home_run"] = max(0.01, probs["home_run"] + pwr_adj)
            probs["double"] = max(0.02, probs["double"] + pwr_adj * 0.5)

        # Normalize so out absorbs remainder
        named = (
            probs["strikeout"] + probs["walk"] + probs["single"]
            + probs["double"] + probs["triple"] + probs["home_run"]
        )
        probs["out"] = max(0.1, 1.0 - named)

        return {k: round(v, 4) for k, v in probs.items()}

    def to_simulation_probs(self, probs: dict[str, float]) -> dict[str, float]:
        """Convert model output to simulation engine probability keys.

        The simulation engine expects ``*_probability`` suffixed keys.
        """
        return {
            "strikeout_probability": probs.get("strikeout", 0.22),
            "walk_probability": probs.get("walk", 0.08),
            "single_probability": probs.get("single", 0.15),
            "double_probability": probs.get("double", 0.05),
            "triple_probability": probs.get("triple", 0.01),
            "home_run_probability": probs.get("home_run", 0.03),
        }
