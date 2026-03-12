"""Analytics API — assembles sub-routers into one prefix.

All endpoints live under ``/api/analytics``. Route implementations
are split across sub-modules for maintainability:

- ``_calibration_routes`` — prediction outcomes, calibration, degradation alerts
- ``_feature_routes`` — feature loadout CRUD, available features
- ``_pipeline_routes`` — training, backtest, batch simulation jobs
- ``_model_routes`` — model registry, inference, ensemble config
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.core.simulation_cache import SimulationCache
from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.services.profile_service import (
    get_pitcher_rolling_profile,
    get_player_rolling_profile,
    get_team_info,
    get_team_rolling_profile,
    get_team_roster,
    profile_to_pa_probabilities,
)
from app.db import get_db

# Canonical 30 MLB team abbreviations — excludes All-Star, minor league,
# and spring training teams that may exist in the DB under the MLB league.
_MLB_TEAM_ABBRS = frozenset({
    "ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET",
    "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SD", "SF", "SEA", "STL", "TB", "TEX", "TOR", "WSH",
})

logger = logging.getLogger(__name__)

from ._calibration_routes import router as _calibration_router
from ._feature_routes import router as _feature_router
from ._model_routes import router as _model_router
from ._pipeline_routes import router as _pipeline_router

# Re-export serializers used by tests
from ._calibration_routes import (  # noqa: F401
    _serialize_degradation_alert,
    _serialize_prediction_outcome,
)
from ._pipeline_routes import _serialize_batch_sim_job  # noqa: F401

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_service = AnalyticsService()
_cache = SimulationCache()


# ---------------------------------------------------------------------------
# Core simulation & profile endpoints (kept here — small and foundational)
# ---------------------------------------------------------------------------


class LiveSimulateRequest(BaseModel):
    """Request body for POST /api/analytics/live-simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    inning: int = Field(..., ge=1, description="Current inning")
    half: str = Field(..., description="top or bottom")
    outs: int = Field(..., ge=0, le=3, description="Current outs")
    bases: dict[str, bool] = Field(
        ..., description="Base occupancy (first, second, third)",
    )
    score: dict[str, int] = Field(
        ..., description="Current score (home, away)",
    )
    iterations: int = Field(5000, ge=100, le=50000, description="Monte Carlo iterations")
    seed: int | None = Field(None, description="Random seed for reproducibility")
    home_probabilities: dict[str, float] | None = Field(None, description="Custom home team probabilities")
    away_probabilities: dict[str, float] | None = Field(None, description="Custom away team probabilities")
    probability_mode: str | None = Field(None, description="Probability mode: rule_based, ml, ensemble")


class LineupSlot(BaseModel):
    """A single batter in a lineup."""
    external_ref: str = Field(..., description="Player external reference ID")
    name: str = Field("", description="Player name (display only)")


class PitcherSlot(BaseModel):
    """A starting pitcher."""
    external_ref: str = Field(..., description="Player external reference ID")
    name: str = Field("", description="Player name (display only)")
    avg_ip: float | None = Field(None, description="Average innings pitched per appearance")


class SimulateRequest(BaseModel):
    """Request body for POST /api/analytics/simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    home_team: str = Field("", description="Home team identifier")
    away_team: str = Field("", description="Away team identifier")
    iterations: int = Field(5000, ge=100, le=50000, description="Monte Carlo iterations")
    seed: int | None = Field(None, description="Random seed for reproducibility")
    home_probabilities: dict[str, float] | None = Field(None, description="Custom home team probabilities")
    away_probabilities: dict[str, float] | None = Field(None, description="Custom away team probabilities")
    sportsbook: dict[str, Any] | None = Field(None, description="Sportsbook lines for comparison")
    probability_mode: str | None = Field(None, description="Probability mode: rule_based, ml, ensemble, pitch_level")
    rolling_window: int = Field(30, ge=5, le=162, description="Rolling window for profile building")
    # Lineup-level simulation fields (optional — None = team-level flow)
    home_lineup: list[LineupSlot] | None = Field(None, description="Home lineup (9 batters)")
    away_lineup: list[LineupSlot] | None = Field(None, description="Away lineup (9 batters)")
    home_starter: PitcherSlot | None = Field(None, description="Home starting pitcher")
    away_starter: PitcherSlot | None = Field(None, description="Away starting pitcher")
    starter_innings: float = Field(6.0, ge=4.0, le=9.0, description="Innings before bullpen takes over")
    exclude_playoffs: bool = Field(False, description="Exclude postseason games from rolling profiles")


@router.get("/team")
async def get_team_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb)"),
    team_id: str = Query(..., description="Team identifier (abbreviation, e.g., NYY)"),
    rolling_window: int = Query(30, ge=5, le=162, description="Rolling window (prior games)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get analytical profile for a team from rolling game stats."""
    team_info = await get_team_info(team_id, db=db)
    name = team_info["name"] if team_info else team_id

    profile = await get_team_rolling_profile(
        team_id, sport, rolling_window=rolling_window, db=db,
    )

    return {
        "sport": sport,
        "team_id": team_id.upper(),
        "name": name,
        "metrics": profile or {},
        "rolling_window": rolling_window,
        "games_in_profile": rolling_window if profile else 0,
    }


