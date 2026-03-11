"""Public MLB Game Simulator API.

Provides a simple, downstream-friendly endpoint for running Monte Carlo
game simulations between two MLB teams.  Probability mode is always
``ml`` (uses trained ML model + rolling team profiles from real Statcast
data).

Downstream apps only need:

    POST /api/simulator/mlb
    Header: X-API-Key: <your-api-key>
    Body:   { "home_team": "NYY", "away_team": "LAD" }

See the full request/response schemas below for optional parameters.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.services.profile_service import (
    get_team_rolling_profile,
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

router = APIRouter(prefix="/api/simulator", tags=["simulator"])

_service = AnalyticsService()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class MLBSimulationRequest(BaseModel):
    """Request body for ``POST /api/simulator/mlb``.

    Only ``home_team`` and ``away_team`` are required.  Everything else
    has sensible defaults.

    Example minimal request::

        {
            "home_team": "NYY",
            "away_team": "LAD"
        }

    Example full request::

        {
            "home_team": "NYY",
            "away_team": "LAD",
            "iterations": 10000,
            "rolling_window": 30,
            "seed": 42
        }
    """

    home_team: str = Field(
        ...,
        min_length=2,
        max_length=4,
        description=(
            "Home team abbreviation (e.g. NYY, LAD, HOU). "
            "Must match a team in the system with advanced stats data."
        ),
        json_schema_extra={"examples": ["NYY"]},
    )
    away_team: str = Field(
        ...,
        min_length=2,
        max_length=4,
        description=(
            "Away team abbreviation (e.g. LAD, BOS, CHC). "
            "Must match a team in the system with advanced stats data."
        ),
        json_schema_extra={"examples": ["LAD"]},
    )
    iterations: int = Field(
        5000,
        ge=100,
        le=50000,
        description=(
            "Number of Monte Carlo iterations to run. Higher values "
            "give more precise probabilities but take longer. "
            "Recommended: 5000 for quick results, 20000+ for precision."
        ),
    )
    rolling_window: int = Field(
        30,
        ge=5,
        le=162,
        description=(
            "Number of recent games to use when building each team's "
            "statistical profile. A smaller window (10–15) reacts faster "
            "to hot/cold streaks; a larger window (40–80) is more stable."
        ),
    )
    seed: int | None = Field(
        None,
        description=(
            "Optional random seed for reproducible results. "
            "Pass the same seed + inputs to get identical output."
        ),
    )


class TeamPAProbabilities(BaseModel):
    """Plate-appearance event probabilities derived from a team's rolling profile."""

    strikeout: float = Field(..., description="Probability of a strikeout per PA")
    walk: float = Field(..., description="Probability of a walk per PA")
    single: float = Field(..., description="Probability of a single per PA")
    double: float = Field(..., description="Probability of a double per PA")
    triple: float = Field(..., description="Probability of a triple per PA")
    home_run: float = Field(..., description="Probability of a home run per PA")


class ScoreFrequency(BaseModel):
    """A final score and how often it occurred in the simulation."""

    score: str = Field(..., description="Final score as 'away-home' (e.g. '3-5')")
    probability: float = Field(..., description="Fraction of simulations with this score (0–1)")


