"""Analytics API endpoints.

Provides REST endpoints for team analysis, player analysis, matchup
comparison, and game simulation. All endpoints return structured JSON
and delegate to the AnalyticsService layer.

Routes:
    GET  /api/analytics/team          — Team analytical profile
    GET  /api/analytics/player        — Player analytical profile
    GET  /api/analytics/matchup       — Head-to-head matchup analysis
    GET  /api/analytics/simulation    — Game simulation results (legacy)
    POST /api/analytics/simulate      — Full Monte Carlo simulation
    POST /api/analytics/live-simulate — Live game simulation from state
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.analytics.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_service = AnalyticsService()


class LiveSimulateRequest(BaseModel):
    """Request body for POST /api/analytics/live-simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    inning: int = Field(1, ge=1, le=20, description="Current inning")
    half: str = Field("top", description="top or bottom")
    outs: int = Field(0, ge=0, le=2, description="Current outs")
    bases: dict[str, bool] = Field(
        default_factory=lambda: {"first": False, "second": False, "third": False},
        description="Base runner state",
    )
    score: dict[str, int] = Field(
        default_factory=lambda: {"home": 0, "away": 0},
        description="Current score",
    )
    iterations: int = Field(2000, ge=1, le=50000, description="Simulation iterations")
    seed: int | None = Field(None, description="Optional seed for determinism")
    home_probabilities: dict[str, float] | None = Field(
        None, description="Custom home team probability distribution",
    )
    away_probabilities: dict[str, float] | None = Field(
        None, description="Custom away team probability distribution",
    )


class SimulateRequest(BaseModel):
    """Request body for POST /api/analytics/simulate."""
    sport: str = Field(..., description="Sport code (e.g., mlb)")
    home_team: str = Field(..., description="Home team identifier")
    away_team: str = Field(..., description="Away team identifier")
    iterations: int = Field(5000, ge=1, le=100000, description="Simulation iterations")
    seed: int | None = Field(None, description="Optional seed for determinism")
    home_probabilities: dict[str, float] | None = Field(
        None, description="Custom home team probability distribution",
    )
    away_probabilities: dict[str, float] | None = Field(
        None, description="Custom away team probability distribution",
    )
    sportsbook: dict[str, Any] | None = Field(
        None, description="Optional sportsbook lines for comparison",
    )


@router.get("/team")
async def get_team_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
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
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
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
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
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


@router.get("/simulation")
async def get_simulation(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    iterations: int = Query(1000, ge=1, le=100000, description="Simulation iterations"),
) -> dict[str, Any]:
    """Run a game simulation and return results (legacy endpoint)."""
    result = _service.run_simulation(sport, game_context={}, iterations=iterations)
    return {
        "sport": result.sport,
        "iterations": result.iterations,
        "summary": result.summary,
    }


@router.post("/simulate")
async def post_simulate(req: SimulateRequest) -> dict[str, Any]:
    """Run a full Monte Carlo simulation with analysis.

    Accepts team identifiers and optional custom probability
    distributions. Returns win probabilities, score distributions,
    and optional sportsbook comparison.
    """
    game_context: dict[str, Any] = {
        "home_team": req.home_team,
        "away_team": req.away_team,
    }

    if req.home_probabilities:
        game_context["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        game_context["away_probabilities"] = req.away_probabilities

    result = _service.run_full_simulation(
        sport=req.sport,
        game_context=game_context,
        iterations=req.iterations,
        seed=req.seed,
        sportsbook=req.sportsbook,
    )

    return {
        "sport": req.sport,
        "home_team": req.home_team,
        "away_team": req.away_team,
        **result,
    }


@router.post("/live-simulate")
async def post_live_simulate(req: LiveSimulateRequest) -> dict[str, Any]:
    """Run a simulation from a live game state.

    Accepts current inning, outs, base runners, and score. Returns
    win probabilities and expected final score.
    """
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

    result = _service.run_live_simulation(
        sport=req.sport,
        game_state=game_state,
        iterations=req.iterations,
        seed=req.seed,
    )

    return {"sport": req.sport, **result}