@router.get("/player")
async def get_player_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb)"),
    player_id: str = Query(..., description="Player identifier"),
) -> dict[str, Any]:
    """Get analytical profile for a player."""
    profile = _service.get_player_analysis(sport, player_id)
    return {
        "sport": profile.sport,
        "player_id": profile.player_id,
        "name": profile.name,
        "metrics": profile.metrics,
    }


@router.get("/matchup")
async def get_matchup_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb)"),
    entity_a: str = Query(..., description="First team abbreviation"),
    entity_b: str = Query(..., description="Second team abbreviation"),
    rolling_window: int = Query(30, ge=5, le=162),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get head-to-head matchup analysis from rolling profiles."""
    profile_a = await get_team_rolling_profile(
        entity_a, sport, rolling_window=rolling_window, db=db,
    )
    profile_b = await get_team_rolling_profile(
        entity_b, sport, rolling_window=rolling_window, db=db,
    )

    comparison: dict[str, Any] = {}
    advantages: dict[str, str] = {}

    if profile_a and profile_b:
        # Compare key metrics
        for key in ["contact_rate", "power_index", "barrel_rate", "whiff_rate",
                     "hard_hit_rate", "plate_discipline_index", "avg_exit_velo"]:
            a_val = profile_a.get(key, 0)
            b_val = profile_b.get(key, 0)
            comparison[key] = {entity_a.upper(): round(a_val, 4), entity_b.upper(): round(b_val, 4)}
            # Lower whiff is better; higher everything else is better
            if key == "whiff_rate":
                advantages[key] = entity_a.upper() if a_val < b_val else entity_b.upper()
            else:
                advantages[key] = entity_a.upper() if a_val > b_val else entity_b.upper()

    return {
        "sport": sport,
        "entity_a": entity_a.upper(),
        "entity_b": entity_b.upper(),
        "profile_a": profile_a or {},
        "profile_b": profile_b or {},
        "comparison": comparison,
        "advantages": advantages,
    }


@router.post("/simulate")
async def post_simulate(
    req: SimulateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run a full Monte Carlo simulation with analysis.

    When teams are specified and probability_mode is ``"ml"``, builds
    rolling profiles from the database and uses them to differentiate
    each team's plate-appearance probabilities. Also runs the trained
    game model (if active) for a model-predicted win probability.
    """
    game_context: dict[str, Any] = {
        "home_team": req.home_team,
        "away_team": req.away_team,
    }

    profile_meta: dict[str, Any] = {}

    # Build team profiles from DB when teams are provided
    home_profile = None
    away_profile = None
    if req.home_team and req.away_team:
        home_profile = await get_team_rolling_profile(
            req.home_team, req.sport,
            rolling_window=req.rolling_window,
            exclude_playoffs=req.exclude_playoffs, db=db,
        )
        away_profile = await get_team_rolling_profile(
            req.away_team, req.sport,
            rolling_window=req.rolling_window,
            exclude_playoffs=req.exclude_playoffs, db=db,
        )

        if home_profile and away_profile:
            profile_meta["has_profiles"] = True
            profile_meta["rolling_window"] = req.rolling_window

            # Convert profiles to PA probabilities for the simulator
            if not req.home_probabilities:
                game_context["home_probabilities"] = profile_to_pa_probabilities(
                    home_profile
                )
                profile_meta["home_pa_source"] = "team_profile"
            if not req.away_probabilities:
                game_context["away_probabilities"] = profile_to_pa_probabilities(
                    away_profile
                )
                profile_meta["away_pa_source"] = "team_profile"

            # Attach profiles for ML model if using ml/ensemble mode
            game_context["profiles"] = {
                "home_profile": {"metrics": home_profile},
                "away_profile": {"metrics": away_profile},
            }

            # Run game model prediction if available
            model_prediction = await _predict_with_game_model(
                req.sport, home_profile, away_profile, db,
            )
            if model_prediction is not None:
                profile_meta["model_win_probability"] = model_prediction
                profile_meta["model_prediction_source"] = "game_model"

            logger.info(
                "simulation_profiles_loaded",
                extra={
                    "home": req.home_team,
                    "away": req.away_team,
                    "home_barrel": home_profile.get("barrel_rate"),
                    "away_barrel": away_profile.get("barrel_rate"),
                    "home_whiff": home_profile.get("whiff_rate"),
                    "away_whiff": away_profile.get("whiff_rate"),
                },
            )
        else:
            profile_meta["has_profiles"] = False
            profile_meta["home_found"] = home_profile is not None
            profile_meta["away_found"] = away_profile is not None

    if req.home_probabilities:
        game_context["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        game_context["away_probabilities"] = req.away_probabilities
    if req.probability_mode:
        game_context["probability_mode"] = req.probability_mode

    # --- Lineup-level orchestration ---
    lineup_mode = False
    if req.home_lineup and req.away_lineup and len(req.home_lineup) == 9 and len(req.away_lineup) == 9:
        lineup_mode = await _build_lineup_context(
            req, game_context, profile_meta, home_profile, away_profile, db,
        )

    result = _service.run_full_simulation(
        sport=req.sport,
        game_context=game_context,
        iterations=req.iterations,
        seed=req.seed,
        sportsbook=req.sportsbook,
        use_lineup=lineup_mode,
    )

    response = {
        "sport": req.sport,
        "home_team": req.home_team,
        "away_team": req.away_team,
        **result,
    }

    # Merge profile metadata into response
    if profile_meta:
        response["profile_meta"] = profile_meta
        # Surface model prediction alongside simulation
        if "model_win_probability" in profile_meta:
            response["model_home_win_probability"] = profile_meta["model_win_probability"]

    # Include PA probabilities used for transparency
    if "home_probabilities" in game_context and profile_meta.get("has_profiles"):
        response["home_pa_probabilities"] = game_context["home_probabilities"]
        response["away_pa_probabilities"] = game_context.get("away_probabilities")

    return response


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
    """Derive pitcher-shaped metrics from a team's rolling profile.

    Maps team batting metrics to the opposing pitcher's perspective so
    that bullpen weights reflect the actual team pitching tendencies
    rather than a generic league-average fallback.
    """
    if not team_profile:
        return None
    whiff = team_profile.get("whiff_rate")
    contact = team_profile.get("contact_rate")
    if whiff is None and contact is None:
        return None
    return {
        "strikeout_rate": whiff if whiff is not None else 0.22,
        "walk_rate": 1.0 - team_profile.get("plate_discipline_index", 0.52) if "plate_discipline_index" in team_profile else 0.08,
        "contact_suppression": round(1.0 - (contact or 0.77) - 0.23, 4),
        "power_suppression": round(1.0 - (team_profile.get("barrel_rate", 0.07) / 0.07), 4) if team_profile.get("barrel_rate") else 0.0,
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

        profile_meta["lineup_mode"] = True
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
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder
        from app.db.analytics import AnalyticsTrainingJob

        # Find the most recent completed game model
        from sqlalchemy import select as sa_select

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
        import joblib
        from pathlib import Path

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


@router.get("/mlb-teams")
async def get_mlb_teams(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List MLB teams with count of games that have advanced stats data.

    Used by the simulator UI to populate team dropdowns. Only returns
    teams that have an abbreviation set.
    """
    from sqlalchemy import func as sa_func, select as sa_select

    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsTeam

    stmt = (
        sa_select(
            SportsTeam.id,
            SportsTeam.name,
            SportsTeam.short_name,
            SportsTeam.abbreviation,
            sa_func.count(MLBGameAdvancedStats.id).label("games_with_stats"),
        )
        .outerjoin(
            MLBGameAdvancedStats,
            MLBGameAdvancedStats.team_id == SportsTeam.id,
        )
        .where(SportsTeam.abbreviation.in_(_MLB_TEAM_ABBRS))
        .group_by(SportsTeam.id)
        .order_by(SportsTeam.name)
    )
    result = await db.execute(stmt)
    rows = result.all()

    teams = [
        {
            "id": row.id,
            "name": row.name,
            "short_name": row.short_name,
            "abbreviation": row.abbreviation,
            "games_with_stats": row.games_with_stats,
        }
        for row in rows
    ]
    return {"teams": teams, "count": len(teams)}


@router.get("/mlb-roster")
async def get_mlb_roster(
    team: str = Query(..., description="Team abbreviation (e.g., NYY)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get recent roster for an MLB team (batters + pitchers).

    Used by the simulator UI to populate lineup and pitcher selectors.
    """
    roster = await get_team_roster(team, db=db)
    if roster is None:
        return {"error": f"Team not found: {team}", "batters": [], "pitchers": []}
    return roster


@router.post("/live-simulate")
async def post_live_simulate(req: LiveSimulateRequest) -> dict[str, Any]:
    """Run a simulation from a live game state."""
    game_state: dict[str, Any] = {
        "inning": req.inning,
        "half": req.half,
        "outs": req.outs,
        "bases": req.bases,
        "score": req.score,
    }

    if req.home_probabilities:
        game_state["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        game_state["away_probabilities"] = req.away_probabilities
    if req.probability_mode:
        game_state["probability_mode"] = req.probability_mode

    result = _service.run_live_simulation(
        sport=req.sport,
        game_state=game_state,
        iterations=req.iterations,
        seed=req.seed,
    )

    return {"sport": req.sport, **result}


# ---------------------------------------------------------------------------
# Include sub-routers
# ---------------------------------------------------------------------------

router.include_router(_calibration_router)
router.include_router(_feature_router)
router.include_router(_pipeline_router)
router.include_router(_model_router)
