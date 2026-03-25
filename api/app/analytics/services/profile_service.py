"""Multi-sport team profile service.

Builds rolling team profiles from sport-specific advanced stats
(MLB, NBA, NHL, NCAAB) and converts profiles to event probabilities
for the simulation engines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ProfileResult:
    """Rich return type for team rolling profiles.

    Wraps the raw metrics dict with freshness metadata so the caller
    can surface data-age information to the user.
    """

    metrics: dict[str, float]
    games_used: int
    date_range: tuple[str, str]  # (oldest_game_date, newest_game_date)
    season_breakdown: dict[int, int] = field(default_factory=dict)  # year -> game count

_PRIOR_SEASON_DECAY = 0.7


def _season_weights(game_dates: list[datetime]) -> list[float]:
    """Return per-game weights: 1.0 for current season, 0.7 for prior seasons.

    Current season is defined by the year of the most recent game date.
    """
    if not game_dates:
        return []
    current_year = game_dates[0].year  # most recent game (desc order)
    return [1.0 if d.year == current_year else _PRIOR_SEASON_DECAY for d in game_dates]


def _weighted_mean(values_weights: list[tuple[float, float]]) -> float:
    """Compute a weighted mean from (value, weight) pairs."""
    total_w = sum(w for _, w in values_weights)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in values_weights) / total_w


# ---------------------------------------------------------------------------
# Sport-specific stats_to_metrics helpers
# ---------------------------------------------------------------------------

def _nba_stats_to_metrics(row) -> dict[str, float]:
    """Extract NBA team advanced stats into a flat metrics dict."""
    return {k: float(v) for k, v in {
        "off_rating": row.off_rating,
        "def_rating": row.def_rating,
        "net_rating": row.net_rating,
        "pace": row.pace,
        "efg_pct": row.efg_pct,
        "ts_pct": row.ts_pct,
        "fg_pct": row.fg_pct,
        "fg3_pct": row.fg3_pct,
        "ft_pct": row.ft_pct,
        "orb_pct": row.orb_pct,
        "drb_pct": row.drb_pct,
        "reb_pct": row.reb_pct,
        "ast_pct": row.ast_pct,
        "tov_pct": row.tov_pct,
        "ft_rate": row.ft_rate,
    }.items() if v is not None}


def _nhl_stats_to_metrics(row) -> dict[str, float]:
    """Extract NHL team advanced stats into a flat metrics dict."""
    raw: dict[str, Any] = {
        "xgoals_for": row.xgoals_for,
        "xgoals_against": row.xgoals_against,
        "xgoals_pct": row.xgoals_pct,
        "corsi_pct": row.corsi_pct,
        "fenwick_pct": row.fenwick_pct,
        "shots_for": row.shots_for,
        "shots_against": row.shots_against,
        "shooting_pct": row.shooting_pct,
        "save_pct": row.save_pct,
        "pdo": row.pdo,
    }
    # Include high-danger columns if present on the model
    for col in (
        "high_danger_shots_for",
        "high_danger_goals_for",
        "high_danger_shots_against",
        "high_danger_goals_against",
    ):
        val = getattr(row, col, None)
        if val is not None:
            raw[col] = val
    return {k: float(v) for k, v in raw.items() if v is not None}


def _ncaab_stats_to_metrics(row) -> dict[str, float]:
    """Extract NCAAB team advanced stats into a flat metrics dict."""
    return {k: float(v) for k, v in {
        "off_rating": row.off_rating,
        "def_rating": row.def_rating,
        "net_rating": row.net_rating,
        "pace": row.pace,
        "off_efg_pct": row.off_efg_pct,
        "off_tov_pct": row.off_tov_pct,
        "off_orb_pct": row.off_orb_pct,
        "off_ft_rate": row.off_ft_rate,
        "def_efg_pct": row.def_efg_pct,
        "def_tov_pct": row.def_tov_pct,
        "def_orb_pct": row.def_orb_pct,
        "def_ft_rate": row.def_ft_rate,
    }.items() if v is not None}


# ---------------------------------------------------------------------------
# Sport config: (league_code, model_import_path, metrics_fn | None)
# For MLB, metrics_fn is None — we use _training_helpers.stats_to_metrics.
# ---------------------------------------------------------------------------

_SPORT_CONFIG: dict[str, tuple[str, str, str, Any]] = {
    "mlb": ("MLB", "app.db.mlb_advanced", "MLBGameAdvancedStats", None),
    "nba": ("NBA", "app.db.nba_advanced", "NBAGameAdvancedStats", _nba_stats_to_metrics),
    "nhl": ("NHL", "app.db.nhl_advanced", "NHLGameAdvancedStats", _nhl_stats_to_metrics),
    "ncaab": ("NCAAB", "app.db.ncaab_advanced", "NCAABGameAdvancedStats", _ncaab_stats_to_metrics),
}


async def get_team_rolling_profile(
    abbreviation: str,
    sport: str,
    *,
    rolling_window: int = 30,
    exclude_playoffs: bool = False,
    db: AsyncSession,
) -> ProfileResult | None:
    """Build a rolling profile for a team from recent game stats.

    Looks up the team by abbreviation, finds their last N games with
    advanced stats, and aggregates into a single profile dict whose
    keys match what the sport's feature builder and training pipeline
    expect.

    Returns a ``ProfileResult`` with metrics and freshness metadata,
    or ``None`` if the team is not found or has insufficient data.
    """
    import importlib

    config = _SPORT_CONFIG.get(sport.lower())
    if config is None:
        return None

    league_code, model_module, model_class_name, metrics_fn = config

    from app.db.sports import SportsGame, SportsLeague, SportsTeam

    # Dynamically import the advanced stats model
    mod = importlib.import_module(model_module)
    StatsModel = getattr(mod, model_class_name)

    # Resolve team ID from abbreviation — filter to correct league to avoid
    # collisions with teams sharing abbreviations across leagues.
    league_sq = (
        select(SportsLeague.id)
        .where(SportsLeague.code == league_code)
        .scalar_subquery()
    )
    team_result = await db.execute(
        select(SportsTeam)
        .where(
            SportsTeam.abbreviation == abbreviation.upper(),
            SportsTeam.league_id == league_sq,
        )
        .limit(1)
    )
    team = team_result.scalar_one_or_none()
    if team is None:
        logger.warning("team_not_found", extra={"abbreviation": abbreviation})
        return None

    # Get this team's recent game stats ordered by game date
    stmt = (
        select(StatsModel, SportsGame.game_date)
        .join(SportsGame, SportsGame.id == StatsModel.game_id)
        .where(
            StatsModel.team_id == team.id,
            SportsGame.status == "final",
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    if exclude_playoffs:
        stmt = stmt.where(SportsGame.season_type == "regular")
    result = await db.execute(stmt)
    rows = result.all()

    if len(rows) < 5:
        logger.info(
            "insufficient_games_for_profile",
            extra={"team": abbreviation, "games": len(rows)},
        )
        return None

    # Aggregate stats into a rolling profile using the appropriate
    # stats_to_metrics function
    if metrics_fn is None:
        # MLB: use training helper for exact parity with training pipeline
        from app.tasks._training_helpers import stats_to_metrics
        metrics_fn = stats_to_metrics

    game_dates = [gd for _, gd in rows]
    weights = _season_weights(game_dates)

    all_metrics: list[dict[str, float]] = []
    for stats_row, _game_date in rows:
        all_metrics.append(metrics_fn(stats_row))

    aggregated: dict[str, float] = {}
    for key in all_metrics[0]:
        vw = [(m[key], w) for m, w in zip(all_metrics, weights) if key in m]
        if vw:
            aggregated[key] = round(_weighted_mean(vw), 4)

    # Build freshness metadata from game_dates (already desc sorted)
    newest_date = game_dates[0].strftime("%Y-%m-%d")
    oldest_date = game_dates[-1].strftime("%Y-%m-%d")
    season_breakdown: dict[int, int] = {}
    for gd in game_dates:
        season_breakdown[gd.year] = season_breakdown.get(gd.year, 0) + 1

    return ProfileResult(
        metrics=aggregated,
        games_used=len(rows),
        date_range=(oldest_date, newest_date),
        season_breakdown=season_breakdown,
    )


async def get_team_info(
    abbreviation: str,
    *,
    sport: str = "mlb",
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Get basic team info by abbreviation.

    The ``sport`` parameter defaults to ``"mlb"`` for backward compatibility.
    """
    from app.db.sports import SportsLeague, SportsTeam

    config = _SPORT_CONFIG.get(sport.lower())
    if config is None:
        return None

    league_code = config[0]

    league_sq = (
        select(SportsLeague.id)
        .where(SportsLeague.code == league_code)
        .scalar_subquery()
    )
    result = await db.execute(
        select(SportsTeam)
        .where(
            SportsTeam.abbreviation == abbreviation.upper(),
            SportsTeam.league_id == league_sq,
        )
        .limit(1)
    )
    team = result.scalar_one_or_none()
    if team is None:
        return None
    return {
        "id": team.id,
        "name": team.name,
        "short_name": team.short_name,
        "abbreviation": team.abbreviation,
    }


