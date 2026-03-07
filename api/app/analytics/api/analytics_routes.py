"""Analytics API endpoints.

Provides REST endpoints for team analysis, player analysis, matchup
comparison, and game simulation. All endpoints return structured JSON
and delegate to the AnalyticsService layer.

Routes:
    GET /api/analytics/team       — Team analytical profile
    GET /api/analytics/player     — Player analytical profile
    GET /api/analytics/matchup    — Head-to-head matchup analysis
    GET /api/analytics/simulation — Game simulation results
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Query

from app.analytics.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_service = AnalyticsService()


@router.get("/team")
async def get_team_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    team_id: str = Query(..., description="Team identifier"),
) -> dict[str, Any]:
    """Get analytical profile for a team."""
    profile = _service.get_team_analysis(sport, team_id)
    return {
        "status": "analytics framework initialized",
        "sport": profile.sport,
        "team_id": profile.team_id,
        "data": asdict(profile),
    }


@router.get("/player")
async def get_player_analytics(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    player_id: str = Query(..., description="Player identifier"),
) -> dict[str, Any]:
    """Get analytical profile for a player."""
    profile = _service.get_player_analysis(sport, player_id)
    return {
        "status": "analytics framework initialized",
        "sport": profile.sport,
        "player_id": profile.player_id,
        "data": asdict(profile),
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
        "status": "analytics framework initialized",
        "sport": profile.sport,
        "entity_a": profile.entity_a_id,
        "entity_b": profile.entity_b_id,
        "data": asdict(profile),
    }


@router.get("/simulation")
async def get_simulation(
    sport: str = Query(..., description="Sport code (e.g., mlb, nba)"),
    iterations: int = Query(1000, ge=1, le=100000, description="Simulation iterations"),
) -> dict[str, Any]:
    """Run a game simulation and return results."""
    result = _service.run_simulation(sport, game_context={}, iterations=iterations)
    return {
        "status": "analytics framework initialized",
        "sport": result.sport,
        "iterations": result.iterations,
        "data": asdict(result),
    }
