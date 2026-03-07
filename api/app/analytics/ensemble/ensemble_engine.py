"""Ensemble engine for combining multiple probability sources.

Collects predictions from multiple providers, applies configurable
weights, and normalizes the result. Designed to be lightweight —
called thousands of times per simulation.

Usage::

    engine = EnsembleEngine()
    result = engine.combine(
        predictions={"rule_based": rule_probs, "ml": ml_probs},
        weights={"rule_based": 0.4, "ml": 0.6},
    )
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EnsembleEngine:
    """Combines predictions from multiple probability providers.

    Stateless and reusable. Each call to ``combine`` performs one
    weighted average and normalization pass.
    """

    def combine(
        self,
        predictions: dict[str, dict[str, float]],
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Combine multiple probability distributions.

        Args:
            predictions: Mapping of provider name to probability dict.
            weights: Mapping of provider name to weight. Weights are
                normalized internally so they don't need to sum to 1.

        Returns:
            Normalized combined probability dict.
        """
        if not predictions:
            return {}

        # Normalize weights
        total_weight = sum(weights.get(name, 0.0) for name in predictions)
        if total_weight <= 0:
            total_weight = len(predictions)
            norm_weights = {name: 1.0 / total_weight for name in predictions}
        else:
            norm_weights = {
                name: weights.get(name, 0.0) / total_weight
                for name in predictions
            }

        # Collect all event keys
        all_events: set[str] = set()
        for probs in predictions.values():
            all_events.update(probs.keys())

        # Weighted sum
        combined: dict[str, float] = {}
        for event in all_events:
            val = 0.0
            for name, probs in predictions.items():
                val += probs.get(event, 0.0) * norm_weights.get(name, 0.0)
            combined[event] = val

        return _normalize(combined)

    def combine_from_config(
        self,
        predictions: dict[str, dict[str, float]],
        config: Any,
    ) -> dict[str, float]:
        """Combine using an EnsembleConfig object.

        Args:
            predictions: Provider name to probability dict.
            config: ``EnsembleConfig`` instance.

        Returns:
            Normalized combined probability dict.
        """
        weights = {p.name: p.weight for p in config.providers}
        return self.combine(predictions, weights)


def _normalize(probs: dict[str, float]) -> dict[str, float]:
    """Normalize probabilities to sum to 1.0."""
    total = sum(probs.values())
    if total <= 0:
        if not probs:
            return {}
        uniform = 1.0 / len(probs)
        return {k: round(uniform, 6) for k in probs}
    return {k: round(v / total, 6) for k, v in probs.items()}
