"""Async team profile service.

Builds rolling team profiles from MLBGameAdvancedStats data in the
database. Reuses the same aggregation logic as the training pipeline
so that inference-time profiles match training-time profiles exactly.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_team_rolling_profile(
    abbreviation: str,
    sport: str,
    *,
    rolling_window: int = 30,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Build a rolling profile for a team from recent game stats.

    Looks up the team by abbreviation, finds their last N games with
    advanced stats, and aggregates into a single profile dict whose
    keys match what ``MLBFeatureBuilder`` and the training pipeline
    expect.

    Returns ``None`` if the team is not found or has insufficient data.
    """
    if sport.lower() != "mlb":
        return None

    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame, SportsLeague, SportsTeam

    # Resolve team ID from abbreviation — filter to MLB league to avoid
    # collisions with minor-league / All-Star teams sharing abbreviations.
    mlb_league_sq = (
        select(SportsLeague.id)
        .where(SportsLeague.code == "MLB")
        .scalar_subquery()
    )
    team_result = await db.execute(
        select(SportsTeam)
        .where(
            SportsTeam.abbreviation == abbreviation.upper(),
            SportsTeam.league_id == mlb_league_sq,
        )
        .limit(1)
    )
    team = team_result.scalar_one_or_none()
    if team is None:
        logger.warning("team_not_found", extra={"abbreviation": abbreviation})
        return None

    # Get this team's recent game stats ordered by game date
    stmt = (
        select(MLBGameAdvancedStats, SportsGame.game_date)
        .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
        .where(
            MLBGameAdvancedStats.team_id == team.id,
            SportsGame.status == "final",
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    result = await db.execute(stmt)
    rows = result.all()

    if len(rows) < 5:
        logger.info(
            "insufficient_games_for_profile",
            extra={"team": abbreviation, "games": len(rows)},
        )
        return None

    # Aggregate stats into a rolling profile using the same
    # stats_to_metrics function as training
    from app.tasks._training_helpers import stats_to_metrics

    all_metrics: list[dict[str, float]] = []
    for stats_row, _game_date in rows:
        all_metrics.append(stats_to_metrics(stats_row))

    aggregated: dict[str, float] = {}
    for key in all_metrics[0]:
        values = [m[key] for m in all_metrics if key in m]
        if values:
            aggregated[key] = round(sum(values) / len(values), 4)

    return aggregated


async def get_team_info(
    abbreviation: str,
    *,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Get basic team info by abbreviation."""
    from app.db.sports import SportsLeague, SportsTeam

    mlb_league_sq = (
        select(SportsLeague.id)
        .where(SportsLeague.code == "MLB")
        .scalar_subquery()
    )
    result = await db.execute(
        select(SportsTeam)
        .where(
            SportsTeam.abbreviation == abbreviation.upper(),
            SportsTeam.league_id == mlb_league_sq,
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
    discipline = profile.get("plate_discipline_index", 0.52)
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
        "walk_probability": round(walk_prob, 4),
        "single_probability": round(single_prob, 4),
        "double_probability": round(double_prob, 4),
        "triple_probability": round(triple_prob, 4),
        "home_run_probability": round(hr_prob, 4),
    }


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))