# ---------------------------------------------------------------------------
# Probability conversion functions
# ---------------------------------------------------------------------------

def profile_to_pa_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert a team's rolling profile metrics into PA event probabilities.

    Maps real team statistics to plate-appearance outcome probabilities
    used by the Monte Carlo game simulator. Teams with better contact
    rates get more hits; teams with higher whiff rates get more
    strikeouts, etc.
    """
    # Extract key metrics with league-average defaults
    whiff = profile.get("whiff_rate", 0.23)
    barrel = profile.get("barrel_rate", 0.07)
    hard_hit = profile.get("hard_hit_rate", 0.35)
    contact = profile.get("contact_rate", 0.77)
    chase = profile.get("chase_rate", 0.32)

    # Map to PA probabilities (league averages as anchors)
    # Higher whiff → more strikeouts
    k_prob = _clamp(0.15 + whiff * 0.35, 0.10, 0.38)

    # Better discipline (less chase) → more walks
    walk_prob = _clamp(0.05 + (1.0 - chase) * 0.06, 0.03, 0.14)

    # Higher barrel rate → more home runs
    hr_prob = _clamp(barrel * 0.45, 0.005, 0.06)

    # Higher hard hit → more doubles
    double_prob = _clamp(0.02 + hard_hit * 0.09, 0.02, 0.09)

    # Triples are rare and mostly speed-based
    triple_prob = 0.008

    # Singles from contact minus extra-base hits
    contact_hitting = _clamp(contact * 0.25, 0.08, 0.22)
    single_prob = max(contact_hitting - hr_prob - double_prob - triple_prob, 0.06)

    # Out probability is the residual
    named_total = k_prob + walk_prob + single_prob + double_prob + triple_prob + hr_prob
    # Ensure we don't exceed 1.0
    if named_total > 0.95:
        scale = 0.95 / named_total
        k_prob *= scale
        walk_prob *= scale
        single_prob *= scale
        double_prob *= scale
        triple_prob *= scale
        hr_prob *= scale

    return {
        "strikeout_probability": round(k_prob, 4),
        "walk_or_hbp_probability": round(walk_prob, 4),
        "single_probability": round(single_prob, 4),
        "double_probability": round(double_prob, 4),
        "triple_probability": round(triple_prob, 4),
        "home_run_probability": round(hr_prob, 4),
    }


def profile_to_nba_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert NBA team metrics to possession event probabilities.

    Maps team advanced stats to per-possession outcome probabilities
    for use by the NBA game simulator.
    """
    efg = profile.get("efg_pct", 0.50)
    tov = profile.get("tov_pct", 0.13)
    fg3 = profile.get("fg3_pct", 0.36)
    ft_rate = profile.get("ft_rate", 0.25)
    orb = profile.get("orb_pct", 0.25)

    # Turnover probability per possession
    turnover_prob = _clamp(tov, 0.05, 0.25)

    # Free-throw trip probability (FTA/FGA ratio scaled to per-possession)
    ft_trip_prob = _clamp(ft_rate * 0.20, 0.02, 0.15)

    # Shot attempt probability is what remains after turnovers and FT trips
    remaining = 1.0 - turnover_prob - ft_trip_prob

    # Of shots attempted, split into makes vs misses using eFG%
    # eFG already accounts for 3PT bonus, so overall make rate ~ eFG
    make_prob = _clamp(remaining * efg, 0.10, 0.55)
    miss_prob = remaining - make_prob

    # Of makes, split into 2PT and 3PT using fg3_pct as a proxy
    # Higher fg3_pct means more 3PT attempts convert
    three_pt_share = _clamp(fg3 * 0.60, 0.10, 0.45)
    three_pt_make_prob = round(make_prob * three_pt_share, 4)
    two_pt_make_prob = round(make_prob * (1.0 - three_pt_share), 4)

    # Offensive rebound probability on misses
    orb_prob = _clamp(orb, 0.15, 0.40)

    return {
        "turnover_probability": round(turnover_prob, 4),
        "ft_trip_probability": round(ft_trip_prob, 4),
        "two_pt_make_probability": two_pt_make_prob,
        "three_pt_make_probability": three_pt_make_prob,
        "miss_probability": round(miss_prob, 4),
        "offensive_rebound_probability": round(orb_prob, 4),
    }


