"""Win probability model: computes and tracks win probability over time.

Provides both point-in-time win probability from simulation results
and timeline generation for win probability charts.

Usage::

    model = WinProbabilityModel()
    wp = model.calculate_win_probability(sim_results)
    timeline = model.build_timeline(game_states_with_results)
"""

from __future__ import annotations

from typing import Any


class WinProbabilityModel:
    """Calculate and track win probabilities."""

    def calculate_win_probability(
        self,
        simulation_results: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Calculate win probability from simulation results.

        Args:
            simulation_results: List of game result dicts, each with
                ``winner`` key set to "home" or "away".

        Returns:
            Dict with ``home_wp`` and ``away_wp``.
        """
        if not simulation_results:
            return {"home_wp": 0.5, "away_wp": 0.5}

        n = len(simulation_results)
        home_wins = sum(1 for r in simulation_results if r.get("winner") == "home")
        home_wp = round(home_wins / n, 4)

        return {
            "home_wp": home_wp,
            "away_wp": round(1.0 - home_wp, 4),
        }

    def build_timeline(
        self,
        snapshots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build a win probability timeline from simulation snapshots.

        Each snapshot should contain at minimum ``inning``, ``half``,
        and ``home_win_probability``.

        Args:
            snapshots: List of live simulation result dicts, ordered
                chronologically.

        Returns:
            List of timeline entries suitable for charting.
        """
        timeline: list[dict[str, Any]] = []

        for snap in snapshots:
            inning = snap.get("inning", 0)
            half = snap.get("half", "top")
            home_wp = snap.get("home_win_probability", 0.5)

            label = f"{'T' if half == 'top' else 'B'}{inning}"

            timeline.append({
                "inning": inning,
                "half": half,
                "label": label,
                "home_wp": round(home_wp, 4),
                "away_wp": round(1.0 - home_wp, 4),
            })

        return timeline

    def generate_live_timeline(
        self,
        game_states: list[dict[str, Any]],
        engine: Any,
        iterations: int = 1000,
        seed: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generate a full win probability timeline by simulating from
        each game state snapshot.

        Args:
            game_states: Ordered list of game state dicts (from PBP data).
            engine: A ``LiveSimulationEngine`` instance.
            iterations: Simulations per state.
            seed: Optional base seed (incremented per state).

        Returns:
            Win probability timeline.
        """
        snapshots: list[dict[str, Any]] = []

        for i, state in enumerate(game_states):
            state_seed = (seed + i) if seed is not None else None
            result = engine.simulate_from_state(
                state, iterations=iterations, seed=state_seed,
            )
            snapshots.append(result)

        return self.build_timeline(snapshots)
