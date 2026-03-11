"""Simulation runner: executes and aggregates Monte Carlo simulations.

Runs a sport-specific game simulator many times and produces aggregated
statistics including win probabilities, average scores, and score
distributions.

Usage::

    from app.analytics.sports.mlb.game_simulator import MLBGameSimulator
    runner = SimulationRunner()
    summary = runner.run_simulations(MLBGameSimulator(), context, iterations=10000)
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any, Protocol


class GameSimulator(Protocol):
    """Protocol for sport-specific game simulators."""

    def simulate_game(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]: ...


class SimulationRunner:
    """Execute and aggregate game simulations."""

    def run_simulations(
        self,
        simulator: GameSimulator,
        game_context: dict[str, Any],
        iterations: int = 10_000,
        seed: int | None = None,
        *,
        keep_results: bool = False,
        use_lineup: bool = False,
    ) -> dict[str, Any]:
        """Run multiple game simulations and aggregate results.

        Args:
            simulator: Sport-specific game simulator instance.
            game_context: Context dict passed to each simulation.
            iterations: Number of games to simulate.
            seed: Optional seed for deterministic results.
            keep_results: If True, include per-game results under
                ``"raw_results"`` for downstream analysis.
            use_lineup: If True, use lineup-aware simulation method.

        Returns:
            Dict with win probabilities, average scores, and
            score distribution. If *keep_results* is True, also
            includes ``"raw_results"`` list.
        """
        rng = random.Random(seed)
        results: list[dict[str, Any]] = []

        if use_lineup:
            if not hasattr(simulator, "simulate_game_with_lineups"):
                raise RuntimeError(
                    f"{type(simulator).__name__} does not support lineup-aware simulation"
                )
            sim_fn = simulator.simulate_game_with_lineups
        else:
            sim_fn = simulator.simulate_game

        for _ in range(iterations):
            result = sim_fn(game_context, rng=rng)
            results.append(result)

        summary = self.aggregate_results(results)
        if keep_results:
            summary["raw_results"] = results
        return summary

    def aggregate_results(
        self,
        sim_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate individual game results into summary statistics.

        Args:
            sim_results: List of game result dicts, each with
                ``home_score``, ``away_score``, ``winner``.

        Returns:
            Summary dict with probabilities, averages, and distribution.
        """
        if not sim_results:
            return {
                "home_win_probability": 0.0,
                "away_win_probability": 0.0,
                "average_home_score": 0.0,
                "average_away_score": 0.0,
                "score_distribution": {},
                "iterations": 0,
            }

        n = len(sim_results)
        home_wins = sum(1 for r in sim_results if r.get("winner") == "home")
        total_home = sum(r.get("home_score", 0) for r in sim_results)
        total_away = sum(r.get("away_score", 0) for r in sim_results)

        # Score distribution (top 20 most common)
        score_counts: Counter[str] = Counter()
        for r in sim_results:
            key = f"{r.get('home_score', 0)}-{r.get('away_score', 0)}"
            score_counts[key] += 1

        distribution = {
            score: round(count / n, 4)
            for score, count in score_counts.most_common(20)
        }

        return {
            "home_win_probability": round(home_wins / n, 4),
            "away_win_probability": round((n - home_wins) / n, 4),
            "average_home_score": round(total_home / n, 2),
            "average_away_score": round(total_away / n, 2),
            "score_distribution": distribution,
            "iterations": n,
        }
