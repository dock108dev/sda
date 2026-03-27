"""Analytics API — assembles sub-routers into one prefix.

All endpoints live under ``/api/analytics``. Route implementations
are split across sub-modules for maintainability:

- ``_calibration_routes`` — prediction outcomes, calibration, degradation alerts
- ``_feature_routes`` — feature loadout CRUD, available features
- ``_pipeline_routes`` — training, batch simulation jobs
- ``_backtest_routes`` — backtest jobs
- ``_experiment_routes`` — experiment suites, historical replay, MLB data coverage
- ``_model_routes`` — model registry, inference, ensemble config
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.services.profile_service import (
    ProfileResult,
    get_team_rolling_profile,
    get_team_roster,
    profile_to_pa_probabilities,
    profile_to_probabilities,
)
from app.db import get_db

from ._simulation_helpers import _build_lineup_context, _predict_with_game_model

from app.analytics.sports.mlb.constants import MLB_TEAM_ABBRS as _MLB_TEAM_ABBRS

logger = logging.getLogger(__name__)

# Re-export serializers used by tests
from ._calibration_routes import (  # noqa: F401
    _serialize_degradation_alert,
    _serialize_prediction_outcome,
)
from ._backtest_routes import router as _backtest_router
from ._calibration_routes import router as _calibration_router
from ._experiment_routes import router as _experiment_router
from ._feature_routes import router as _feature_router
from ._model_routes import router as _model_router
from ._game_theory_routes import router as _game_theory_router
from ._pipeline_routes import _serialize_batch_sim_job  # noqa: F401
from ._pipeline_routes import router as _pipeline_router

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_service = AnalyticsService()


# ---------------------------------------------------------------------------
# Core simulation & profile endpoints (kept here — small and foundational)
# ---------------------------------------------------------------------------


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
    model_id: str | None = Field(None, description="Specific model ID to use instead of the active model")


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
    home_profile: dict[str, float] | None = None
    away_profile: dict[str, float] | None = None
    home_profile_result: ProfileResult | None = None
    away_profile_result: ProfileResult | None = None

    if req.home_team and req.away_team:
        home_profile_result = await get_team_rolling_profile(
            req.home_team, req.sport,
            rolling_window=req.rolling_window,
            exclude_playoffs=req.exclude_playoffs, db=db,
        )
        away_profile_result = await get_team_rolling_profile(
            req.away_team, req.sport,
            rolling_window=req.rolling_window,
            exclude_playoffs=req.exclude_playoffs, db=db,
        )
        home_profile = home_profile_result.metrics if home_profile_result else None
        away_profile = away_profile_result.metrics if away_profile_result else None

        if home_profile and away_profile:
            profile_meta["has_profiles"] = True
            profile_meta["rolling_window"] = req.rolling_window

            # Always compute profile-derived PA probs (for display),
            # but only use them as simulator input for rule_based / unspecified modes.
            profile_home_pa = profile_to_probabilities(req.sport, home_profile)
            profile_away_pa = profile_to_probabilities(req.sport, away_profile)
            profile_meta["profile_pa_probabilities"] = {
                "home": profile_home_pa,
                "away": profile_away_pa,
            }

            # Only pre-populate game_context PA probs when the mode is
            # rule_based or unspecified.  For ml / ensemble the resolver
            # will overwrite these — this fixes the priority bug where
            # profile-derived PA probs shadowed resolver output.
            effective_mode = req.probability_mode or "rule_based"
            if effective_mode == "rule_based":
                if not req.home_probabilities:
                    game_context["home_probabilities"] = profile_home_pa
                    profile_meta["home_pa_source"] = "team_profile"
                if not req.away_probabilities:
                    game_context["away_probabilities"] = profile_away_pa
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

            # Thread data freshness into profile_meta
            profile_meta["data_freshness"] = {
                "home": {
                    "games_used": home_profile_result.games_used,
                    "newest_game": home_profile_result.date_range[1],
                    "oldest_game": home_profile_result.date_range[0],
                },
                "away": {
                    "games_used": away_profile_result.games_used,
                    "newest_game": away_profile_result.date_range[1],
                    "oldest_game": away_profile_result.date_range[0],
                },
            }

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
            profile_meta["home_found"] = home_profile_result is not None
            profile_meta["away_found"] = away_profile_result is not None

    if req.home_probabilities:
        game_context["home_probabilities"] = req.home_probabilities
    if req.away_probabilities:
        game_context["away_probabilities"] = req.away_probabilities
    if req.probability_mode:
        game_context["probability_mode"] = req.probability_mode
    if req.model_id:
        game_context["_model_id"] = req.model_id

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

    # Thread raw profiles and baselines into profile_meta for edge analysis
    if home_profile and away_profile:
        import importlib as _importlib
        baselines_config = _SPORT_BASELINES.get(req.sport.lower(), _SPORT_BASELINES["mlb"])
        baselines_mod = _importlib.import_module(baselines_config[0])
        sport_baselines = getattr(baselines_mod, baselines_config[1])
        profile_meta["home_profile"] = home_profile
        profile_meta["away_profile"] = away_profile
        profile_meta["baselines"] = {k: v for k, v in sport_baselines.items() if k in home_profile}

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

    # Surface simulation diagnostics (mode, model info)
    diagnostics = result.get("_diagnostics")
    if diagnostics is not None:
        response["simulation_info"] = diagnostics.to_dict()
        # Clean up internal key
        response.pop("_diagnostics", None)

    # Bundle both prediction systems: MC simulation + trained classifier
    predictions: dict[str, Any] = {
        "monte_carlo": {
            "home_win_probability": response.get("home_win_probability"),
            "method": "plate-appearance Monte Carlo simulation",
            "probability_inputs": response.get("simulation_info", {}).get("executed_mode", "default")
                if "simulation_info" in response else
                result.get("probability_source", "default"),
        },
    }
    model_wp = profile_meta.get("model_win_probability")
    if model_wp is not None:
        predictions["game_model"] = {
            "home_win_probability": model_wp,
            "method": "trained classifier on team profile features",
        }
    response["predictions"] = predictions

    # Include event summary and sanity warnings when available
    if "event_summary" in result:
        response["event_summary"] = result["event_summary"]
        from app.analytics.core.simulation_analysis import check_simulation_sanity
        warnings = check_simulation_sanity(result["event_summary"])
        if warnings:
            response.setdefault("simulation_info", {})
            if isinstance(response["simulation_info"], dict):
                response["simulation_info"]["sanity_warnings"] = warnings

    return response


@router.get("/team-profile")
async def get_team_profile(
    team: str = Query(..., description="Team abbreviation (e.g., NYY)"),
    sport: str = Query("mlb", description="Sport code (e.g., mlb, nba, nhl, ncaab)"),
    rolling_window: int = Query(30, ge=5, le=162, description="Rolling window for profile building"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a team's rolling profile with league baselines for comparison."""
    import importlib

    sport_lower = sport.lower()
    baselines_config = _SPORT_BASELINES.get(sport_lower, _SPORT_BASELINES["mlb"])
    baselines_mod = importlib.import_module(baselines_config[0])
    sport_baselines = getattr(baselines_mod, baselines_config[1])

    profile_result = await get_team_rolling_profile(
        team, sport_lower, rolling_window=rolling_window, db=db,
    )
    if profile_result is None:
        return {"error": f"No profile data found for {team}", "team": team, "games_used": 0,
                "date_range": [None, None], "season_breakdown": {}, "metrics": {}, "baselines": {}}

    metrics = profile_result.metrics
    baselines = {k: v for k, v in sport_baselines.items() if k in metrics}

    return {
        "team": team,
        "games_used": profile_result.games_used,
        "date_range": list(profile_result.date_range),
        "season_breakdown": {str(k): v for k, v in profile_result.season_breakdown.items()},
        "metrics": metrics,
        "baselines": baselines,
    }


