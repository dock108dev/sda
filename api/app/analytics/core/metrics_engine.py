"""Engine for computing derived analytical metrics.

The MetricsEngine provides sport-agnostic interfaces for metric calculation.
Sport-specific modules supply the actual formulas and stat mappings.

Future metrics include:
- Plate discipline (swing rate, contact rate, zone awareness)
- Power index / expected slugging
- Defensive metrics
- Pitching quality scores
- Team efficiency ratings
"""

from __future__ import annotations

from typing import Any


class MetricsEngine:
    """Compute derived metrics from raw stat data.

    This class defines the common interface. Sport modules provide
    calculation implementations via their own metrics classes.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()

    def calculate_player_metrics(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Derive analytical metrics from raw player stats.

        Args:
            stats: Raw stat dictionary (sport-specific keys).

        Returns:
            Dict of computed metric name → value.
        """
        return {}

    def calculate_team_metrics(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Derive analytical metrics from raw team stats.

        Args:
            stats: Raw stat dictionary (sport-specific keys).

        Returns:
            Dict of computed metric name → value.
        """
        return {}
