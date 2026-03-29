"""Profile aggregation, stats conversion, and sklearn model factory.

Rolling profile builder, stats-to-metrics conversion with derived
composites, game score extraction, and sklearn model instantiation
used by training, backtest, and batch simulation tasks.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile aggregation
# ---------------------------------------------------------------------------


def build_rolling_profile(
    team_games: list[tuple[str, object]],
    *,
    before_date: str,
    window: int,
    min_games: int = 5,
) -> dict | None:
    """Aggregate a team's prior games into a rolling profile.

    Args:
        team_games: Chronologically sorted list of (date_str, MLBGameAdvancedStats).
        before_date: Only include games strictly before this date.
        window: Maximum number of prior games to include.
        min_games: Minimum prior games required; returns None if insufficient.
    """
    prior = [stats for date_str, stats in team_games if date_str < before_date]

    if len(prior) < min_games:
        return None

    recent = prior[-window:]
    all_metrics: list[dict] = [stats_to_metrics(s) for s in recent]

    aggregated: dict[str, float] = {}
    for key in all_metrics[0]:
        values = [m[key] for m in all_metrics if key in m]
        if values:
            aggregated[key] = round(sum(values) / len(values), 4)

    return aggregated


# ---------------------------------------------------------------------------
# Stats → metrics conversion
# ---------------------------------------------------------------------------


def stats_to_metrics(stats: Any) -> dict:
    """Convert MLBGameAdvancedStats row to metrics dict for feature builder.

    Exposes both raw DB columns and derived composites so the feature
    builder has a rich set of inputs to choose from.
    """
    total_pitches = stats.total_pitches or 0
    balls_in_play = stats.balls_in_play or 0

    return {
        # --- Raw plate discipline columns ---
        "total_pitches": float(total_pitches),
        "zone_pitches": float(stats.zone_pitches or 0),
        "zone_swings": float(stats.zone_swings or 0),
        "zone_contact": float(stats.zone_contact or 0),
        "outside_pitches": float(stats.outside_pitches or 0),
        "outside_swings": float(stats.outside_swings or 0),
        "outside_contact": float(stats.outside_contact or 0),
        # --- Raw plate discipline percentages ---
        "z_swing_pct": stats.z_swing_pct or 0.0,
        "o_swing_pct": stats.o_swing_pct or 0.0,
        "z_contact_pct": stats.z_contact_pct or 0.0,
        "o_contact_pct": stats.o_contact_pct or 0.0,
        # --- Raw quality of contact columns ---
        "balls_in_play": float(balls_in_play),
        "hard_hit_count": float(stats.hard_hit_count or 0),
        "barrel_count": float(stats.barrel_count or 0),
        # --- Raw quality of contact percentages ---
        "avg_exit_velo": stats.avg_exit_velo or 88.0,
        "hard_hit_pct": stats.hard_hit_pct or 0.0,
        "barrel_pct": stats.barrel_pct or 0.0,
        # --- Derived composites (original 8) ---
        "contact_rate": _safe_rate(stats.z_contact_pct, stats.o_contact_pct),
        "power_index": _power_index(stats.avg_exit_velo, stats.barrel_pct),
        "barrel_rate": stats.barrel_pct or 0.0,
        "hard_hit_rate": stats.hard_hit_pct or 0.0,
        "swing_rate": _safe_rate(stats.z_swing_pct, stats.o_swing_pct),
        "whiff_rate": _whiff_rate(stats),
        "avg_exit_velocity": stats.avg_exit_velo or 88.0,
        "expected_slug": _expected_slug(stats),
        # --- Additional derived ratios ---
        "zone_swing_rate": (
            (stats.zone_swings / stats.zone_pitches)
            if (stats.zone_pitches or 0) > 0 else 0.0
        ),
        "chase_rate": (
            (stats.outside_swings / stats.outside_pitches)
            if (stats.outside_pitches or 0) > 0 else 0.0
        ),
        "zone_contact_rate": (
            (stats.zone_contact / stats.zone_swings)
            if (stats.zone_swings or 0) > 0 else 0.0
        ),
        "outside_contact_rate": (
            (stats.outside_contact / stats.outside_swings)
            if (stats.outside_swings or 0) > 0 else 0.0
        ),
        "plate_discipline_index": _plate_discipline_index(stats),
    }


def _safe_rate(zone_pct: float | None, outside_pct: float | None) -> float:
    """Combine zone and outside rates into an overall rate."""
    z = zone_pct or 0.0
    o = outside_pct or 0.0
    return round((z + o) / 2, 4) if (z or o) else 0.0


def _power_index(avg_ev: float | None, barrel_pct: float | None) -> float:
    """Composite power metric from exit velocity and barrel rate.

    Normalized so that league-average inputs (ev=88, barrel_pct=0.07)
    produce a value of 1.0.  This keeps the HR formula in matchup.py
    calibrated: ``barrel_rate * power_index * BARREL_HR_CONVERSION``
    should produce ~3% HR rate for league-average batters.
    """
    ev = avg_ev or 88.0
    bp = barrel_pct or 0.07
    raw = (ev / 88.0) * (1 + bp * 5)
    # Normalize: league avg raw = (88/88) * (1 + 0.07*5) = 1.35
    return round(raw / 1.35, 4)


def _whiff_rate(stats: Any) -> float:
    """Calculate whiff rate from available swing/contact data."""
    total_swings = (stats.zone_swings or 0) + (stats.outside_swings or 0)
    total_contact = (stats.zone_contact or 0) + (stats.outside_contact or 0)
    if total_swings == 0:
        return 0.23
    return round(1.0 - (total_contact / total_swings), 4)


def _expected_slug(stats: Any) -> float:
    """Estimate expected slugging from quality of contact metrics."""
    ev = stats.avg_exit_velo or 88.0
    hh = stats.hard_hit_pct or 0.35
    bp = stats.barrel_pct or 0.07
    return round(0.3 + (ev - 80) * 0.01 + hh * 0.5 + bp * 2.0, 4)


def _plate_discipline_index(stats: Any) -> float:
    """Composite plate discipline: high zone swing + low chase = good."""
    z_swing = stats.z_swing_pct or 0.0
    o_swing = stats.o_swing_pct or 0.0
    # Reward swinging at strikes, penalize chasing
    return round(z_swing - o_swing * 0.5, 4) if (z_swing or o_swing) else 0.0


# ---------------------------------------------------------------------------
# Game score + sklearn model factory
# ---------------------------------------------------------------------------


def get_game_score(game: Any, *, is_home: bool) -> int | None:
    """Extract score from a SportsGame for home or away team."""
    if hasattr(game, "home_score") and hasattr(game, "away_score"):
        return game.home_score if is_home else game.away_score

    raw = getattr(game, "raw_data", None) or {}
    if is_home:
        return raw.get("home_score") or raw.get("homeScore")
    return raw.get("away_score") or raw.get("awayScore")


def get_sklearn_model(algorithm: str, model_type: str, random_state: int):
    """Create sklearn model instance based on algorithm choice."""
    if algorithm == "random_forest":
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        if model_type in ("plate_appearance", "game"):
            return RandomForestClassifier(
                n_estimators=200, max_depth=6, random_state=random_state
            )
        return RandomForestRegressor(
            n_estimators=200, max_depth=6, random_state=random_state
        )

    if algorithm == "xgboost":
        try:
            from xgboost import XGBClassifier, XGBRegressor
            if model_type in ("plate_appearance", "game"):
                return XGBClassifier(
                    n_estimators=200, max_depth=5, random_state=random_state,
                    use_label_encoder=False, eval_metric="logloss",
                )
            return XGBRegressor(
                n_estimators=200, max_depth=5, random_state=random_state,
            )
        except ImportError:
            pass

    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
    if model_type in ("plate_appearance", "game"):
        return GradientBoostingClassifier(
            n_estimators=100, max_depth=5, random_state=random_state,
        )
    return GradientBoostingRegressor(
        n_estimators=100, max_depth=4, random_state=random_state,
    )
