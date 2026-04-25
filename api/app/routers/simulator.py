"""Public Game Simulator API (multi-sport).

Provides simple, downstream-friendly endpoints for running Monte Carlo
game simulations.

Sport-specific (MLB with lineup support):

    POST /api/simulator/mlb
    Header: X-API-Key: <your-api-key>
    Body:   { "home_team": "NYY", "away_team": "LAD" }

Generic multi-sport:

    POST /api/simulator/{sport}
    Header: X-API-Key: <your-api-key>
    Body:   { "home_team": "BOS", "away_team": "MIA" }

See the full request/response schemas below for optional parameters.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.api.analytics_routes import _predict_with_game_model
from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.services.profile_service import (
    get_team_rolling_profile,
    profile_to_probabilities,
)
from app.analytics.sports.team_filters import get_canonical_abbrs
from app.db import get_db

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulator", tags=["simulator"])

_service = AnalyticsService()

# Sport → (league_code, module_path, class_name) for advanced stats queries.
_SPORT_ADVANCED_STATS: dict[str, tuple[str, str, str]] = {
    "mlb": ("MLB", "app.db.mlb_advanced", "MLBGameAdvancedStats"),
    "nba": ("NBA", "app.db.nba_advanced", "NBAGameAdvancedStats"),
    "nhl": ("NHL", "app.db.nhl_advanced", "NHLGameAdvancedStats"),
    "ncaab": ("NCAAB", "app.db.ncaab_advanced", "NCAABGameAdvancedStats"),
}

_SUPPORTED_SPORTS = frozenset(_SPORT_ADVANCED_STATS.keys())


# ---------------------------------------------------------------------------
# Shared models
# ---------------------------------------------------------------------------


from app.routers.simulator_models import ScoreFrequency  # noqa: F401 — re-exported

# ---------------------------------------------------------------------------
# Generic multi-sport request / response models
# ---------------------------------------------------------------------------


class GameSimulationRequest(BaseModel):
    """Request body for ``POST /api/simulator/{sport}``.

    Only ``home_team`` and ``away_team`` are required.  Everything else
    has sensible defaults.
    """

    home_team: str = Field(
        ...,
        min_length=2,
        max_length=10,
        description="Home team abbreviation",
    )
    away_team: str = Field(
        ...,
        min_length=2,
        max_length=10,
        description="Away team abbreviation",
    )
    iterations: int = Field(
        5000,
        ge=100,
        le=50000,
        description="Monte Carlo iterations",
    )
    rolling_window: int = Field(
        30,
        ge=5,
        le=162,
        description="Recent games for team profiles",
    )
    seed: int | None = Field(None, description="Random seed for reproducibility")


class GameSimulationResponse(BaseModel):
    """Response from ``POST /api/simulator/{sport}``."""

    model_config = _ALIAS_CFG

    sport: str
    home_team: str
    away_team: str
    home_win_probability: float
    away_win_probability: float
    average_home_score: float
    average_away_score: float
    average_total: float
    most_common_scores: list[ScoreFrequency] = Field(default_factory=list)
    iterations: int
    rolling_window: int
    profiles_loaded: bool
    model_home_win_probability: float | None = None


class TeamInfo(BaseModel):
    """A team available for simulation."""

    model_config = _ALIAS_CFG

    abbreviation: str
    name: str
    short_name: str | None = None
    games_with_stats: int
    sport: str


class TeamsResponse(BaseModel):
    """List of teams available for simulation for a given sport."""

    model_config = _ALIAS_CFG

    sport: str
    teams: list[TeamInfo]
    count: int


# MLB sub-router is included before the generic {sport} routes so FastAPI
# matches POST /mlb (lineup-aware) before POST /{sport}.
from app.routers.simulator_mlb import router as _mlb_router  # noqa: E402

router.include_router(_mlb_router)


# ---------------------------------------------------------------------------
# Generic multi-sport endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{sport}/teams",
    response_model=TeamsResponse,
    summary="List teams available for simulation",
    description=(
        "Returns all teams for the specified sport with advanced stats "
        "game counts.  Supported sports: mlb, nba, nhl, ncaab."
    ),
)
async def list_sport_teams(
    sport: str,
    db: AsyncSession = Depends(get_db),
) -> TeamsResponse:
    import importlib

    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

    from app.db.sports import SportsLeague, SportsTeam

    sport_lower = sport.lower()
    config = _SPORT_ADVANCED_STATS.get(sport_lower)
    if config is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport: {sport}. Supported: {', '.join(sorted(_SUPPORTED_SPORTS))}",
        )

    league_code, model_module, model_class_name = config

    mod = importlib.import_module(model_module)
    StatsModel = getattr(mod, model_class_name)

    league_sq = (
        sa_select(SportsLeague.id)
        .where(SportsLeague.code == league_code)
        .scalar_subquery()
    )

    stmt = (
        sa_select(
            SportsTeam.id,
            SportsTeam.name,
            SportsTeam.short_name,
            SportsTeam.abbreviation,
            sa_func.count(StatsModel.id).label("games_with_stats"),
        )
        .outerjoin(StatsModel, StatsModel.team_id == SportsTeam.id)
        .where(
            SportsTeam.league_id == league_sq,
            SportsTeam.abbreviation.isnot(None),
            SportsTeam.abbreviation != "",
        )
        .group_by(SportsTeam.id)
        .order_by(SportsTeam.name)
    )

    # Filter by canonical team abbreviations to exclude cross-sport/minor-league
    # rows accidentally tagged with this league_id. NCAAB skipped (no canonical
    # list — relies on league_id alone).
    canonical_abbrs = get_canonical_abbrs(sport_lower)
    if canonical_abbrs:
        stmt = stmt.where(SportsTeam.abbreviation.in_(canonical_abbrs))

    result = await db.execute(stmt)
    rows = result.all()

    teams = [
        TeamInfo(
            abbreviation=row.abbreviation,
            name=row.name,
            short_name=row.short_name,
            games_with_stats=row.games_with_stats,
            sport=sport_lower,
        )
        for row in rows
    ]
    return TeamsResponse(sport=sport_lower, teams=teams, count=len(teams))


@router.post(
    "/{sport}",
    response_model=GameSimulationResponse,
    summary="Run a game simulation",
    description=(
        "Run a Monte Carlo simulation between two teams for any supported "
        "sport (mlb, nba, nhl, ncaab).\n\n"
        "For MLB with lineup/pitcher support, use the dedicated "
        "``POST /api/simulator/mlb`` endpoint instead."
    ),
)
async def simulate_game(
    sport: str,
    req: GameSimulationRequest,
    db: AsyncSession = Depends(get_db),
) -> GameSimulationResponse:
    sport_lower = sport.lower()
    if sport_lower not in _SUPPORTED_SPORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport: {sport}. Supported: {', '.join(sorted(_SUPPORTED_SPORTS))}",
        )

    home_abbr = req.home_team.strip().upper()
    away_abbr = req.away_team.strip().upper()

    # MLB uses ML probability mode; others use rule_based
    probability_mode = "ml" if sport_lower == "mlb" else "rule_based"

    game_context: dict[str, Any] = {
        "home_team": home_abbr,
        "away_team": away_abbr,
        "probability_mode": probability_mode,
    }

    profiles_loaded = False
    model_wp: float | None = None

    # Build rolling team profiles from DB
    home_profile_result = await get_team_rolling_profile(
        home_abbr, sport_lower, rolling_window=req.rolling_window, db=db,
    )
    away_profile_result = await get_team_rolling_profile(
        away_abbr, sport_lower, rolling_window=req.rolling_window, db=db,
    )
    home_profile = home_profile_result.metrics if home_profile_result else None
    away_profile = away_profile_result.metrics if away_profile_result else None

    if home_profile and away_profile:
        profiles_loaded = True

        # Convert profiles to sport-specific probabilities
        home_probs = profile_to_probabilities(sport_lower, home_profile)
        away_probs = profile_to_probabilities(sport_lower, away_profile)

        # For rule_based mode, pre-set probabilities in game context
        if probability_mode == "rule_based" and home_probs and away_probs:
            game_context["home_probabilities"] = home_probs
            game_context["away_probabilities"] = away_probs

        game_context["profiles"] = {
            "home_profile": {"metrics": home_profile},
            "away_profile": {"metrics": away_profile},
        }

        # Run trained game model prediction if available
        model_wp = await _predict_with_game_model(
            sport_lower, home_profile, away_profile, db,
        )

        logger.info(
            "simulator_multisport_profiles_loaded",
            extra={
                "sport": sport_lower,
                "home": home_abbr,
                "away": away_abbr,
                "rolling_window": req.rolling_window,
            },
        )

    # Run Monte Carlo simulation off the event loop. The engine is CPU-bound
    # (10k–50k iterations of pure-Python loops) and blocks the worker for
    # seconds per call; without this offload, concurrent requests serialize
    # and tail latency spikes under load.
    result = await asyncio.to_thread(
        _service.run_full_simulation,
        sport=sport_lower,
        game_context=game_context,
        iterations=req.iterations,
        seed=req.seed,
    )

    return GameSimulationResponse(
        sport=sport_lower,
        home_team=home_abbr,
        away_team=away_abbr,
        home_win_probability=result.get("home_win_probability", 0.5),
        away_win_probability=result.get("away_win_probability", 0.5),
        average_home_score=result.get("average_home_score", 0),
        average_away_score=result.get("average_away_score", 0),
        average_total=result.get("average_total", 0),
        most_common_scores=[
            ScoreFrequency(score=s["score"], probability=s["probability"])
            for s in result.get("most_common_scores", [])
        ],
        iterations=req.iterations,
        rolling_window=req.rolling_window,
        profiles_loaded=profiles_loaded,
        model_home_win_probability=model_wp,
    )
