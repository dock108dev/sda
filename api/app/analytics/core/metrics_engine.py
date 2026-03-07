"""Engine for computing derived analytical metrics.

The MetricsEngine provides sport-agnostic interfaces for metric calculation.
It dynamically loads sport-specific modules that supply the actual formulas
and stat mappings.

Usage::

    engine = MetricsEngine("mlb")
    metrics = engine.calculate_player_metrics({
        "zone_swing_pct": 0.75,
        "outside_swing_pct": 0.30,
        "zone_contact_pct": 0.88,
        "outside_contact_pct": 0.60,
        "avg_exit_velocity": 90.0,
        "hard_hit_pct": 0.40,
    })
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Registry mapping sport codes to their metrics module path and class name.
_SPORT_METRICS: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.sports.mlb.metrics", "MLBMetrics"),
}


class MetricsEngine:
    """Compute derived metrics from raw stat data.

    Dynamically loads the appropriate sport-specific metrics class
    and delegates all calculations to it.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()
        self._metrics_instance: Any | None = None

    def _get_sport_metrics(self) -> Any:
        """Lazily load and cache the sport-specific metrics class."""
        if self._metrics_instance is not None:
            return self._metrics_instance

        entry = _SPORT_METRICS.get(self.sport)
        if entry is None:
            logger.warning("no_metrics_module", extra={"sport": self.sport})
            return None

        import importlib

        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        self._metrics_instance = cls()
        return self._metrics_instance

    def calculate_player_metrics(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Derive analytical metrics from raw player stats.

        Delegates to the sport module's ``build_player_metrics`` method.
        Returns an empty dict if no sport module is registered.

        Args:
            stats: Raw stat dictionary (sport-specific keys).

        Returns:
            Dict of computed metric name -> value.
        """
        sport_metrics = self._get_sport_metrics()
        if sport_metrics is None:
            return {}
        return sport_metrics.build_player_metrics(stats)

    def calculate_team_metrics(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Derive analytical metrics from raw team stats.

        Delegates to the sport module's ``build_team_metrics`` method.

        Args:
            stats: Raw stat dictionary (sport-specific keys).

        Returns:
            Dict of computed metric name -> value.
        """
        sport_metrics = self._get_sport_metrics()
        if sport_metrics is None:
            return {}
        return sport_metrics.build_team_metrics(stats)

    def calculate_matchup_metrics(
        self,
        entity_a: dict[str, Any],
        entity_b: dict[str, Any],
    ) -> dict[str, float]:
        """Produce matchup probability metrics between two entities.

        Delegates to the sport module's ``build_matchup_metrics`` method.

        Args:
            entity_a: Stats/metrics for the first entity (e.g., batter).
            entity_b: Stats/metrics for the second entity (e.g., pitcher).

        Returns:
            Dict of probability metric name -> value.
        """
        sport_metrics = self._get_sport_metrics()
        if sport_metrics is None:
            return {}
        return sport_metrics.build_matchup_metrics(entity_a, entity_b)