# ---------------------------------------------------------------------------
# Sport-aware lookup tables (multi-sport support)
# ---------------------------------------------------------------------------

_SPORT_ADVANCED_STATS: dict[str, tuple[str, str, str]] = {
    "mlb": ("MLB", "app.db.mlb_advanced", "MLBGameAdvancedStats"),
    "nba": ("NBA", "app.db.nba_advanced", "NBAGameAdvancedStats"),
    "nhl": ("NHL", "app.db.nhl_advanced", "NHLGameAdvancedStats"),
    "ncaab": ("NCAAB", "app.db.ncaab_advanced", "NCAABGameAdvancedStats"),
}

_SPORT_BASELINES: dict[str, tuple[str, str]] = {
    "mlb": ("app.analytics.sports.mlb.constants", "FEATURE_BASELINES"),
    "nba": ("app.analytics.sports.nba.constants", "FEATURE_BASELINES"),
    "nhl": ("app.analytics.sports.nhl.constants", "FEATURE_BASELINES"),
    "ncaab": ("app.analytics.sports.ncaab.constants", "FEATURE_BASELINES"),
}


@router.get("/{sport}/teams")
async def get_sport_teams(
    sport: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List teams for any sport with count of games that have advanced stats."""
    import importlib

    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

    from app.db.sports import SportsLeague, SportsTeam

    sport_lower = sport.lower()
    config = _SPORT_ADVANCED_STATS.get(sport_lower)
    if config is None:
        return {"error": f"Unsupported sport: {sport}", "teams": [], "count": 0}

    league_code, model_module, model_class_name = config

    mod = importlib.import_module(model_module)
    StatsModel = getattr(mod, model_class_name)

    league_sq = sa_select(SportsLeague.id).where(SportsLeague.code == league_code).scalar_subquery()

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
        .having(sa_func.count(StatsModel.id) > 0)
        .order_by(SportsTeam.name)
    )

    # For MLB, also filter by canonical team abbrs
    if sport_lower == "mlb":
        stmt = stmt.where(SportsTeam.abbreviation.in_(_MLB_TEAM_ABBRS))

    result = await db.execute(stmt)
    rows = result.all()
    teams = [
        {
            "id": r.id,
            "name": r.name,
            "short_name": r.short_name,
            "abbreviation": r.abbreviation,
            "games_with_stats": r.games_with_stats,
        }
        for r in rows
    ]
    return {"teams": teams, "count": len(teams)}


@router.get("/mlb-teams")
async def get_mlb_teams(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List MLB teams with count of games that have advanced stats data.

    Used by the simulator UI to populate team dropdowns. Only returns
    teams that have an abbreviation set.
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy import select as sa_select

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


# ---------------------------------------------------------------------------
# Include sub-routers
# ---------------------------------------------------------------------------

router.include_router(_backtest_router)
router.include_router(_calibration_router)
router.include_router(_experiment_router)
router.include_router(_feature_router)
router.include_router(_pipeline_router)
router.include_router(_model_router)
router.include_router(_game_theory_router)
