"""Private helpers for Monte Carlo simulation endpoints.

Extracted from ``analytics_routes.py`` to keep the route module focused on
HTTP concerns.  All functions here are pure logic or DB lookups — they never
reference the FastAPI ``router``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.services.profile_service import (
    get_pitcher_rolling_profile,
    get_player_rolling_profile,
    get_team_info,
)

if TYPE_CHECKING:
    from .analytics_routes import SimulateRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reliever-as-starter regression
# ---------------------------------------------------------------------------

# Pitchers with avg IP below this threshold get regressed toward league avg.
# A full-time starter (5+ IP avg) uses their actual profile; a reliever with
# 1 avg IP gets ~80% league average because their extreme per-inning rates
# (high K, low BB) aren't sustainable over a full start.
_STARTER_IP_THRESHOLD = 5.0

_LEAGUE_AVG_PITCHER: dict[str, float] = {
    "strikeout_rate": 0.22,
    "walk_rate": 0.08,
    "contact_suppression": 0.0,
    "power_suppression": 0.0,
}


def _regress_pitcher_profile(
    profile: dict[str, float],
    avg_ip: float | None,
) -> dict[str, float]:
    """Regress a pitcher's profile toward league average based on avg IP.

    Relievers pitch short stints at max effort — their per-inning rates
    can't be sustained over a full start.  This blends their profile with
    league average proportionally to how many innings they typically throw.
    """
    if avg_ip is None or avg_ip >= _STARTER_IP_THRESHOLD:
        return profile  # Starter — use actual profile

    blend = max(avg_ip / _STARTER_IP_THRESHOLD, 0.1)  # floor at 10%
    regressed: dict[str, float] = {}
    for key in profile:
        league_val = _LEAGUE_AVG_PITCHER.get(key, 0.0)
        regressed[key] = round(league_val + blend * (profile[key] - league_val), 4)
    return regressed


def _pitching_metrics_from_profile(
    team_profile: dict[str, float] | None,
) -> dict[str, float] | None:
    """Derive mild bullpen adjustments from a team's batting profile.

    The previous implementation tried to invert batting stats into pitcher
    metrics, producing nonsensical values (e.g., -90% power suppression).

    Now: use league-average pitcher baselines with small nudges based on
    the team's own offensive tendencies as a proxy for pitching staff
    quality.  Teams that strike out a lot tend to have pitchers with
    higher K rates; teams with low barrel rates tend to suppress power.

    The adjustments are deliberately small (clamped to +-0.05) because
    batting stats are a weak proxy for pitching ability.
    """
    if not team_profile:
        return None
    whiff = team_profile.get("whiff_rate")
    contact = team_profile.get("contact_rate")
    if whiff is None and contact is None:
        return None

    # Small offsets from league average, clamped to avoid extreme values
    k_offset = min(max((whiff or 0.23) - 0.23, -0.05), 0.05)
    bb_offset = min(max(0.08 - (team_profile.get("plate_discipline_index", 0.52) - 0.52) * 0.1, -0.03), 0.03)
    contact_offset = min(max(0.77 - (contact or 0.77), -0.05), 0.05) * 0.3
    barrel = team_profile.get("barrel_rate", 0.07)
    power_offset = min(max((0.07 - barrel) / 0.07, -0.15), 0.15) * 0.3

    return {
        "strikeout_rate": round(0.22 + k_offset, 4),
        "walk_rate": round(max(0.04, min(0.12, 0.08 + bb_offset)), 4),
        "contact_suppression": round(max(-0.05, min(0.05, contact_offset)), 4),
        "power_suppression": round(max(-0.05, min(0.05, power_offset)), 4),
    }


async def _build_lineup_context(
    req: SimulateRequest,
    game_context: dict[str, Any],
    profile_meta: dict[str, Any],
    home_profile: dict[str, float] | None,
    away_profile: dict[str, float] | None,
    db: AsyncSession,
) -> bool:
    """Pre-compute per-batter probability weights for lineup simulation.

    Fetches rolling profiles for each batter and pitcher, runs them through
    ``MLBMatchup.batter_vs_pitcher()``, and packs the resulting weight arrays
    into ``game_context``.

    Returns True if lineup weights were successfully built, False otherwise.
    """
    from app.analytics.core.types import PlayerProfile
    from app.analytics.sports.mlb.game_simulator import _build_weights
    from app.analytics.sports.mlb.matchup import MLBMatchup

    matchup = MLBMatchup()

    # Resolve team IDs from abbreviations
    home_info = await get_team_info(req.home_team, db=db)
    away_info = await get_team_info(req.away_team, db=db)
    if not home_info or not away_info:
        return False

    home_team_id = home_info["id"]
    away_team_id = away_info["id"]

    # --- Fetch pitcher profiles ---
    # Away starter faces home lineup; home starter faces away lineup
    away_starter_raw = None
    home_starter_raw = None

    if req.away_starter:
        away_starter_raw = await get_pitcher_rolling_profile(
            req.away_starter.external_ref, away_team_id,
            rolling_window=req.rolling_window,
            exclude_playoffs=req.exclude_playoffs, db=db,
        )
    if req.home_starter:
        home_starter_raw = await get_pitcher_rolling_profile(
            req.home_starter.external_ref, home_team_id,
            rolling_window=req.rolling_window,
            exclude_playoffs=req.exclude_playoffs, db=db,
        )

    # Fallback pitcher profiles from team-level data
    fallback_pitcher = {"strikeout_rate": 0.22, "walk_rate": 0.08,
                        "contact_suppression": 0.0, "power_suppression": 0.0}

    # Apply reliever-as-starter regression based on avg IP
    away_sp = _regress_pitcher_profile(
        away_starter_raw or fallback_pitcher,
        req.away_starter.avg_ip if req.away_starter else None,
    )
    home_sp = _regress_pitcher_profile(
        home_starter_raw or fallback_pitcher,
        req.home_starter.avg_ip if req.home_starter else None,
    )

    # Bullpen = opposing team's pitching profile, falling back to league average.
    # Home batters face the away bullpen; away batters face the home bullpen.
    away_bullpen_metrics = _pitching_metrics_from_profile(away_profile) or fallback_pitcher
    home_bullpen_metrics = _pitching_metrics_from_profile(home_profile) or fallback_pitcher

    try:
        # --- Build per-batter weights ---
        home_starter_weights: list[list[float]] = []
        home_bullpen_weights: list[list[float]] = []
        away_starter_weights: list[list[float]] = []
        away_bullpen_weights: list[list[float]] = []

        for slot in req.home_lineup:
            batter_profile = await get_player_rolling_profile(
                slot.external_ref, home_team_id,
                rolling_window=req.rolling_window,
                exclude_playoffs=req.exclude_playoffs, db=db,
            )
            batter_metrics = batter_profile or (home_profile or {})
            batter_pp = PlayerProfile(
                player_id=slot.external_ref, sport="mlb",
                name=slot.name, metrics=batter_metrics,
            )
            # vs away starter
            pitcher_pp = PlayerProfile(
                player_id=req.away_starter.external_ref if req.away_starter else "team",
                sport="mlb", metrics=away_sp,
            )
            probs_vs_starter = matchup.batter_vs_pitcher(batter_pp, pitcher_pp)
            home_starter_weights.append(_build_weights(probs_vs_starter))
            # vs away bullpen
            bp_pp = PlayerProfile(player_id="away_bullpen", sport="mlb", metrics=away_bullpen_metrics)
            probs_vs_bp = matchup.batter_vs_pitcher(batter_pp, bp_pp)
            home_bullpen_weights.append(_build_weights(probs_vs_bp))

        for slot in req.away_lineup:
            batter_profile = await get_player_rolling_profile(
                slot.external_ref, away_team_id,
                rolling_window=req.rolling_window,
                exclude_playoffs=req.exclude_playoffs, db=db,
            )
            batter_metrics = batter_profile or (away_profile or {})
            batter_pp = PlayerProfile(
                player_id=slot.external_ref, sport="mlb",
                name=slot.name, metrics=batter_metrics,
            )
            # vs home starter
            pitcher_pp = PlayerProfile(
                player_id=req.home_starter.external_ref if req.home_starter else "team",
                sport="mlb", metrics=home_sp,
            )
            probs_vs_starter = matchup.batter_vs_pitcher(batter_pp, pitcher_pp)
            away_starter_weights.append(_build_weights(probs_vs_starter))
            # vs home bullpen
            bp_pp = PlayerProfile(player_id="home_bullpen", sport="mlb", metrics=home_bullpen_metrics)
            probs_vs_bp = matchup.batter_vs_pitcher(batter_pp, bp_pp)
            away_bullpen_weights.append(_build_weights(probs_vs_bp))

        game_context["home_lineup_weights"] = home_starter_weights
        game_context["away_lineup_weights"] = away_starter_weights
        game_context["home_bullpen_weights"] = home_bullpen_weights
        game_context["away_bullpen_weights"] = away_bullpen_weights
        game_context["starter_innings"] = req.starter_innings

        home_batters_resolved = sum(
            1 for s in req.home_lineup if s.external_ref
        )
        away_batters_resolved = sum(
            1 for s in req.away_lineup if s.external_ref
        )
        profile_meta["lineup_mode"] = {
            "enabled": True,
            "home_batters_resolved": home_batters_resolved,
            "away_batters_resolved": away_batters_resolved,
            "home_starter_resolved": home_starter_raw is not None,
            "away_starter_resolved": away_starter_raw is not None,
            "starter_innings": req.starter_innings,
        }
        profile_meta["home_pa_source"] = "lineup_batter_vs_pitcher"
        profile_meta["away_pa_source"] = "lineup_batter_vs_pitcher"

        # Attach pitcher analytics for frontend display
        profile_meta["home_pitcher"] = {
            "name": req.home_starter.name if req.home_starter else None,
            "avg_ip": req.home_starter.avg_ip if req.home_starter else None,
            "raw_profile": home_starter_raw,
            "adjusted_profile": home_sp,
            "is_regressed": (req.home_starter.avg_ip or 99) < _STARTER_IP_THRESHOLD if req.home_starter else False,
        }
        profile_meta["away_pitcher"] = {
            "name": req.away_starter.name if req.away_starter else None,
            "avg_ip": req.away_starter.avg_ip if req.away_starter else None,
            "raw_profile": away_starter_raw,
            "adjusted_profile": away_sp,
            "is_regressed": (req.away_starter.avg_ip or 99) < _STARTER_IP_THRESHOLD if req.away_starter else False,
        }
        profile_meta["home_bullpen"] = away_bullpen_metrics
        profile_meta["away_bullpen"] = home_bullpen_metrics

        logger.info(
            "lineup_weights_built",
            extra={
                "home_team": req.home_team,
                "away_team": req.away_team,
                "home_batters": len(home_starter_weights),
                "away_batters": len(away_starter_weights),
                "starter_innings": req.starter_innings,
                "home_sp_avg_ip": req.home_starter.avg_ip if req.home_starter else None,
                "away_sp_avg_ip": req.away_starter.avg_ip if req.away_starter else None,
            },
        )
        return True
    except Exception as exc:
        logger.warning(
            "lineup_weight_build_failed",
            extra={"error": str(exc)},
        )
        return False


async def _predict_with_game_model(
    sport: str,
    home_profile: dict[str, float],
    away_profile: dict[str, float],
    db: AsyncSession,
) -> float | None:
    """Run the active game model on two team profiles.

    Returns home win probability or None if no model is available.
    """
    try:
        # Find the most recent completed game model
        from sqlalchemy import select as sa_select

        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder
        from app.db.analytics import AnalyticsTrainingJob

        stmt = (
            sa_select(AnalyticsTrainingJob)
            .where(
                AnalyticsTrainingJob.status == "completed",
                AnalyticsTrainingJob.sport == sport,
                AnalyticsTrainingJob.model_type == "game",
                AnalyticsTrainingJob.model_id.isnot(None),
            )
            .order_by(AnalyticsTrainingJob.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None or not job.feature_names:
            return None

        # Build feature vector using the same builder as training
        builder = MLBFeatureBuilder()
        vec = builder.build_game_features(home_profile, away_profile)
        feature_array = vec.to_array()

        if not feature_array:
            return None

        # Try to load and predict with the actual sklearn model
        from pathlib import Path

        import joblib

        artifact_path = job.artifact_path
        if artifact_path and Path(artifact_path).exists():
            model = joblib.load(artifact_path)
            import numpy as np

            X = np.array([feature_array])
            proba = model.predict_proba(X)
            # proba[0] is [p_class_0, p_class_1]; class 1 = home_win
            classes = list(model.classes_)
            if 1 in classes:
                home_win_idx = classes.index(1)
                return round(float(proba[0][home_win_idx]), 4)

        return None
    except Exception as exc:
        logger.warning(
            "game_model_prediction_failed",
            extra={"sport": sport, "error": str(exc)},
        )
        return None
