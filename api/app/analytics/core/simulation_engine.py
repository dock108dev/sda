"""Base simulation engine interface.

Each sport provides its own simulation implementation that plugs into
this interface. The core engine handles iteration counting, result
aggregation, and output formatting.

Supports three usage modes:

1. **Legacy** — ``SimulationEngine("mlb").simulate_game(ctx)`` returns a
   ``SimulationResult`` placeholder (backward-compatible).
2. **Full Monte Carlo** — ``SimulationEngine("mlb").run_simulation(ctx,
   iterations=10000, seed=42)`` delegates to a sport-specific game
   simulator via ``SimulationRunner`` and returns aggregated results.
3. **ML-enhanced** — When ``probability_mode`` is ``"ml"`` in the game
   context, the engine uses the ``ProbabilityResolver`` to generate
   event probabilities from trained ML models.
"""

from __future__ import annotations

import importlib
import logging
import random
from typing import Any

from .simulation_runner import SimulationRunner
from .types import SimulationResult

logger = logging.getLogger(__name__)

# Registry mapping sport codes to (module_path, class_name).
_SPORT_SIMULATORS: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.sports.mlb.game_simulator", "MLBGameSimulator"),
}


class SimulationEngine:
    """Sport-agnostic simulation orchestrator.

    Routes to sport-specific game simulators and aggregates results
    via ``SimulationRunner``. Supports pluggable probability sources
    through the ``ProbabilityResolver``.
    """

    def __init__(self, sport: str) -> None:
        self.sport = sport.lower()
        self._simulator: Any | None = None

    def _get_sport_simulator(self) -> Any:
        """Lazily load and cache the sport-specific game simulator."""
        if self._simulator is not None:
            return self._simulator

        entry = _SPORT_SIMULATORS.get(self.sport)
        if entry is None:
            logger.warning("no_simulator_module", extra={"sport": self.sport})
            return None

        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        self._simulator = cls()
        return self._simulator

    def simulate_game(
        self,
        game_context: dict[str, Any],
        iterations: int = 1000,
    ) -> SimulationResult:
        """Run a game simulation over N iterations.

        Backward-compatible entry point. For full Monte Carlo results
        with aggregated statistics, use ``run_simulation()`` instead.

        Args:
            game_context: Sport-specific game setup data.
            iterations: Number of simulation iterations.

        Returns:
            Aggregated simulation result.
        """
        simulator = self._get_sport_simulator()
        if simulator is None:
            return SimulationResult(sport=self.sport, iterations=iterations)

        runner = SimulationRunner()
        summary = runner.run_simulations(
            simulator, game_context, iterations=iterations,
        )
        return SimulationResult(
            sport=self.sport,
            iterations=iterations,
            summary=summary,
        )

    def run_simulation(
        self,
        game_context: dict[str, Any],
        iterations: int = 10_000,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Run a full Monte Carlo simulation with aggregated results.

        Supports probability mode selection via ``game_context`` keys:

        - ``probability_mode``: ``"rule_based"`` (default) or ``"ml"``
        - ``ml_model``: Legacy key — sets mode to ``"ml"`` if present
        - ``profiles``: Entity profiles for ML probability generation

        Args:
            game_context: Sport-specific game setup data.
            iterations: Number of games to simulate.
            seed: Optional seed for deterministic results.

        Returns:
            Dict with win probabilities, average scores, score
            distribution, and probability source metadata.
        """
        simulator = self._get_sport_simulator()
        if simulator is None:
            return {
                "home_win_probability": 0.0,
                "away_win_probability": 0.0,
                "average_home_score": 0.0,
                "average_away_score": 0.0,
                "score_distribution": {},
                "iterations": 0,
            }

        context = dict(game_context)
        prob_meta: dict[str, Any] = {}

        # Resolve probability mode
        probability_mode = context.pop("probability_mode", None)
        ml_model_type = context.pop("ml_model", None)

        # Pitch-level simulation uses a different simulator entirely
        if probability_mode == "pitch_level" and self.sport == "mlb":
            return self._run_pitch_level(context, iterations, seed)

        if probability_mode in ("ml", "ensemble") or ml_model_type:
            model_type = ml_model_type or "plate_appearance"
            context, prob_meta = self._apply_probability_resolver(
                context, probability_mode or "ml", model_type,
            )
        elif probability_mode == "rule_based":
            context, prob_meta = self._apply_probability_resolver(
                context, "rule_based", "plate_appearance",
            )

        runner = SimulationRunner()
        result = runner.run_simulations(
            simulator, context,
            iterations=iterations, seed=seed,
        )

        if prob_meta:
            result["probability_source"] = prob_meta.get(
                "probability_source", "default",
            )
            result["probability_meta"] = prob_meta

        return result

    def _run_pitch_level(
        self,
        game_context: dict[str, Any],
        iterations: int,
        seed: int | None,
    ) -> dict[str, Any]:
        """Run pitch-level simulation using PitchLevelGameSimulator."""
        from app.analytics.simulation.mlb.pitch_simulator import (
            PitchLevelGameSimulator,
        )

        sim = PitchLevelGameSimulator()
        rng = random.Random(seed)

        home_wins = 0
        total_home = 0
        total_away = 0
        total_pitches = 0

        for _ in range(iterations):
            result = sim.simulate_game(game_context, rng=random.Random(rng.random()))
            total_home += result["home_score"]
            total_away += result["away_score"]
            total_pitches += result.get("total_pitches", 0)
            if result["winner"] == "home":
                home_wins += 1

        n = max(iterations, 1)
        return {
            "home_win_probability": round(home_wins / n, 4),
            "away_win_probability": round(1.0 - home_wins / n, 4),
            "average_home_score": round(total_home / n, 2),
            "average_away_score": round(total_away / n, 2),
            "iterations": iterations,
            "probability_source": "pitch_level",
            "average_pitches_per_game": round(total_pitches / n, 1),
        }

    def _apply_probability_resolver(
        self,
        game_context: dict[str, Any],
        mode: str,
        model_type: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Use the ProbabilityResolver to generate event probabilities.

        Args:
            game_context: Current game context.
            mode: Probability mode (``"rule_based"`` or ``"ml"``).
            model_type: Model type (e.g., ``"plate_appearance"``).

        Returns:
            Tuple of (updated context, metadata dict).
        """
        meta: dict[str, Any] = {}
        try:
            from app.analytics.probabilities.probability_resolver import (
                ProbabilityResolver,
            )

            resolver_config = {
                "probability_mode": mode,
                "fallback_mode": "rule_based",
                "strict_mode": False,
            }
            resolver = ProbabilityResolver(config=resolver_config)

            profiles = game_context.get("profiles", {})
            result = resolver.get_probabilities_with_meta(
                self.sport, model_type, profiles, mode=mode,
            )

            prob_meta = result.pop("_meta", {})
            meta = prob_meta

            # Convert to simulation probability keys
            sim_probs = _to_simulation_keys(result)

            if "home_probabilities" not in game_context:
                game_context["home_probabilities"] = sim_probs
            if "away_probabilities" not in game_context:
                game_context["away_probabilities"] = sim_probs

            game_context["_probability_source"] = meta.get(
                "probability_source", mode,
            )

            logger.info(
                "probability_resolved",
                extra={
                    "sport": self.sport,
                    "mode": mode,
                    "source": meta.get("probability_source"),
                },
            )

        except Exception as exc:
            logger.error(
                "probability_resolution_error",
                extra={"sport": self.sport, "mode": mode, "error": str(exc)},
            )
            meta = {"probability_source": "default", "error": str(exc)}

        return game_context, meta

    def _run_single_iteration(
        self,
        game_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one simulation iteration.

        Override in sport-specific subclasses.
        """
        return {}


def _to_simulation_keys(probs: dict[str, float]) -> dict[str, float]:
    """Convert event probability keys to simulation engine format.

    Maps ``"strikeout"`` → ``"strikeout_probability"``, etc.
    """
    result: dict[str, float] = {}
    for key, val in probs.items():
        if key.startswith("_"):
            continue
        if not key.endswith("_probability"):
            result[f"{key}_probability"] = val
        else:
            result[key] = val
    return result
