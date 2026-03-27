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
from typing import Any

from .simulation_runner import SimulationRunner

logger = logging.getLogger(__name__)

# Registry mapping sport codes to (module_path, class_name).
_SPORT_SIMULATORS: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.sports.mlb.game_simulator", "MLBGameSimulator"),
    "nba": ("app.analytics.sports.nba.game_simulator", "NBAGameSimulator"),
    "nhl": ("app.analytics.sports.nhl.game_simulator", "NHLGameSimulator"),
    "ncaab": ("app.analytics.sports.ncaab.game_simulator", "NCAABGameSimulator"),
    "nfl": ("app.analytics.sports.nfl.game_simulator", "NFLGameSimulator"),
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
            return self._run_pitch_level(
                context, iterations, seed, keep_results=keep_results,
            )

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
        *,
        keep_results: bool = False,
    ) -> dict[str, Any]:
        """Run pitch-level simulation using PitchLevelGameSimulator.

        Resolves per-team profiles from ``game_context["profiles"]`` to
        create differentiated feature dicts, then delegates to
        ``SimulationRunner`` for iteration and aggregation.
        """
        from app.analytics.simulation.mlb.pitch_simulator import (
            PitchLevelGameSimulator,
        )

        context = dict(game_context)

        # Resolve per-team features from profiles
        profiles = context.pop("profiles", {})
        home_profile = profiles.get("home_profile", {})
        away_profile = profiles.get("away_profile", {})

        if home_profile or away_profile:
            home_metrics = _extract_profile_metrics(home_profile)
            away_metrics = _extract_profile_metrics(away_profile)

            # Home batting vs away pitching
            context["home_features"] = _profile_to_pitch_features(
                home_metrics, away_metrics,
            )
            # Away batting vs home pitching
            context["away_features"] = _profile_to_pitch_features(
                away_metrics, home_metrics,
            )

        # Attempt to load trained models
        pitch_model, bb_model = _load_pitch_models()
        sim = PitchLevelGameSimulator(
            pitch_model=pitch_model,
            batted_ball_model=bb_model,
        )

        runner = SimulationRunner()
        result = runner.run_simulations(
            sim, context,
            iterations=iterations, seed=seed,
            keep_results=keep_results,
        )
        result["probability_source"] = "pitch_level"

        return result

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
        base_extra = {"_model_id": model_id} if model_id else {}

        # When team profiles are provided (home_profile / away_profile),
        # resolve PA probabilities separately for each team — each team's
        # batting profile is paired with the opposing team's profile as
        # the "pitcher" side so the PA model sees differentiated features.
        home_profile = profiles.get("home_profile")
        away_profile = profiles.get("away_profile")

        if home_profile and away_profile:
            home_ctx = {
                "batter_profile": home_profile,
                "pitcher_profile": away_profile,
                **base_extra,
            }
            away_ctx = {
                "batter_profile": away_profile,
                "pitcher_profile": home_profile,
                **base_extra,
            }
            home_result = resolver.get_probabilities_with_meta(
                self.sport, model_type, home_ctx, mode=mode,
            )
            away_result = resolver.get_probabilities_with_meta(
                self.sport, model_type, away_ctx, mode=mode,
            )

            prob_meta = home_result.pop("_meta", {})
            away_result.pop("_meta", None)
            meta = prob_meta

            home_sim_probs = _to_simulation_keys(home_result)
            away_sim_probs = _to_simulation_keys(away_result)

            for issues in (
                validate_probabilities(home_sim_probs),
                validate_probabilities(away_sim_probs),
            ):
                if issues:
                    diagnostics.warnings.extend(issues)

            game_context["home_probabilities"] = home_sim_probs
            game_context["away_probabilities"] = away_sim_probs
        else:
            # Single-context resolution (batter_profile/pitcher_profile
            # already set, or empty profiles for league defaults)
            ctx = {**profiles, **base_extra}
            result = resolver.get_probabilities_with_meta(
                self.sport, model_type, ctx, mode=mode,
            )

            prob_meta = result.pop("_meta", {})
            meta = prob_meta

            sim_probs = _to_simulation_keys(result)
            validation_issues = validate_probabilities(sim_probs)
            if validation_issues:
                diagnostics.warnings.extend(validation_issues)

            game_context["home_probabilities"] = sim_probs
            game_context["away_probabilities"] = sim_probs

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


