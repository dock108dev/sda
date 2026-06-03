"""Helper functions for simulation engine probability setup."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


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