class MLBSimulationResponse(BaseModel):
    """Response from ``POST /api/simulator/mlb``.

    Contains win probabilities, expected scores, most common final
    scores, and the PA probabilities derived from each team's profile.
    """

    home_team: str = Field(..., description="Home team abbreviation")
    away_team: str = Field(..., description="Away team abbreviation")
    home_win_probability: float = Field(
        ..., description="Probability the home team wins (0–1)"
    )
    away_win_probability: float = Field(
        ..., description="Probability the away team wins (0–1)"
    )
    average_home_score: float = Field(
        ..., description="Average home team runs across all iterations"
    )
    average_away_score: float = Field(
        ..., description="Average away team runs across all iterations"
    )
    average_total: float = Field(
        ..., description="Average combined total runs"
    )
    median_total: float = Field(
        ..., description="Median combined total runs"
    )
    most_common_scores: list[ScoreFrequency] = Field(
        default_factory=list,
        description="Top 10 most frequent final scores",
    )
    iterations: int = Field(..., description="Number of Monte Carlo iterations run")
    rolling_window: int = Field(
        ..., description="Rolling window used for team profiles"
    )
    profiles_loaded: bool = Field(
        ...,
        description=(
            "Whether real team profiles were loaded from the database. "
            "If false, league-average defaults were used."
        ),
    )
    home_pa_probabilities: TeamPAProbabilities | None = Field(
        None,
        description="PA event probabilities used for the home team (from profile)",
    )
    away_pa_probabilities: TeamPAProbabilities | None = Field(
        None,
        description="PA event probabilities used for the away team (from profile)",
    )
    model_home_win_probability: float | None = Field(
        None,
        description=(
            "Win probability from the trained game model (if available). "
            "This is a direct model prediction, separate from the Monte "
            "Carlo simulation result."
        ),
    )


class MLBTeamInfo(BaseModel):
    """A team available for simulation."""

    abbreviation: str = Field(..., description="Team abbreviation (e.g. NYY)")
    name: str = Field(..., description="Full team name (e.g. New York Yankees)")
    short_name: str | None = Field(None, description="Short name (e.g. Yankees)")
    games_with_stats: int = Field(
        ...,
        description=(
            "Number of games with advanced Statcast data. "
            "Teams with 0 games will use league-average defaults."
        ),
    )


class MLBTeamsResponse(BaseModel):
    """List of MLB teams available for simulation."""

    teams: list[MLBTeamInfo] = Field(..., description="All MLB teams")
    count: int = Field(..., description="Total number of teams")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/mlb/teams",
    response_model=MLBTeamsResponse,
    summary="List MLB teams available for simulation",
    description=(
        "Returns all MLB teams with the number of games that have "
        "advanced Statcast data.  Use the ``abbreviation`` values as "
        "``home_team`` / ``away_team`` in the simulation endpoint. "
        "Teams with more ``games_with_stats`` will produce more "
        "accurate, data-driven simulations."
    ),
)
async def list_simulator_teams(
    db: AsyncSession = Depends(get_db),
) -> MLBTeamsResponse:
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
        MLBTeamInfo(
            abbreviation=row.abbreviation,
            name=row.name,
            short_name=row.short_name,
            games_with_stats=row.games_with_stats,
        )
        for row in rows
    ]
    return MLBTeamsResponse(teams=teams, count=len(teams))


