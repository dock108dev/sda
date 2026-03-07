"""MLB-specific simulation analysis.

Currently delegates to the generic SimulationAnalysis implementations.
Exists as a plugin point for future MLB-specific analysis (e.g.,
inning-by-inning breakdowns, run expectancy matrices).
"""

from __future__ import annotations

from typing import Any


class MLBSimulationAnalysis:
    """MLB simulation analysis — delegates to generic for now."""

    def summarize_results(
        self,
        simulation_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """MLB-specific result summary. Currently uses generic logic."""
        from app.analytics.core.simulation_analysis import SimulationAnalysis
        return SimulationAnalysis("mlb").summarize_results(simulation_results)

    def summarize_distribution(
        self,
        simulation_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from app.analytics.core.simulation_analysis import SimulationAnalysis
        return SimulationAnalysis("mlb").summarize_distribution(simulation_results)

    def summarize_team_totals(
        self,
        simulation_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from app.analytics.core.simulation_analysis import SimulationAnalysis
        return SimulationAnalysis("mlb").summarize_team_totals(simulation_results)

    def summarize_spreads(
        self,
        simulation_results: list[dict[str, Any]],
        spread_line: float,
    ) -> dict[str, Any]:
        from app.analytics.core.simulation_analysis import SimulationAnalysis
        return SimulationAnalysis("mlb").summarize_spreads(simulation_results, spread_line)

    def summarize_totals(
        self,
        simulation_results: list[dict[str, Any]],
        total_line: float,
    ) -> dict[str, Any]:
        from app.analytics.core.simulation_analysis import SimulationAnalysis
        return SimulationAnalysis("mlb").summarize_totals(simulation_results, total_line)
