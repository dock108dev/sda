"""Base simulation engine interface.

Each sport provides its own simulation implementation that plugs into
this interface. The core engine handles iteration counting, result
aggregation, and output formatting.

Future capabilities:
- Monte Carlo game simulation
- Plate appearance / at-bat simulation (MLB)
- Possession-level simulation (NBA)
- Season projection models
- Odds comparison against simulation outputs
"""

from __future__ import annotations

from typing import Any

from .types import SimulationResult


class SimulationEngine:
    """Sport-agnostic simulation runner.

    Subclassed by sport-specific simulators that implement the
    ``_run_single_iteration`` method.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()

    def simulate_game(
        self,
        game_context: dict[str, Any],
        iterations: int = 1000,
    ) -> SimulationResult:
        """Run a game simulation over N iterations.

        Args:
            game_context: Sport-specific game setup data (teams,
                rosters, conditions, etc.).
            iterations: Number of simulation iterations.

        Returns:
            Aggregated simulation result.
        """
        return SimulationResult(sport=self.sport, iterations=iterations)

    def _run_single_iteration(
        self,
        game_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one simulation iteration.

        Override in sport-specific subclasses.
        """
        return {}