@router.post(
    "/mlb",
    response_model=MLBSimulationResponse,
    summary="Run an MLB game simulation",
    description=(
        "Runs a Monte Carlo simulation for a matchup between two MLB teams.\n\n"
        "**How it works:**\n\n"
        "1. Loads each team's rolling statistical profile from real Statcast "
        "game data (barrel rate, whiff rate, contact rate, etc.).\n"
        "2. Converts profiles into plate-appearance event probabilities "
        "(strikeout, walk, single, double, triple, home run).\n"
        "3. Simulates the game plate-appearance by plate-appearance for "
        "the requested number of iterations.\n"
        "4. Aggregates results into win probabilities, expected scores, "
        "and most common final scores.\n\n"
        "**Probability mode** is always ML — team profiles are built from "
        "real historical data and the trained game model (if available) "
        "provides an additional win probability estimate.\n\n"
        "**Quick start:**\n"
        "```json\n"
        "POST /api/simulator/mlb\n"
        "{\n"
        '    "home_team": "NYY",\n'
        '    "away_team": "LAD"\n'
        "}\n"
        "```"
    ),
)
async def simulate_mlb_game(
    req: MLBSimulationRequest,
    db: AsyncSession = Depends(get_db),
) -> MLBSimulationResponse:
    home_abbr = req.home_team.strip().upper()
    away_abbr = req.away_team.strip().upper()

    game_context: dict[str, Any] = {
        "home_team": home_abbr,
        "away_team": away_abbr,
        "probability_mode": "ml",
    }

    profiles_loaded = False
    home_pa: dict[str, float] | None = None
    away_pa: dict[str, float] | None = None
    model_wp: float | None = None

    # Build rolling team profiles from DB
    home_profile = await get_team_rolling_profile(
        home_abbr, "mlb", rolling_window=req.rolling_window, db=db,
    )
    away_profile = await get_team_rolling_profile(
        away_abbr, "mlb", rolling_window=req.rolling_window, db=db,
    )

    if home_profile and away_profile:
        profiles_loaded = True
        home_pa = profile_to_pa_probabilities(home_profile)
        away_pa = profile_to_pa_probabilities(away_profile)
        game_context["home_probabilities"] = home_pa
        game_context["away_probabilities"] = away_pa
        game_context["profiles"] = {
            "home_profile": {"metrics": home_profile},
            "away_profile": {"metrics": away_profile},
        }

        # Run trained game model if available
        model_wp = await _predict_with_game_model(
            "mlb", home_profile, away_profile, db,
        )

        logger.info(
            "simulator_profiles_loaded",
            extra={
                "home": home_abbr,
                "away": away_abbr,
                "rolling_window": req.rolling_window,
            },
        )

    # Run Monte Carlo simulation
    result = _service.run_full_simulation(
        sport="mlb",
        game_context=game_context,
        iterations=req.iterations,
        seed=req.seed,
    )

    # Build typed PA probabilities for response
    home_pa_typed = _to_pa_model(home_pa) if home_pa else None
    away_pa_typed = _to_pa_model(away_pa) if away_pa else None

    return MLBSimulationResponse(
        home_team=home_abbr,
        away_team=away_abbr,
        home_win_probability=result.get("home_win_probability", 0.5),
        away_win_probability=result.get("away_win_probability", 0.5),
        average_home_score=result.get("average_home_score", 0),
        average_away_score=result.get("average_away_score", 0),
        average_total=result.get("average_total", 0),
        median_total=result.get("median_total", 0),
        most_common_scores=[
            ScoreFrequency(score=s["score"], probability=s["probability"])
            for s in result.get("most_common_scores", [])
        ],
        iterations=req.iterations,
        rolling_window=req.rolling_window,
        profiles_loaded=profiles_loaded,
        home_pa_probabilities=home_pa_typed,
        away_pa_probabilities=away_pa_typed,
        model_home_win_probability=model_wp,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_pa_model(pa: dict[str, float]) -> TeamPAProbabilities:
    """Convert raw PA probability dict to typed model."""
    return TeamPAProbabilities(
        strikeout=pa.get("strikeout_probability", 0),
        walk=pa.get("walk_probability", 0),
        single=pa.get("single_probability", 0),
        double=pa.get("double_probability", 0),
        triple=pa.get("triple_probability", 0),
        home_run=pa.get("home_run_probability", 0),
    )


async def _predict_with_game_model(
    sport: str,
    home_profile: dict[str, float],
    away_profile: dict[str, float],
    db: AsyncSession,
) -> float | None:
    """Run the active game model on two team profiles.

    Returns home win probability or ``None`` if no model is available.
    """
    try:
        from app.analytics.features.sports.mlb_features import MLBFeatureBuilder
        from app.db.analytics import AnalyticsTrainingJob
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

        builder = MLBFeatureBuilder()
        vec = builder.build_game_features(home_profile, away_profile)
        feature_array = vec.to_array()
        if not feature_array:
            return None

        import joblib
        from pathlib import Path

        artifact_path = job.artifact_path
        if artifact_path and Path(artifact_path).exists():
            model = joblib.load(artifact_path)
            import numpy as np

            X = np.array([feature_array])
            proba = model.predict_proba(X)
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
