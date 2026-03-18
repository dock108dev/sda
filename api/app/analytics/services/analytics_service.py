"""Service layer connecting analytics logic to API endpoints.

Provides a clean interface for the router layer to call without
needing to know about engine internals or sport module resolution.
"""

from __future__ import annotations

from typing import Any

from app.analytics.core.simulation_analysis import SimulationAnalysis
from app.analytics.core.simulation_engine import SimulationEngine


class AnalyticsService:
    """High-level analytics service used by API routes."""

    def run_full_simulation(
        self,
        sport: str,
        game_context: dict[str, Any],
        iterations: int = 10_000,
        seed: int | None = None,
        sportsbook: dict[str, Any] | None = None,
        use_lineup: bool = False,
    ) -> dict[str, Any]:
        """Run a Monte Carlo simulation with full analysis.

        Args:
            sport: Sport code.
            game_context: Probability distributions for home/away teams.
            iterations: Number of games to simulate.
            seed: Optional seed for deterministic results.
            sportsbook: Optional sportsbook lines for comparison.
            use_lineup: If True, use lineup-aware simulation.

        Returns:
            Dict with win probabilities, score distributions, and
            optional sportsbook comparison.
        """
        sim = SimulationEngine(sport)
        result = sim.run_simulation(
            game_context, iterations=iterations, seed=seed,
            keep_results=True, use_lineup=use_lineup,
        )

        raw_results = result.pop("raw_results", None)
        if raw_results is None:
            return result

        # Preserve event_summary and diagnostics computed by the runner
        event_summary = result.get("event_summary")
        diagnostics = result.get("_diagnostics")
        prob_source = result.get("probability_source")
        prob_meta = result.get("probability_meta")

        analysis = SimulationAnalysis(sport)
        summary = analysis.summarize_results(raw_results, sportsbook=sportsbook)

        # Re-attach data that summarize_results doesn't know about
        if event_summary is not None:
            summary["event_summary"] = event_summary
        if diagnostics is not None:
            summary["_diagnostics"] = diagnostics
        if prob_source is not None:
            summary["probability_source"] = prob_source
        if prob_meta is not None:
            summary["probability_meta"] = prob_meta

        return summary