def profile_to_nhl_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert NHL team metrics to shot event probabilities.

    Maps team advanced stats to per-shot outcome probabilities
    for use by the NHL game simulator.
    """
    shooting = profile.get("shooting_pct", 0.09)
    save = profile.get("save_pct", 0.91)
    xgoals_pct = profile.get("xgoals_pct", 0.50)
    corsi = profile.get("corsi_pct", 0.50)

    # Goal probability per shot attempt — blend shooting_pct with xG signal
    base_goal = _clamp(shooting, 0.03, 0.18)
    # Adjust slightly by xGoals dominance
    xg_adj = (xgoals_pct - 0.50) * 0.04
    goal_prob = _clamp(base_goal + xg_adj, 0.03, 0.18)

    # Save probability (goalie stops it)
    save_prob = _clamp(1.0 - goal_prob - 0.15, 0.55, 0.85)

    # Remaining split between blocked and missed
    remaining = 1.0 - goal_prob - save_prob
    blocked_prob = round(remaining * 0.55, 4)
    missed_prob = round(remaining * 0.45, 4)

    # Possession share from Corsi
    possession_share = _clamp(corsi / 100.0 if corsi > 1.0 else corsi, 0.35, 0.65)

    return {
        "goal_probability": round(goal_prob, 4),
        "save_probability": round(save_prob, 4),
        "blocked_probability": blocked_prob,
        "missed_probability": missed_prob,
        "possession_share": round(possession_share, 4),
    }


def profile_to_ncaab_probabilities(profile: dict[str, float]) -> dict[str, float]:
    """Convert NCAAB team metrics to possession event probabilities.

    Similar to NBA but uses four-factor columns directly.
    """
    efg = profile.get("off_efg_pct", 0.50)
    tov = profile.get("off_tov_pct", 0.18)
    orb = profile.get("off_orb_pct", 0.30)
    ft_rate = profile.get("off_ft_rate", 0.30)

    # Turnover probability per possession (NCAAB tends higher than NBA)
    turnover_prob = _clamp(tov, 0.08, 0.30)

    # Free-throw trip probability
    ft_trip_prob = _clamp(ft_rate * 0.18, 0.02, 0.15)

    # Shot attempt probability is what remains
    remaining = 1.0 - turnover_prob - ft_trip_prob

    # Make vs miss using eFG%
    make_prob = _clamp(remaining * efg, 0.10, 0.50)
    miss_prob = remaining - make_prob

    # Split makes into 2PT and 3PT — NCAAB has lower 3PT rate than NBA
    three_pt_pct = profile.get("three_pt_pct", 0.33)
    three_pt_share = _clamp(three_pt_pct * 0.55, 0.08, 0.40)
    three_pt_make_prob = round(make_prob * three_pt_share, 4)
    two_pt_make_prob = round(make_prob * (1.0 - three_pt_share), 4)

    # Offensive rebound probability on misses
    orb_prob = _clamp(orb, 0.18, 0.45)

    return {
        "turnover_probability": round(turnover_prob, 4),
        "ft_trip_probability": round(ft_trip_prob, 4),
        "two_pt_make_probability": two_pt_make_prob,
        "three_pt_make_probability": three_pt_make_prob,
        "miss_probability": round(miss_prob, 4),
        "offensive_rebound_probability": round(orb_prob, 4),
    }


def profile_to_probabilities(sport: str, profile: dict[str, float]) -> dict[str, float]:
    """Route to sport-specific probability conversion."""
    s = sport.lower()
    if s == "mlb":
        return profile_to_pa_probabilities(profile)
    elif s == "nba":
        return profile_to_nba_probabilities(profile)
    elif s == "nhl":
        return profile_to_nhl_probabilities(profile)
    elif s == "ncaab":
        return profile_to_ncaab_probabilities(profile)
    return {}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))



# Re-export MLB-specific functions for backward compatibility.
# New code should import directly from the specific modules.
from app.analytics.services.mlb_player_profiles import (  # noqa: F401
    _pitcher_profile_from_boxscore,
    _pitcher_profile_from_statcast,
    get_pitcher_rolling_profile,
    get_player_rolling_profile,
)
from app.analytics.services.mlb_roster_service import (  # noqa: F401
    _fetch_mlb_api_roster,
    get_team_roster,
)
