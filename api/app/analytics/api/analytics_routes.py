"""Analytics API — assembles sub-routers into one prefix.

All endpoints live under ``/api/analytics``. Route implementations
are split across sub-modules for maintainability:

- ``_calibration_routes`` — prediction outcomes, calibration, degradation alerts
- ``_feature_routes`` — feature loadout CRUD, available features
- ``_pipeline_routes`` — training, backtest, batch simulation jobs
- ``_model_routes`` — model registry, inference, ensemble config
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.analytics.core.simulation_cache import SimulationCache
from app.analytics.services.analytics_service import AnalyticsService

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


@router.get("/team")
async def get_team_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb)"),
    team_id: str = Query(..., description="Team identifier"),
) -> dict[str, Any]:
    """Get analytical profile for a team."""
    profile = _service.get_team_analysis(sport, team_id)
    return {
        "sport": profile.sport,
        "team_id": profile.team_id,
        "name": profile.name,
        "metrics": profile.metrics,
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
    entity_a: str = Query(..., description="First entity identifier"),
    entity_b: str = Query(..., description="Second entity identifier"),
) -> dict[str, Any]:
    """Get head-to-head matchup analysis."""
    profile = _service.get_matchup_analysis(sport, entity_a, entity_b)
    return {
        "sport": profile.sport,
        "entity_a": profile.entity_a_id,
        "entity_b": profile.entity_b_id,
        "probabilities": profile.probabilities,
        "comparison": profile.comparison,
        "advantages": profile.advantages,
    }


@router.post("/simulate")
async def post_simulate(req: SimulateRequest) -> dict[str, Any]:
    """Run a full Monte Carlo simulation with analysis."""
    game_context: dict[str, Any] = {
        "home_team": req.home_team,
        "away_team": req.away_team,
    }

    if req.home_probabilities:
        game_context["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        game_context["away_probabilities"] = req.away_probabilities
    if req.probability_mode:
        game_context["probability_mode"] = req.probability_mode

    result = _service.run_full_simulation(
        sport=req.sport,
        game_context=game_context,
        iterations=req.iterations,
        seed=req.seed,
        sportsbook=req.sportsbook,
    )

    response = {
        "sport": req.sport,
        "home_team": req.home_team,
        "away_team": req.away_team,
        **result,
    }

    return response


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