def _extract_profile_metrics(profile: Any) -> dict[str, float]:
    """Extract metrics dict from a profile (dict or object)."""
    if not profile:
        return {}
    if isinstance(profile, dict):
        return profile.get("metrics", profile)
    if hasattr(profile, "metrics"):
        return profile.metrics
    return {}


def _profile_to_pitch_features(
    batting_metrics: dict[str, float],
    pitching_metrics: dict[str, float],
) -> dict[str, float]:
    """Map team profile metrics to pitch simulator feature keys.

    Maps batter profile metrics and opposing pitcher profile metrics
    to the flat feature keys expected by ``MLBPitchOutcomeModel`` and
    ``MLBBattedBallModel``.
    """
    return {
        # Pitcher features (from opposing team's pitching profile)
        "pitcher_k_rate": pitching_metrics.get("k_rate", pitching_metrics.get("strikeout_rate", 0.22)),
        "pitcher_walk_rate": pitching_metrics.get("bb_rate", pitching_metrics.get("walk_rate", 0.08)),
        "pitcher_zone_rate": pitching_metrics.get("zone_swing_rate", 0.45),
        "pitcher_contact_allowed": 1.0 - pitching_metrics.get("whiff_rate", 0.23),
        # Batter features (from team's batting profile)
        "batter_contact_rate": batting_metrics.get("contact_rate", 0.77),
        "batter_swing_rate": batting_metrics.get("swing_rate", 0.47),
        "batter_zone_swing_rate": batting_metrics.get("zone_swing_rate", 0.65),
        "batter_chase_rate": batting_metrics.get("chase_rate", 0.30),
        # Batted ball features
        "batter_barrel_rate": batting_metrics.get("barrel_rate", 0.06),
        "batter_hard_hit_rate": batting_metrics.get("hard_hit_rate", 0.35),
        "batter_power_index": batting_metrics.get("power_index", 1.0),
        "pitcher_hard_hit_allowed": pitching_metrics.get("hard_hit_pct_against", 0.35),
        "exit_velocity": batting_metrics.get("avg_exit_velocity", batting_metrics.get("avg_exit_velo", 88.0)),
    }


def _load_pitch_models() -> tuple[Any, Any]:
    """Attempt to load trained pitch and batted ball models.

    Uses ``BaseModel.load()`` so the standard joblib→pickle fallback
    and ``_loaded`` flag are set correctly.

    Returns (pitch_model, batted_ball_model) — either may be None
    if no trained model is available.
    """
    pitch_model = None
    bb_model = None
    try:
        from app.analytics.models.core.model_registry import ModelRegistry
        registry = ModelRegistry()

        pitch_entry = registry.get_active_model("mlb", "pitch")
        if pitch_entry:
            from app.analytics.models.sports.mlb.pitch_model import (
                MLBPitchOutcomeModel,
            )
            pm = MLBPitchOutcomeModel()
            pm.load(pitch_entry["artifact_path"])
            pitch_model = pm

        bb_entry = registry.get_active_model("mlb", "batted_ball")
        if bb_entry:
            from app.analytics.models.sports.mlb.batted_ball_model import (
                MLBBattedBallModel,
            )
            bbm = MLBBattedBallModel()
            bbm.load(bb_entry["artifact_path"])
            bb_model = bbm
    except Exception:
        logger.warning("pitch_models_load_skipped", exc_info=True)

    return pitch_model, bb_model


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
