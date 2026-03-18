"""Base simulation engine interface.

Each sport provides its own simulation implementation that plugs into
this interface. The core engine handles iteration counting, result
aggregation, and output formatting.

Supports two usage modes:

1. **Full Monte Carlo** — ``SimulationEngine("mlb").run_simulation(ctx,
   iterations=10000, seed=42)`` delegates to a sport-specific game
   simulator via ``SimulationRunner`` and returns aggregated results.
2. **ML-enhanced** — When ``probability_mode`` is ``"ml"`` in the game
   context, the engine uses the ``ProbabilityResolver`` to generate
   event probabilities from trained ML models.
"""

from __future__ import annotations

import importlib
import logging
import random
from typing import Any

from .simulation_runner import SimulationRunner

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

    def run_simulation(
        self,
        game_context: dict[str, Any],
        iterations: int = 10_000,
        seed: int | None = None,
        *,
        keep_results: bool = False,
        use_lineup: bool = False,
    ) -> dict[str, Any]:
        """Run a full Monte Carlo simulation with aggregated results.

        Supports probability mode selection via ``game_context`` keys:

        - ``probability_mode``: ``"rule_based"``, ``"ml"``, ``"ensemble"``,
          or ``"pitch_level"``
        - ``profiles``: Entity profiles for ML probability generation

        Args:
            game_context: Sport-specific game setup data.
            iterations: Number of games to simulate.
            seed: Optional seed for deterministic results.
            keep_results: If True, include per-game results under
                ``"raw_results"`` for downstream analysis.

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

        # Resolve probability mode and optional model override
        probability_mode = context.pop("probability_mode", None)
        model_id = context.pop("_model_id", None)

        # Pitch-level simulation uses a different simulator entirely
        if probability_mode == "pitch_level" and self.sport == "mlb":
            return self._run_pitch_level(context, iterations, seed)

        if probability_mode in ("ml", "ensemble"):
            context, prob_meta = self._apply_probability_resolver(
                context, probability_mode, "plate_appearance",
                model_id=model_id,
            )
        elif probability_mode == "rule_based":
            context, prob_meta = self._apply_probability_resolver(
                context, "rule_based", "plate_appearance",
            )

        runner = SimulationRunner()
        result = runner.run_simulations(
            simulator, context,
            iterations=iterations, seed=seed,
            keep_results=keep_results,
            use_lineup=use_lineup,
        )

        if prob_meta:
            result["probability_source"] = prob_meta.get(
                "probability_source", "default",
            )
            # Extract diagnostics before storing meta
            diagnostics = prob_meta.pop("_diagnostics", None)
            result["probability_meta"] = prob_meta
            if diagnostics is not None:
                result["_diagnostics"] = diagnostics

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
            result = sim.simulate_game(game_context, rng=rng)
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
        *,
        model_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Use the ProbabilityResolver to generate event probabilities.

        Priority order:
        1. User-explicit probabilities (already in game_context)
        2. Resolver output (ml / ensemble / rule_based modes)
        3. Profile-derived probabilities (set by analytics_routes for rule_based)
        4. League defaults

        Args:
            game_context: Current game context.
            mode: Probability mode (``"rule_based"`` or ``"ml"``).
            model_type: Model type (e.g., ``"plate_appearance"``).

        Returns:
            Tuple of (updated context, metadata dict).
        """
        from .simulation_diagnostics import ModelInfo, SimulationDiagnostics

        diagnostics = SimulationDiagnostics(
            requested_mode=mode,
            executed_mode=mode,
        )
        meta: dict[str, Any] = {}

        from app.analytics.probabilities.probability_provider import (
            validate_probabilities,
        )
        from app.analytics.probabilities.probability_resolver import (
            ProbabilityResolver,
        )

        resolver_config = {
            "probability_mode": mode,
        }
        resolver = ProbabilityResolver(config=resolver_config)

        profiles = game_context.get("profiles", {})
        if model_id:
            profiles = {**profiles, "_model_id": model_id}
        result = resolver.get_probabilities_with_meta(
            self.sport, model_type, profiles, mode=mode,
        )

        prob_meta = result.pop("_meta", {})
        meta = prob_meta

        # Build diagnostics from resolver metadata
        diagnostics.executed_mode = prob_meta.get("executed_mode", mode)
        model_info_raw = prob_meta.get("model_info")
        if model_info_raw and isinstance(model_info_raw, dict):
            diagnostics.model_info = ModelInfo(
                model_id=model_info_raw.get("model_id", ""),
                version=model_info_raw.get("version", 0),
                trained_at=model_info_raw.get("trained_at"),
                metrics=model_info_raw.get("metrics", {}),
            )

        # Convert to simulation probability keys
        sim_probs = _to_simulation_keys(result)

        # Validate resolver output and add issues as warnings
        validation_issues = validate_probabilities(sim_probs)
        if validation_issues:
            diagnostics.warnings.extend(validation_issues)

        game_context["home_probabilities"] = sim_probs
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

        # Attach diagnostics to meta for upstream consumption
        meta["_diagnostics"] = diagnostics
        return game_context, meta


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
