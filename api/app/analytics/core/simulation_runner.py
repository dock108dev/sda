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

        summary = {
            "home_win_probability": round(home_wins / n, 4),
            "away_win_probability": round((n - home_wins) / n, 4),
            "average_home_score": round(total_home / n, 2),
            "average_away_score": round(total_away / n, 2),
            "score_distribution": distribution,
            "iterations": n,
        }

        # Add event summary if results contain event data
        if sim_results and "home_events" in sim_results[0]:
            summary["event_summary"] = self._aggregate_events(sim_results)

        return summary

    def _aggregate_events(
        self,
        sim_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate per-game event counts into batch-level statistics."""
        n = len(sim_results)

        def _team_summary(key: str) -> dict[str, Any]:
            totals: Counter[str] = Counter()
            for r in sim_results:
                ev = r.get(key, {})
                for k, v in ev.items():
                    totals[k] += v

            pa = totals.get("pa_total", 1) or 1
            hits = totals.get("single", 0) + totals.get("double", 0) + totals.get("triple", 0) + totals.get("home_run", 0)

            return {
                "avg_pa": round(totals.get("pa_total", 0) / n, 1),
                "avg_hits": round(hits / n, 1),
                "avg_hr": round(totals.get("home_run", 0) / n, 1),
                "avg_bb": round(totals.get("walk", 0) / n, 1),
                "avg_k": round(totals.get("strikeout", 0) / n, 1),
                "avg_runs": round(
                    sum(r.get("home_score" if key == "home_events" else "away_score", 0) for r in sim_results) / n,
                    1,
                ),
                "pa_rates": {
                    "k_pct": round(totals.get("strikeout", 0) / pa, 3),
                    "bb_pct": round(totals.get("walk", 0) / pa, 3),
                    "single_pct": round(totals.get("single", 0) / pa, 3),
                    "double_pct": round(totals.get("double", 0) / pa, 3),
                    "triple_pct": round(totals.get("triple", 0) / pa, 3),
                    "hr_pct": round(totals.get("home_run", 0) / pa, 3),
                    "out_pct": round(totals.get("out", 0) / pa, 3),
                },
            }

        # Game-level metrics
        from .simulation_analysis import _median

        total_runs = [
            r.get("home_score", 0) + r.get("away_score", 0)
            for r in sim_results
        ]
        median_total = _median(total_runs)
        extra_innings = sum(
            1 for r in sim_results if r.get("innings_played", 9) > 9
        )
        shutouts = sum(
            1 for r in sim_results
            if r.get("home_score", 0) == 0 or r.get("away_score", 0) == 0
        )
        one_run_games = sum(
            1 for r in sim_results
            if abs(r.get("home_score", 0) - r.get("away_score", 0)) == 1
        )

        return {
            "home": _team_summary("home_events"),
            "away": _team_summary("away_events"),
            "game": {
                "avg_total_runs": round(sum(total_runs) / n, 1),
                "median_total_runs": round(median_total, 0),
                "extra_innings_pct": round(extra_innings / n, 3),
                "shutout_pct": round(shutouts / n, 3),
                "one_run_game_pct": round(one_run_games / n, 3),
            },
        }
