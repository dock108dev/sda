"""Live simulation engine: runs simulations from partial game states.

Routes to sport-specific live simulators and aggregates results into
win probabilities and expected scores. Designed for real-time use
during live games.

Usage::

    engine = LiveSimulationEngine("mlb")
    result = engine.simulate_from_state(game_state, iterations=2000)
"""

from __future__ import annotations

import importlib
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

# Registry mapping sport codes to (module_path, class_name).
_SPORT_LIVE_SIMULATORS: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.sports.mlb.live_simulator", "MLBLiveSimulator"),
}


class LiveSimulationEngine:
    """Sport-agnostic live simulation orchestrator."""

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()
        self._simulator: Any | None = None

    def _get_sport_simulator(self) -> Any:
        """Lazily load and cache the sport-specific live simulator."""
        if self._simulator is not None:
            return self._simulator

        entry = _SPORT_LIVE_SIMULATORS.get(self.sport)
        if entry is None:
            logger.warning("no_live_simulator", extra={"sport": self.sport})
            return None

        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        self._simulator = cls()
        return self._simulator

    def simulate_from_state(
        self,
        game_state: dict[str, Any],
        iterations: int = 2000,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Run Monte Carlo simulation from a partial game state.

        Args:
            game_state: Current game state (inning, outs, bases, score,
                probability distributions).
            iterations: Number of simulations to run.
            seed: Optional seed for determinism.

        Returns:
            Dict with win probabilities, expected scores, and the
            current game state echo.
        """
        simulator = self._get_sport_simulator()
        if simulator is None:
            return _empty_result(game_state)

        rng = random.Random(seed)
        results: list[dict[str, Any]] = []

        for _ in range(iterations):
            result = simulator.simulate_from_state(game_state, rng=rng)
            results.append(result)

        return _aggregate_live_results(results, game_state, iterations)


def _aggregate_live_results(
    results: list[dict[str, Any]],
    game_state: dict[str, Any],
    iterations: int,
) -> dict[str, Any]:
    """Aggregate live simulation results."""
    n = len(results)
    if n == 0:
        return _empty_result(game_state)

    home_wins = sum(1 for r in results if r.get("winner") == "home")
    total_home = sum(r.get("home_score", 0) for r in results)
    total_away = sum(r.get("away_score", 0) for r in results)

    score = game_state.get("score", {})

    return {
        "inning": game_state.get("inning", 1),
        "half": game_state.get("half", "top"),
        "score": score,
        "home_win_probability": round(home_wins / n, 4),
        "away_win_probability": round((n - home_wins) / n, 4),
        "expected_final_score": {
            "home": round(total_home / n, 2),
            "away": round(total_away / n, 2),
        },
        "iterations": iterations,
    }


def _empty_result(game_state: dict[str, Any]) -> dict[str, Any]:
    score = game_state.get("score", {})
    return {
        "inning": game_state.get("inning", 1),
        "half": game_state.get("half", "top"),
        "score": score,
        "home_win_probability": 0.5,
        "away_win_probability": 0.5,
        "expected_final_score": {
            "home": score.get("home", 0),
            "away": score.get("away", 0),
        },
        "iterations": 0,
    }
