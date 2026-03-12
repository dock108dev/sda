"""Simulation diagnostics — structured transparency for simulation runs.

Captures what the user requested, what actually ran, whether a fallback
occurred, and details about the model (if any) that produced the
probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelInfo:
    """Identity and quality metadata for the ML model used."""

    model_id: str
    version: int
    trained_at: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class SimulationDiagnostics:
    """Full diagnostics for a single simulation run.

    Attributes:
        requested_mode: What the user asked for (``"ml"``, ``"ensemble"``,
            ``"rule_based"``).
        executed_mode: What actually ran — may differ when a fallback fires.
        fallback_used: True if the requested mode could not be satisfied.
        fallback_reason: Human-readable explanation when ``fallback_used``
            is True (e.g., ``"no_active_ml_model"``, ``"inference_error"``).
        model_info: Populated when an ML model was successfully used.
        warnings: Non-fatal issues discovered during the run (e.g.,
            probability validation problems).
    """

    requested_mode: str
    executed_mode: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    model_info: ModelInfo | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for inclusion in the API response."""
        d: dict[str, Any] = {
            "requested_mode": self.requested_mode,
            "executed_mode": self.executed_mode,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "model_info": None,
            "warnings": self.warnings,
        }
        if self.model_info is not None:
            d["model_info"] = {
                "model_id": self.model_info.model_id,
                "version": self.model_info.version,
                "trained_at": self.model_info.trained_at,
                "metrics": self.model_info.metrics,
            }
        return d
