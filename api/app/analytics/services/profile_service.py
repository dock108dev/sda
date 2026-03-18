"""Async team profile service.

Builds rolling team profiles from MLBGameAdvancedStats data in the
database. Reuses the same aggregation logic as the training pipeline
so that inference-time profiles match training-time profiles exactly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    keys match what ``MLBFeatureBuilder`` and the training pipeline
    expect.

    Returns a ``ProfileResult`` with metrics and freshness metadata,
    or ``None`` if the team is not found or has insufficient data.
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

    # Aggregate stats into a rolling profile using the same
    # stats_to_metrics function as training
    from app.tasks._training_helpers import stats_to_metrics

    game_dates = [gd for _, gd in rows]
    weights = _season_weights(game_dates)

    all_metrics: list[dict[str, float]] = []
    for stats_row, _game_date in rows:
        all_metrics.append(stats_to_metrics(stats_row))

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


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


async def get_player_rolling_profile(
    player_external_ref: str,
    team_id: int,
    *,
    rolling_window: int = 30,
    exclude_playoffs: bool = False,
    db: AsyncSession,
) -> dict[str, float] | None:
    """Build a rolling batting profile for a player from recent game stats.

    If the player has fewer than 5 games, the profile is blended with the
    team's rolling profile so that low-sample players regress toward team
    averages rather than producing noisy standalone estimates.

    Returns ``None`` when no games are found at all.
    """
    from app.db.mlb_advanced import MLBPlayerAdvancedStats
    from app.db.sports import SportsGame, SportsTeam

    stmt = (
        select(MLBPlayerAdvancedStats, SportsGame.game_date)
        .join(SportsGame, SportsGame.id == MLBPlayerAdvancedStats.game_id)
        .where(
            MLBPlayerAdvancedStats.player_external_ref == player_external_ref,
            SportsGame.status == "final",
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    if exclude_playoffs:
        stmt = stmt.where(SportsGame.season_type == "regular")
    result = await db.execute(stmt)
    rows = result.all()

    if len(rows) == 0:
        return None

    from app.tasks._training_helpers import stats_to_metrics

    game_dates = [gd for _, gd in rows]
    weights = _season_weights(game_dates)

    all_metrics: list[dict[str, float]] = []
    for stats_row, _game_date in rows:
        all_metrics.append(stats_to_metrics(stats_row))

    player_profile: dict[str, float] = {}
    for key in all_metrics[0]:
        vw = [(m[key], w) for m, w in zip(all_metrics, weights) if key in m]
        if vw:
            player_profile[key] = round(_weighted_mean(vw), 4)

    games_found = len(rows)
    if games_found < 5:
        # Blend with team average — look up abbreviation from team_id
        team_result = await db.execute(
            select(SportsTeam).where(SportsTeam.id == team_id).limit(1)
        )
        team = team_result.scalar_one_or_none()
        if team is not None:
            team_profile_result = await get_team_rolling_profile(
                team.abbreviation, "mlb",
                exclude_playoffs=exclude_playoffs, db=db,
            )
            team_profile = team_profile_result.metrics if team_profile_result else None
            if team_profile is not None:
                player_weight = games_found / 5
                team_weight = 1.0 - player_weight
                blended: dict[str, float] = {}
                all_keys = set(player_profile) | set(team_profile)
                for key in all_keys:
                    p_val = player_profile.get(key, 0.0)
                    t_val = team_profile.get(key, 0.0)
                    blended[key] = round(
                        p_val * player_weight + t_val * team_weight, 4
                    )
                return blended

    return player_profile


async def get_pitcher_rolling_profile(
    player_external_ref: str,
    team_id: int,
    *,
    rolling_window: int = 30,
    exclude_playoffs: bool = False,
    db: AsyncSession,
) -> dict[str, float] | None:
    """Build a rolling pitching profile from recent game data.

    Prefers ``MLBPitcherGameStats`` (Statcast-enriched pitcher data) when
    available, falling back to ``SportsPlayerBoxscore`` for basic rate stats.

    Returns ``None`` when fewer than 3 games are available.
    """
    # Try enriched pitcher stats first
    profile = await _pitcher_profile_from_statcast(
        player_external_ref, team_id,
        rolling_window=rolling_window,
        exclude_playoffs=exclude_playoffs,
        db=db,
    )
    if profile is not None:
        return profile

    # Fallback: derive from boxscore JSONB
    return await _pitcher_profile_from_boxscore(
        player_external_ref, team_id,
        rolling_window=rolling_window,
        exclude_playoffs=exclude_playoffs,
        db=db,
    )


async def _pitcher_profile_from_statcast(
    player_external_ref: str,
    team_id: int,
    *,
    rolling_window: int = 30,
    exclude_playoffs: bool = False,
    db: AsyncSession,
) -> dict[str, float] | None:
    """Build pitcher profile from MLBPitcherGameStats (Statcast-enriched)."""
    try:
        from app.db.mlb_advanced import MLBPitcherGameStats
        from app.db.sports import SportsGame

        stmt = (
            select(MLBPitcherGameStats, SportsGame.game_date)
            .join(SportsGame, SportsGame.id == MLBPitcherGameStats.game_id)
            .where(
                MLBPitcherGameStats.player_external_ref == player_external_ref,
                MLBPitcherGameStats.team_id == team_id,
                SportsGame.status == "final",
            )
            .order_by(SportsGame.game_date.desc())
            .limit(rolling_window)
        )
        if exclude_playoffs:
            stmt = stmt.where(SportsGame.season_type == "regular")
        result = await db.execute(stmt)
        rows = result.all()

        if len(rows) < 3:
            return None

        # Verify the first row is actually an MLBPitcherGameStats instance
        first_row = rows[0][0]
        if not isinstance(getattr(first_row, "batters_faced", None), (int, float, type(None))):
            return None
    except Exception:
        # Table may not exist yet or query failed — fall back
        return None

    game_dates = [gd for _, gd in rows]
    weights = _season_weights(game_dates)

    per_game: list[dict[str, float]] = []
    for ps, _ in rows:
        bf = ps.batters_faced or 1
        m: dict[str, float] = {
            "k_rate": ps.k_rate if ps.k_rate is not None else (ps.strikeouts / bf if bf else 0),
            "bb_rate": ps.bb_rate if ps.bb_rate is not None else (ps.walks / bf if bf else 0),
            "hr_rate": ps.hr_rate if ps.hr_rate is not None else (ps.home_runs_allowed / bf if bf else 0),
            "whiff_rate": ps.whiff_rate or 0.0,
            "z_contact_pct": ps.z_contact_pct or 0.0,
            "chase_rate": ps.chase_rate or 0.0,
            "avg_exit_velo_against": ps.avg_exit_velo_against or 0.0,
            "hard_hit_pct_against": ps.hard_hit_pct_against or 0.0,
            "barrel_pct_against": ps.barrel_pct_against or 0.0,
        }
        # Derive suppression metrics for matchup compatibility
        m["contact_suppression"] = _clamp(
            1.0 - ((1.0 - (m["k_rate"] + m["bb_rate"])) * (1.0 - (m.get("whiff_rate", 0.0) * 0.5))),
            -0.15, 0.30,
        )
        m["power_suppression"] = _clamp(
            1.0 - (m["hr_rate"] / 0.03) if m["hr_rate"] < 0.03 else 0.0,
            -0.30, 0.50,
        )
        # Also compute strikeout_rate / walk_rate aliases for matchup.py
        m["strikeout_rate"] = m["k_rate"]
        m["walk_rate"] = m["bb_rate"]
        per_game.append(m)

    aggregated: dict[str, float] = {}
    for key in per_game[0]:
        vw = [(gm[key], w) for gm, w in zip(per_game, weights)]
        aggregated[key] = round(_weighted_mean(vw), 4)

    return aggregated


async def _pitcher_profile_from_boxscore(
    player_external_ref: str,
    team_id: int,
    *,
    rolling_window: int = 30,
    exclude_playoffs: bool = False,
    db: AsyncSession,
) -> dict[str, float] | None:
    """Fallback pitcher profile from SportsPlayerBoxscore JSONB stats."""
    from app.db.sports import SportsGame, SportsPlayerBoxscore

    stmt = (
        select(SportsPlayerBoxscore, SportsGame.game_date)
        .join(SportsGame, SportsGame.id == SportsPlayerBoxscore.game_id)
        .where(
            SportsPlayerBoxscore.player_external_ref == player_external_ref,
            SportsPlayerBoxscore.team_id == team_id,
            SportsGame.status == "final",
        )
        .order_by(SportsGame.game_date.desc())
        .limit(rolling_window)
    )
    if exclude_playoffs:
        stmt = stmt.where(SportsGame.season_type == "regular")
    result = await db.execute(stmt)
    rows = result.all()

    per_game_metrics: list[dict[str, float]] = []
    game_dates_for_weighting: list[datetime] = []
    for row, game_date in rows:
        stats = row.stats or {}
        strike_outs = float(stats.get("strikeOuts", stats.get("strike_outs", 0)))
        base_on_balls = float(stats.get("baseOnBalls", stats.get("base_on_balls", 0)))
        home_runs = float(stats.get("homeRuns", stats.get("home_runs", 0)))
        hits = float(stats.get("hits", 0))

        approx_bf = hits + base_on_balls + strike_outs + home_runs
        if approx_bf == 0:
            continue

        per_game_metrics.append(
            {
                "strikeout_rate": strike_outs / approx_bf,
                "walk_rate": base_on_balls / approx_bf,
                "contact_suppression": _clamp(
                    1.0 - (hits / approx_bf) - 0.30, -0.15, 0.30
                ),
                "power_suppression": _clamp(
                    1.0 - ((home_runs / approx_bf) / 0.03), -0.30, 0.50
                ),
            }
        )
        game_dates_for_weighting.append(game_date)

    if len(per_game_metrics) < 3:
        logger.info(
            "insufficient_games_for_pitcher_profile",
            extra={
                "player_external_ref": player_external_ref,
                "games": len(per_game_metrics),
            },
        )
        return None

    weights = _season_weights(game_dates_for_weighting)

    aggregated: dict[str, float] = {}
    for key in per_game_metrics[0]:
        vw = [(m[key], w) for m, w in zip(per_game_metrics, weights)]
        aggregated[key] = round(_weighted_mean(vw), 4)

    return aggregated


async def get_team_roster(
    team_abbreviation: str,
    *,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Fetch active batters and pitchers for a team over the last 30 days.

    Returns a dict with ``batters`` and ``pitchers`` lists built from
    recent final games. Returns ``None`` if the team cannot be found.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import cast, func
    from sqlalchemy.types import Float

    from app.db.mlb_advanced import MLBPlayerAdvancedStats
    from app.db.sports import (
        SportsGame,
        SportsLeague,
        SportsPlayerBoxscore,
        SportsTeam,
    )

    # Resolve team via MLB league (same pattern as get_team_rolling_profile)
    mlb_league_sq = (
        select(SportsLeague.id)
        .where(SportsLeague.code == "MLB")
        .scalar_subquery()
    )
    team_result = await db.execute(
        select(SportsTeam)
        .where(
            SportsTeam.abbreviation == team_abbreviation.upper(),
            SportsTeam.league_id == mlb_league_sq,
        )
        .limit(1)
    )
    team = team_result.scalar_one_or_none()
    if team is None:
        logger.warning(
            "team_not_found_for_roster",
            extra={"abbreviation": team_abbreviation},
        )
        return None

    # Try progressively wider windows: 30 days, 90 days, full season.
    # During the offseason the 30-day window will be empty, so we widen
    # until we find data.
    for lookback_days in (30, 90, 365):
        cutoff = datetime.now(tz=UTC) - timedelta(days=lookback_days)

        recent_games_sq = (
            select(SportsGame.id)
            .where(
                SportsGame.status == "final",
                SportsGame.game_date >= cutoff,
            )
            .scalar_subquery()
        )

        # --- Batters from MLBPlayerAdvancedStats ---
        batter_stmt = (
            select(
                MLBPlayerAdvancedStats.player_external_ref,
                MLBPlayerAdvancedStats.player_name,
                func.count().label("games_played"),
            )
            .where(
                MLBPlayerAdvancedStats.team_id == team.id,
                MLBPlayerAdvancedStats.game_id.in_(recent_games_sq),
            )
            .group_by(
                MLBPlayerAdvancedStats.player_external_ref,
                MLBPlayerAdvancedStats.player_name,
            )
            .order_by(func.count().desc())
        )
        batter_result = await db.execute(batter_stmt)
        batters = [
            {
                "external_ref": row.player_external_ref,
                "name": row.player_name,
                "games_played": row.games_played,
            }
            for row in batter_result.all()
        ]

        # --- Pitchers from SportsPlayerBoxscore ---
        pitcher_stmt = (
            select(
                SportsPlayerBoxscore.player_external_ref,
                SportsPlayerBoxscore.player_name,
                func.count().label("games"),
                func.avg(
                    cast(
                        SportsPlayerBoxscore.stats["inningsPitched"].as_float(),
                        Float,
                    )
                ).label("avg_ip"),
            )
            .where(
                SportsPlayerBoxscore.team_id == team.id,
                SportsPlayerBoxscore.game_id.in_(recent_games_sq),
                SportsPlayerBoxscore.stats["inningsPitched"].as_float() > 0,
            )
            .group_by(
                SportsPlayerBoxscore.player_external_ref,
                SportsPlayerBoxscore.player_name,
            )
        )
        pitcher_result = await db.execute(pitcher_stmt)
        pitchers = [
            {
                "external_ref": row.player_external_ref,
                "name": row.player_name,
                "games": row.games,
                "avg_ip": round(float(row.avg_ip), 2) if row.avg_ip else 0.0,
            }
            for row in pitcher_result.all()
        ]

        if batters or pitchers:
            break

    # If DB has no data at all, fall back to the MLB Stats API active roster.
    if not batters and not pitchers and team.external_ref:
        fallback = await _fetch_mlb_api_roster(team.external_ref)
        if fallback:
            return fallback

    return {"batters": batters, "pitchers": pitchers}


async def _fetch_mlb_api_roster(mlb_team_id: str) -> dict[str, Any] | None:
    """Fetch the active roster from the MLB Stats API.

    Uses ``/api/v1/teams/{id}/roster?rosterType=active`` which is
    public and requires no authentication.  Returns batters and pitchers
    in the same shape as the DB-backed ``get_team_roster``.
    """
    import httpx

    url = f"https://statsapi.mlb.com/api/v1/teams/{mlb_team_id}/roster?rosterType=active&hydrate=person"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("mlb_api_roster_fetch_failed", extra={"team_id": mlb_team_id})
        return None

    roster = data.get("roster", [])
    if not roster:
        return None

    batters: list[dict[str, Any]] = []
    pitchers: list[dict[str, Any]] = []

    for entry in roster:
        person = entry.get("person", {})
        player_id = str(person.get("id", ""))
        name = person.get("fullName", "")
        position_type = entry.get("position", {}).get("type", "")

        if not player_id or not name:
            continue

        if position_type == "Pitcher":
            pitchers.append({
                "external_ref": player_id,
                "name": name,
                "games": 0,
                "avg_ip": 0.0,
            })
        else:
            batters.append({
                "external_ref": player_id,
                "name": name,
                "games_played": 0,
            })

    return {"batters": batters, "pitchers": pitchers}
