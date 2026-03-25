"""MLB-specific simulator endpoints with lineup support.

These endpoints provide the full MLB simulation experience including
per-batter matchup probabilities, starting pitcher analysis, and
bullpen transition modeling.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.api.analytics_routes import _predict_with_game_model
from app.analytics.services.analytics_service import AnalyticsService
from app.analytics.services.profile_service import (
    get_pitcher_rolling_profile,
    get_player_rolling_profile,
    get_team_info,
    get_team_rolling_profile,
    profile_to_pa_probabilities,
)
from app.db import get_db

from app.analytics.sports.mlb.constants import MLB_TEAM_ABBRS as _MLB_TEAM_ABBRS
from app.routers.simulator_models import ScoreFrequency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["simulator"])

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
    home_lineup: list[str] | None = Field(
        None,
        min_length=1,
        max_length=9,
        description=(
            "Optional home batting lineup: list of player external_ref IDs "
            "in batting order. When provided, per-batter PA probabilities "
            "are computed from individual player profiles."
        ),
    )
    away_lineup: list[str] | None = Field(
        None,
        min_length=1,
        max_length=9,
        description=(
            "Optional away batting lineup: list of player external_ref IDs "
            "in batting order."
        ),
    )
    home_starter: str | None = Field(
        None,
        description="Home starting pitcher external_ref ID for matchup computation.",
    )
    away_starter: str | None = Field(
        None,
        description="Away starting pitcher external_ref ID for matchup computation.",
    )
    starter_innings: float = Field(
        6.0,
        ge=1.0,
        le=9.0,
        description="Innings the starter pitches before bullpen takes over.",
    )


class TeamPAProbabilities(BaseModel):
    """Plate-appearance event probabilities derived from a team's rolling profile."""

    strikeout: float = Field(..., description="Probability of a strikeout per PA")
    walk: float = Field(..., description="Probability of a walk per PA")
    single: float = Field(..., description="Probability of a single per PA")
    double: float = Field(..., description="Probability of a double per PA")
    triple: float = Field(..., description="Probability of a triple per PA")
    home_run: float = Field(..., description="Probability of a home run per PA")


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

    # Resolve team IDs for lineup support
    home_team_info = await get_team_info(home_abbr, db=db)
    away_team_info = await get_team_info(away_abbr, db=db)
    home_team_id = home_team_info["id"] if home_team_info else None
    away_team_id = away_team_info["id"] if away_team_info else None

    # Build rolling team profiles from DB
    home_profile_result = await get_team_rolling_profile(
        home_abbr, "mlb", rolling_window=req.rolling_window, db=db,
    )
    away_profile_result = await get_team_rolling_profile(
        away_abbr, "mlb", rolling_window=req.rolling_window, db=db,
    )
    home_profile = home_profile_result.metrics if home_profile_result else None
    away_profile = away_profile_result.metrics if away_profile_result else None

    if home_profile and away_profile:
        profiles_loaded = True
        home_pa = profile_to_pa_probabilities(home_profile)
        away_pa = profile_to_pa_probabilities(away_profile)
        # Do NOT pre-set game_context["home_probabilities"] — the ML
        # resolver in simulation_engine will populate these.  Pre-setting
        # would shadow the resolver output (the priority bug).
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

    # Build per-batter lineup weights when lineups are provided
    use_lineup = False
    if req.home_lineup and req.away_lineup:
        lineup_ctx = await _build_lineup_context(
            home_lineup=req.home_lineup,
            away_lineup=req.away_lineup,
            home_starter=req.home_starter,
            away_starter=req.away_starter,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            rolling_window=req.rolling_window,
            starter_innings=req.starter_innings,
            db=db,
        )
        if lineup_ctx:
            game_context.update(lineup_ctx)
            use_lineup = True

    # Run Monte Carlo simulation
    result = _service.run_full_simulation(
        sport="mlb",
        game_context=game_context,
        iterations=req.iterations,
        seed=req.seed,
        use_lineup=use_lineup,
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


async def _build_lineup_context(
    *,
    home_lineup: list[str],
    away_lineup: list[str],
    home_starter: str | None,
    away_starter: str | None,
    home_team_id: int | None,
    away_team_id: int | None,
    rolling_window: int,
    starter_innings: float,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Build per-batter weight arrays from individual player profiles.

    For each batter in the lineup, loads their rolling profile and the
    opposing starter's profile, then computes batter-vs-pitcher matchup
    probabilities. Falls back to team-level probabilities for batters
    or pitchers without sufficient data.

    Returns a dict with ``home_lineup_weights``, ``away_lineup_weights``,
    and ``starter_innings`` ready for ``simulate_game_with_lineups()``,
    or ``None`` if team IDs are unavailable.
    """
    from app.analytics.sports.mlb.constants import (
        DEFAULT_EVENT_PROBS_SUFFIXED as _DEFAULTS,
    )
    from app.analytics.sports.mlb.game_simulator import _build_weights
    from app.analytics.sports.mlb.matchup import MLBMatchup

    if home_team_id is None or away_team_id is None:
        # Resolve team IDs from abbreviations if not available
        return None

    matchup = MLBMatchup()

    # Load pitcher profiles
    home_pitcher_profile = None
    away_pitcher_profile = None
    if home_starter:
        home_pitcher_profile = await get_pitcher_rolling_profile(
            home_starter, home_team_id,
            rolling_window=rolling_window, db=db,
        )
    if away_starter:
        away_pitcher_profile = await get_pitcher_rolling_profile(
            away_starter, away_team_id,
            rolling_window=rolling_window, db=db,
        )

    async def _batter_weights(
        lineup: list[str], team_id: int, pitcher_profile: dict | None,
    ) -> list[list[float]]:
        """Build weight arrays for each batter in a lineup."""
        from app.analytics.core.types import PlayerProfile

        weights_list = []
        for batter_ref in lineup:
            batter_profile = await get_player_rolling_profile(
                batter_ref, team_id,
                rolling_window=rolling_window, db=db,
            )
            if batter_profile and pitcher_profile:
                # Full batter-vs-pitcher matchup
                bp = PlayerProfile(player_id=batter_ref, sport="mlb", metrics=batter_profile)
                pp = PlayerProfile(player_id="pitcher", sport="mlb", metrics=pitcher_profile)
                probs = matchup.batter_vs_pitcher(bp, pp)
                weights_list.append(_build_weights(probs))
            elif batter_profile:
                # Batter profile only — convert to PA probs
                probs = profile_to_pa_probabilities(batter_profile)
                weights_list.append(_build_weights(probs))
            else:
                # No data — use league defaults
                weights_list.append(_build_weights(_DEFAULTS))
        # Pad to 9 if fewer batters provided
        while len(weights_list) < 9:
            weights_list.append(weights_list[-1] if weights_list else _build_weights(_DEFAULTS))
        return weights_list[:9]

    home_weights = await _batter_weights(home_lineup, home_team_id, away_pitcher_profile)
    away_weights = await _batter_weights(away_lineup, away_team_id, home_pitcher_profile)

    return {
        "home_lineup_weights": home_weights,
        "away_lineup_weights": away_weights,
        "starter_innings": starter_innings,
    }


def _to_pa_model(pa: dict[str, float]) -> TeamPAProbabilities:
    """Convert raw PA probability dict to typed model."""
    return TeamPAProbabilities(
        strikeout=pa.get("strikeout_probability", 0),
        walk=pa.get("walk_or_hbp_probability", 0),
        single=pa.get("single_probability", 0),
        double=pa.get("double_probability", 0),
        triple=pa.get("triple_probability", 0),
        home_run=pa.get("home_run_probability", 0),
    )
