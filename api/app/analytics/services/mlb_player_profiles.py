"""MLB player and pitcher profile service.

Rolling statistical profiles for individual batters and pitchers,
used by lineup-aware simulation. MLB-only — other sports do not
yet have player-level simulation support.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.services.profile_service import (
    ProfileResult,
    _clamp,
    _season_weights,
    _weighted_mean,
)

logger = logging.getLogger(__name__)


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
            # Late import to allow mock.patch on profile_service
            import app.analytics.services.profile_service as _ps

            team_profile_result = await _ps.get_team_rolling_profile(
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
    # Look up helpers via the profile_service module so that
    # mock.patch("app.analytics.services.profile_service._pitcher_profile_from_*")
    # works in tests (the re-exports live there).
    import app.analytics.services.profile_service as _ps

    # Try enriched pitcher stats first
    profile = await _ps._pitcher_profile_from_statcast(
        player_external_ref, team_id,
        rolling_window=rolling_window,
        exclude_playoffs=exclude_playoffs,
        db=db,
    )
    if profile is not None:
        return profile

    # Fallback: derive from boxscore JSONB
    return await _ps._pitcher_profile_from_boxscore(
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
