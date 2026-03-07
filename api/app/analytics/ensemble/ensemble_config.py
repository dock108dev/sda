"""Ensemble configuration.

Defines the weighting and provider list for ensemble probability
combination. Configurations are stored per sport + model_type pair.

Usage::

    config = EnsembleConfig(
        sport="mlb",
        model_type="plate_appearance",
        providers=[
            ProviderWeight(name="rule_based", weight=0.4),
            ProviderWeight(name="ml", weight=0.6),
        ],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderWeight:
    """A named probability provider with its ensemble weight."""

    name: str
    weight: float


@dataclass
class EnsembleConfig:
    """Configuration for an ensemble combination.

    Attributes:
        sport: Sport code (e.g., ``"mlb"``).
        model_type: Model type (e.g., ``"plate_appearance"``).
        providers: Ordered list of providers with weights.
    """

    sport: str
    model_type: str
    providers: list[ProviderWeight] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sport": self.sport,
            "model_type": self.model_type,
            "providers": [
                {"name": p.name, "weight": p.weight} for p in self.providers
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnsembleConfig:
        providers = [
            ProviderWeight(name=p["name"], weight=float(p["weight"]))
            for p in data.get("providers", [])
        ]
        return cls(
            sport=data["sport"],
            model_type=data["model_type"],
            providers=providers,
        )

    @property
    def total_weight(self) -> float:
        return sum(p.weight for p in self.providers)


# Default configs per sport + model_type.
_DEFAULT_CONFIGS: dict[tuple[str, str], EnsembleConfig] = {
    ("mlb", "plate_appearance"): EnsembleConfig(
        sport="mlb",
        model_type="plate_appearance",
        providers=[
            ProviderWeight(name="rule_based", weight=0.4),
            ProviderWeight(name="ml", weight=0.6),
        ],
    ),
    ("mlb", "game"): EnsembleConfig(
        sport="mlb",
        model_type="game",
        providers=[
            ProviderWeight(name="rule_based", weight=0.5),
            ProviderWeight(name="ml", weight=0.5),
        ],
    ),
}

# Runtime registry for custom configs (set via API).
_custom_configs: dict[tuple[str, str], EnsembleConfig] = {}


def get_ensemble_config(sport: str, model_type: str) -> EnsembleConfig:
    """Get the ensemble config for a sport + model_type.

    Returns custom config if set, otherwise the default.
    """
    key = (sport.lower(), model_type)
    return _custom_configs.get(key) or _DEFAULT_CONFIGS.get(
        key,
        EnsembleConfig(
            sport=sport,
            model_type=model_type,
            providers=[ProviderWeight(name="rule_based", weight=1.0)],
        ),
    )


def set_ensemble_config(config: EnsembleConfig) -> None:
    """Register a custom ensemble config at runtime."""
    key = (config.sport.lower(), config.model_type)
    _custom_configs[key] = config


def list_ensemble_configs() -> list[EnsembleConfig]:
    """List all known ensemble configs (defaults + custom overrides)."""
    merged: dict[tuple[str, str], EnsembleConfig] = {}
    for key, cfg in _DEFAULT_CONFIGS.items():
        merged[key] = cfg
    for key, cfg in _custom_configs.items():
        merged[key] = cfg
    return list(merged.values())
