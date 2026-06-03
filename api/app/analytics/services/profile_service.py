"""Multi-sport team profile service.

Builds rolling team profiles from sport-specific advanced stats
(MLB, NBA, NHL, NCAAB) and converts profiles to event probabilities
for the simulation engines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.services.profile_math import (  # noqa: F401 - exported from profile service API
    _season_weights,
    _weighted_mean,
)
from app.analytics.services.profile_probabilities import (
    _clamp,  # noqa: F401 - exported from profile service API
    profile_to_nba_probabilities,  # noqa: F401 - exported from profile service API
    profile_to_ncaab_probabilities,  # noqa: F401 - exported from profile service API
    profile_to_nhl_probabilities,  # noqa: F401 - exported from profile service API
    profile_to_pa_probabilities,  # noqa: F401 - exported from profile service API
    profile_to_probabilities,  # noqa: F401 - exported from profile service API
)

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
        vw = [(m[key], w) for m, w in zip(all_metrics, weights, strict=False) if key in m]
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
