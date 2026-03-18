"""Probability resolver.

Chooses the correct probability provider based on configuration
and provides a single interface for the simulation engine.
No silent fallback — if the ML model fails, the error propagates.

Usage::

    resolver = ProbabilityResolver(config={
        "probability_mode": "ml",
    })
    probs = resolver.get_probabilities("mlb", "plate_appearance", context)
"""

from __future__ import annotations

import logging
from typing import Any

from .probability_provider import (
    EnsembleProvider,
    MLProvider,
    ProbabilityProvider,
    RuleBasedProvider,
)

logger = logging.getLogger(__name__)

# Supported modes.
MODE_RULE_BASED = "rule_based"
MODE_ML = "ml"
MODE_ENSEMBLE = "ensemble"

_DEFAULT_CONFIG: dict[str, Any] = {
    "probability_mode": MODE_ML,
}


class ProbabilityResolver:
    """Resolve and execute the correct probability provider.

    Args:
        config: Configuration dict with ``probability_mode`` key.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = {**_DEFAULT_CONFIG, **(config or {})}
        self._providers: dict[str, ProbabilityProvider] = {}

    @property
    def mode(self) -> str:
        """Current probability mode."""
        return self._config.get("probability_mode", MODE_ML)

    def resolve_provider(
        self,
        sport: str,
        model_type: str,
        mode: str | None = None,
    ) -> ProbabilityProvider:
        """Get the provider for the given mode.

        Args:
            sport: Sport code.
            model_type: Model type (e.g., ``"plate_appearance"``).
            mode: Override mode. Uses config default if ``None``.

        Returns:
            ``ProbabilityProvider`` instance.

        Raises:
            ValueError: If the mode is not supported.
        """
        mode = mode or self.mode

        if mode == MODE_RULE_BASED:
            return self._get_or_create(MODE_RULE_BASED, RuleBasedProvider)

        if mode == MODE_ML:
            key = f"{MODE_ML}:{model_type}"
            if key not in self._providers:
                self._providers[key] = MLProvider(model_type=model_type)
            return self._providers[key]

        if mode == MODE_ENSEMBLE:
            key = f"{MODE_ENSEMBLE}:{model_type}"
            if key not in self._providers:
                self._providers[key] = EnsembleProvider(model_type=model_type)
            return self._providers[key]

        raise ValueError(f"Unsupported probability mode: {mode}")

    def get_probabilities(
        self,
        sport: str,
        model_type: str,
        context: dict[str, Any],
        mode: str | None = None,
    ) -> dict[str, float]:
        """Get normalized event probabilities.

        Executes the configured provider. Raises on failure — no silent fallback.

        Args:
            sport: Sport code.
            model_type: Model type.
            context: Profiles and game context.
            mode: Override mode.

        Returns:
            Normalized probability dict with ``_meta`` key removed
            (metadata is attached to the return of
            ``get_probabilities_with_meta``).
        """
        result = self.get_probabilities_with_meta(
            sport, model_type, context, mode,
        )
        # Strip metadata key if present
        result.pop("_meta", None)
        return result

    def get_probabilities_with_meta(
        self,
        sport: str,
        model_type: str,
        context: dict[str, Any],
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Get probabilities with source metadata.

        Returns:
            Probability dict with an additional ``_meta`` key containing
            ``requested_mode``, ``executed_mode``, ``probability_source``,
            and ``model_info`` (when ML provider succeeds).
        """
        effective_mode = mode or self.mode

        try:
            provider = self.resolve_provider(sport, model_type, effective_mode)
            probs = provider.get_event_probabilities(sport, context)
            meta: dict[str, Any] = {
                "probability_source": provider.provider_name,
                "model_type": model_type,
                "requested_mode": effective_mode,
                "executed_mode": provider.provider_name,
            }
            # Attach model_info when ML provider was used
            if effective_mode in (MODE_ML, MODE_ENSEMBLE):
                meta["model_info"] = self._get_model_info(sport, model_type)
            return {**probs, "_meta": meta}

        except Exception as exc:
            logger.error(
                "probability_provider_failed mode=%s sport=%s error=%s",
                effective_mode, sport, exc,
                exc_info=True,
            )
            raise RuntimeError(
                f"ML probability provider failed (mode={effective_mode}, "
                f"sport={sport}, model_type={model_type}): {exc}"
            ) from exc

    @staticmethod
    def _get_model_info(sport: str, model_type: str) -> dict[str, Any] | None:
        """Fetch model identity info from the inference engine."""
        try:
            from app.analytics.inference.model_inference_engine import (
                ModelInferenceEngine,
            )
            engine = ModelInferenceEngine()
            status = engine.get_model_status(sport, model_type)
            if status.get("available"):
                return {
                    "model_id": status["model_id"],
                    "version": status["version"],
                    "trained_at": status["trained_at"],
                    "metrics": status["metrics"],
                }
        except Exception:
            pass
        return None

    def _get_or_create(
        self,
        key: str,
        cls: type[ProbabilityProvider],
    ) -> ProbabilityProvider:
        if key not in self._providers:
            self._providers[key] = cls()
        return self._providers[key]
