"""Probability provider abstraction.

Defines a common interface for probability sources used by the
simulation engine. All providers return normalized event probability
dicts in a standard format.

Supported implementations:
    - ``RuleBasedProvider`` — uses PA model rule-based path / static defaults
    - ``MLProvider`` — uses ModelInferenceEngine
    - ``EnsembleProvider`` — combines multiple providers

Usage::

    provider = RuleBasedProvider()
    probs = provider.get_event_probabilities("mlb", context)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

from app.analytics.sports.mlb.constants import (
    DEFAULT_EVENT_PROBS as _MLB_DEFAULTS,
)
from app.analytics.sports.mlb.constants import (
    PA_EVENTS as MLB_PA_EVENTS,
)


# Maximum deviation from league-average baseline.  A value of 0.5 means
# the model can shift each event probability by at most 50% of its
# baseline value.  For example, strikeout baseline is 0.22, so the model
# output is clamped to 0.11–0.33.  This prevents poorly-calibrated
# models from producing absurd simulations (e.g., 60% hit rate) while
# still allowing meaningful team differentiation.
_MAX_BASELINE_DEVIATION = 0.25


def normalize_probabilities(
    probs: dict[str, float],
    valid_events: list[str] | None = None,
) -> dict[str, float]:
    """Normalize a probability dict so values sum to 1.0.

    - Negative values are clamped to 0.
    - Missing events from ``valid_events`` default to 0.
    - If all values are 0, returns uniform distribution.

    Args:
        probs: Raw probability dict.
        valid_events: Expected event keys. If ``None``, uses the
            keys present in ``probs``.

    Returns:
        Normalized probability dict.

    Raises:
        ValueError: If no valid events provided and probs is empty.
    """
    events = valid_events or list(probs.keys())
    if not events:
        raise ValueError("Cannot normalize empty probability set")

    clamped = {e: max(0.0, float(probs.get(e, 0.0))) for e in events}
    total = sum(clamped.values())

    if total <= 0:
        uniform = 1.0 / len(events)
        return {e: round(uniform, 6) for e in events}

    return {e: round(v / total, 6) for e, v in clamped.items()}


def anchor_to_baseline(
    probs: dict[str, float],
    baseline: dict[str, float] | None = None,
    max_deviation: float = _MAX_BASELINE_DEVIATION,
) -> dict[str, float]:
    """Clamp ML probabilities so they stay within a band around the baseline.

    For each event, the output is clamped to:
        ``baseline * (1 - max_deviation)`` ≤ output ≤ ``baseline * (1 + max_deviation)``

    Then renormalized to sum to 1.0.  This prevents poorly-calibrated
    models from producing absurd simulations while preserving the
    direction and relative magnitude of the model's predictions.

    Args:
        probs: Normalized probability dict from the model.
        baseline: League-average defaults. If None, uses MLB defaults.
        max_deviation: Maximum fractional deviation from baseline (0-1).

    Returns:
        Anchored and renormalized probability dict.
    """
    if baseline is None:
        baseline = _MLB_DEFAULTS

    anchored: dict[str, float] = {}
    for event, model_prob in probs.items():
        base = baseline.get(event, 0.0)
        if base <= 0:
            anchored[event] = model_prob
            continue
        lo = base * (1.0 - max_deviation)
        hi = base * (1.0 + max_deviation)
        anchored[event] = max(lo, min(hi, model_prob))

    # Renormalize after clamping
    total = sum(anchored.values())
    if total <= 0:
        return probs
    return {e: round(v / total, 6) for e, v in anchored.items()}


def validate_probabilities(
    probs: dict[str, float],
    valid_events: list[str] | None = None,
    tolerance: float = 0.01,
) -> list[str]:
    """Validate a probability dict and return a list of issues.

    Returns an empty list if valid.
    """
    issues: list[str] = []

    if not probs:
        issues.append("empty_probabilities")
        return issues

    for key, val in probs.items():
        if not isinstance(val, (int, float)):
            issues.append(f"non_numeric:{key}")
        elif val < 0:
            issues.append(f"negative:{key}")

    total = sum(float(v) for v in probs.values() if isinstance(v, (int, float)))
    if abs(total - 1.0) > tolerance:
        issues.append(f"sum_not_one:{total:.4f}")

    if valid_events:
        for event in valid_events:
            if event not in probs:
                issues.append(f"missing_event:{event}")

    return issues


class ProbabilityProvider(ABC):
    """Base abstraction for event probability sources."""

    @abstractmethod
    def get_event_probabilities(
        self,
        sport: str,
        context: dict[str, Any],
    ) -> dict[str, float]:
        """Generate normalized event probabilities.

        Args:
            sport: Sport code (e.g., ``"mlb"``).
            context: Profiles and game context for probability
                generation. Keys are sport-specific.

        Returns:
            Normalized dict mapping event names to probabilities
            that sum to 1.0.
        """

    @property
    def provider_name(self) -> str:
        """Human-readable provider name for metadata."""
        return self.__class__.__name__


class RuleBasedProvider(ProbabilityProvider):
    """Generate probabilities from the PA model's rule-based path.

    Uses the MLBPlateAppearanceModel rule-based logic or static
    league-average defaults when no profiles are available.
    """

    @property
    def provider_name(self) -> str:
        return "rule_based"

    def get_event_probabilities(
        self,
        sport: str,
        context: dict[str, Any],
    ) -> dict[str, float]:
        """Generate rule-based event probabilities.

        Uses the PA model wrapper's rule-based path for MLB.
        Falls back to league-average defaults.
        """
        sport = sport.lower()

        if sport == "mlb":
            return self._mlb_probabilities(context)

        return normalize_probabilities(_MLB_DEFAULTS, MLB_PA_EVENTS)

    def _mlb_probabilities(self, context: dict[str, Any]) -> dict[str, float]:
        """Generate MLB probabilities from profiles or defaults."""
        from app.analytics.models.sports.mlb.pa_model import (
            MLBPlateAppearanceModel,
        )

        model = MLBPlateAppearanceModel()
        batter = context.get("batter_profile", {})
        pitcher = context.get("pitcher_profile", {})

        features: dict[str, Any] = {}
        if isinstance(batter, dict):
            features.update(batter.get("metrics", batter))
        if isinstance(pitcher, dict):
            for k, v in pitcher.get("metrics", pitcher).items():
                features.setdefault(k, v)

        probs = model._predict_rule_based(features)
        return normalize_probabilities(probs, MLB_PA_EVENTS)


class MLProvider(ProbabilityProvider):
    """Generate probabilities from trained ML models.

    Uses the ModelInferenceEngine from Prompt 15.
    """

    def __init__(self, model_type: str = "plate_appearance") -> None:
        self._model_type = model_type
        self._engine: Any = None

    @property
    def provider_name(self) -> str:
        return "ml"

    def _get_engine(self) -> Any:
        if self._engine is None:
            from app.analytics.inference.model_inference_engine import (
                ModelInferenceEngine,
            )
            self._engine = ModelInferenceEngine()
        return self._engine

    def get_event_probabilities(
        self,
        sport: str,
        context: dict[str, Any],
    ) -> dict[str, float]:
        """Generate ML-based event probabilities.

        Builds features from profiles and runs inference through
        the active model (or a specific model if ``_model_id`` is
        present in the context).
        """
        engine = self._get_engine()
        model_id = context.get("_model_id")
        probs = engine.predict_proba(
            sport=sport,
            model_type=self._model_type,
            profiles=context,
            model_id=model_id,
        )

        if not probs:
            raise RuntimeError(
                f"ML inference returned empty probabilities "
                f"(sport={sport}, model_type={self._model_type})"
            )

        valid_events = MLB_PA_EVENTS if sport.lower() == "mlb" else None
        normalized = normalize_probabilities(probs, valid_events)

        # Anchor to baseline so miscalibrated models can't produce
        # absurd simulations (e.g., 60% hit rate → 30 runs/game).
        if sport.lower() == "mlb":
            normalized = anchor_to_baseline(normalized)

        return normalized


class EnsembleProvider(ProbabilityProvider):
    """Combine predictions from multiple providers using weighted average.

    Uses the EnsembleEngine and EnsembleConfig to collect predictions
    from rule-based and ML providers and produce a single blended
    probability distribution.
    """

    def __init__(self, model_type: str = "plate_appearance") -> None:
        self._model_type = model_type
        self._rule = RuleBasedProvider()
        self._ml = MLProvider(model_type=model_type)
        # After each call to get_event_probabilities, this attribute
        # holds the list of provider names that succeeded.
        self.last_providers_used: list[str] = []

    @property
    def provider_name(self) -> str:
        return "ensemble"

    def get_event_probabilities(
        self,
        sport: str,
        context: dict[str, Any],
    ) -> dict[str, float]:
        """Generate ensemble-blended event probabilities.

        Collects from rule-based and ML providers, combines with
        configured weights, and normalizes.

        After this method returns, ``self.last_providers_used`` contains
        the list of provider names that contributed to the blend.
        """
        from app.analytics.ensemble.ensemble_config import get_ensemble_config
        from app.analytics.ensemble.ensemble_engine import EnsembleEngine

        config = get_ensemble_config(sport, self._model_type)
        provider_names = {p.name for p in config.providers}

        predictions: dict[str, dict[str, float]] = {}

        if "rule_based" in provider_names:
            try:
                predictions["rule_based"] = self._rule.get_event_probabilities(
                    sport, context,
                )
            except Exception as exc:
                logger.warning("ensemble_rule_based_failed", extra={"error": str(exc)})

        if "ml" in provider_names:
            try:
                predictions["ml"] = self._ml.get_event_probabilities(sport, context)
            except Exception as exc:
                logger.warning("ensemble_ml_failed", extra={"error": str(exc)})

        self.last_providers_used = sorted(predictions.keys())

        if not predictions:
            logger.info("ensemble_all_providers_failed", extra={"sport": sport})
            valid_events = MLB_PA_EVENTS if sport.lower() == "mlb" else None
            return normalize_probabilities(_MLB_DEFAULTS, valid_events)

        engine = EnsembleEngine()
        combined = engine.combine_from_config(predictions, config)

        valid_events = MLB_PA_EVENTS if sport.lower() == "mlb" else None
        return normalize_probabilities(combined, valid_events)
