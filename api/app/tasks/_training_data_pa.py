"""Plate-appearance training data loaders.

Extracted from _training_data.py — loads historical MLB plate-appearance
and player-level PA training data from the database.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.tasks._training_helpers import build_rolling_profile, stats_to_metrics

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _load_mlb_pa_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load MLB plate-appearance training data using player stats.

    Builds training records by pairing each batter's rolling profile
    with the opposing team's rolling pitching profile.  The PA outcome
    is derived from the player's game-level metrics.
    """
    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            return await _load_mlb_pa_training_data_impl(
                db, date_start, date_end,
                rolling_window=rolling_window,
            )

    return await _load_mlb_pa_training_data_impl(
        db, date_start, date_end,
        rolling_window=rolling_window,
    )


async def _load_mlb_pa_training_data_impl(
    db: AsyncSession,
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
) -> list[dict]:
    """Inner implementation for PA training data loading."""
    from sqlalchemy import select

    from app.db.mlb_advanced import MLBGameAdvancedStats, MLBPlayerAdvancedStats
    from app.db.sports import SportsGame

    min_games = 5

    dt_start = (
        datetime.strptime(date_start, "%Y-%m-%d").replace(tzinfo=UTC)
        if date_start else None
    )
    dt_end = (
        datetime.strptime(date_end, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=UTC
        )
        if date_end else None
    )

    # 1. Get completed games in range
    game_stmt = (
        select(SportsGame)
        .where(SportsGame.status == "final")
        .order_by(SportsGame.game_date.asc())
    )
    if dt_start:
        game_stmt = game_stmt.where(SportsGame.game_date >= dt_start)
    if dt_end:
        game_stmt = game_stmt.where(SportsGame.game_date <= dt_end)

    result = await db.execute(game_stmt)
    games = result.scalars().all()
    if not games:
        return []

    game_ids = [g.id for g in games]
    game_map = {g.id: g for g in games}

    # 2. Load player stats for these games
    player_stmt = (
        select(MLBPlayerAdvancedStats)
        .where(MLBPlayerAdvancedStats.game_id.in_(game_ids))
    )
    player_result = await db.execute(player_stmt)
    all_player_stats = player_result.scalars().all()

    if not all_player_stats:
        return []

    # 3. Build rolling team profiles (for pitcher proxy) using game-level stats
    team_stats_stmt = (
        select(MLBGameAdvancedStats)
        .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
        .where(SportsGame.status == "final")
        .order_by(SportsGame.game_date.asc())
    )
    if dt_end:
        team_stats_stmt = team_stats_stmt.where(SportsGame.game_date <= dt_end)

    team_result = await db.execute(team_stats_stmt)
    all_team_stats = team_result.scalars().all()

    # Map game_id → list of team stats, and build date lookup
    team_stats_by_game: dict[int, list] = defaultdict(list)
    for ts in all_team_stats:
        team_stats_by_game[ts.game_id].append(ts)

    game_dates: dict[int, str] = {}
    for g in games:
        game_dates[g.id] = str(g.game_date)
    # Also get dates for team stats games outside our range (for rolling)
    extra_game_ids = [gid for gid in team_stats_by_game if gid not in game_dates]
    if extra_game_ids:
        dates_stmt = select(SportsGame.id, SportsGame.game_date).where(
            SportsGame.id.in_(extra_game_ids)
        )
        dates_result = await db.execute(dates_stmt)
        for gid, gdate in dates_result:
            game_dates[gid] = str(gdate)

    # Build team history for rolling pitcher profiles
    team_history: dict[int, list[tuple[str, object]]] = defaultdict(list)
    for game_id, stats_list in team_stats_by_game.items():
        gdate = game_dates.get(game_id, "")
        for s in stats_list:
            team_history[s.team_id].append((gdate, s))
    for tid in team_history:
        team_history[tid].sort(key=lambda x: x[0])

    # 4. Build per-player history for rolling batter profiles
    player_history: dict[str, list[tuple[str, object]]] = defaultdict(list)
    for ps in all_player_stats:
        gdate = game_dates.get(ps.game_id, "")
        player_history[ps.player_external_ref].append((gdate, ps))
    for pid in player_history:
        player_history[pid].sort(key=lambda x: x[0])

    # 5. For each player-game, build a training record
    records = []
    skipped = 0

    for ps in all_player_stats:
        if ps.game_id not in game_map:
            continue

        game = game_map[ps.game_id]
        game_date_str = str(game.game_date)

        # Batter rolling profile (from player's prior games)
        batter_prior = [
            s for d, s in player_history[ps.player_external_ref]
            if d < game_date_str
        ]
        if len(batter_prior) < min_games:
            skipped += 1
            continue

        batter_recent = batter_prior[-rolling_window:]
        batter_metrics_list = [stats_to_metrics(s) for s in batter_recent]
        batter_profile: dict[str, float] = {}
        for key in batter_metrics_list[0]:
            vals = [m[key] for m in batter_metrics_list if key in m]
            if vals:
                batter_profile[key] = round(sum(vals) / len(vals), 4)

        # Pitcher proxy: opposing team's rolling profile
        opp_team_stats = team_stats_by_game.get(ps.game_id, [])
        opp_team_id = None
        for ts in opp_team_stats:
            if ts.team_id != ps.team_id:
                opp_team_id = ts.team_id
                break

        if opp_team_id is None:
            skipped += 1
            continue

        pitcher_profile_data = build_rolling_profile(
            team_history.get(opp_team_id, []),
            before_date=game_date_str,
            window=rolling_window,
        )
        if pitcher_profile_data is None:
            skipped += 1
            continue

        # Derive PA outcome from player's game metrics
        outcome = _derive_pa_outcome(ps)

        records.append({
            "batter_profile": {"metrics": batter_profile},
            "pitcher_profile": {"metrics": pitcher_profile_data},
            "outcome": outcome,
        })

    logger.info(
        "mlb_pa_training_data_loaded",
        extra={
            "records": len(records),
            "player_game_rows": len(all_player_stats),
            "skipped_insufficient_history": skipped,
            "rolling_window": rolling_window,
        },
    )
    return records


async def _load_mlb_player_pa_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load true player-level PA training data from PBP events.

    Uses the MLBPADatasetBuilder to extract real PA outcomes from
    play-by-play data with point-in-time batter and pitcher profiles.
    """
    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            return await _load_mlb_player_pa_impl(
                db, date_start, date_end, rolling_window=rolling_window
            )

    return await _load_mlb_player_pa_impl(
        db, date_start, date_end, rolling_window=rolling_window
    )


async def _load_mlb_player_pa_impl(
    db: AsyncSession,
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
) -> list[dict]:
    """Inner implementation using the PA dataset builder."""
    from app.analytics.datasets.mlb_pa_dataset import MLBPADatasetBuilder

    builder = MLBPADatasetBuilder(db)
    rows = await builder.build(
        date_start=date_start,
        date_end=date_end,
        rolling_window=rolling_window,
        include_profiles=True,
        include_fielding=True,
        min_batter_games=5,
        min_pitcher_games=3,
    )

    # Convert dataset rows to training record format
    records = []
    for row in rows:
        record: dict = {
            "batter_profile": row.get("batter_profile", {}),
            "pitcher_profile": row.get("pitcher_profile", {}),
            "outcome": row["outcome"],
        }
        # Add matchup context for the feature builder
        if row.get("batter_hand") or row.get("pitcher_hand"):
            record["matchup"] = {
                "batter_hand": row.get("batter_hand", ""),
                "pitcher_hand": row.get("pitcher_hand", ""),
            }
        # Add fielding context if available
        if row.get("team_fielding"):
            record["team_fielding"] = row["team_fielding"]
        records.append(record)

    logger.info(
        "mlb_player_pa_training_data_loaded",
        extra={
            "records": len(records),
            "rolling_window": rolling_window,
        },
    )
    return records


def _derive_pa_outcome(player_stats: object) -> str:
    """Derive a representative PA outcome from a player's game metrics.

    Uses Statcast batting metrics to categorize the player's dominant
    outcome type for that game.  This is an approximation — individual
    PA outcomes are not stored in the DB.
    """
    barrel = getattr(player_stats, "barrel_pct", None) or 0.0
    hard_hit = getattr(player_stats, "hard_hit_pct", None) or 0.0
    avg_ev = getattr(player_stats, "avg_exit_velo", None) or 88.0
    z_swing = getattr(player_stats, "z_swing_pct", None) or 0.0
    o_swing = getattr(player_stats, "o_swing_pct", None) or 0.0
    bip = getattr(player_stats, "balls_in_play", None) or 0
    total_pitches = getattr(player_stats, "total_pitches", None) or 1

    # Approximate contact rate
    total_swings = (
        (getattr(player_stats, "zone_swings", None) or 0)
        + (getattr(player_stats, "outside_swings", None) or 0)
    )
    total_contact = (
        (getattr(player_stats, "zone_contact", None) or 0)
        + (getattr(player_stats, "outside_contact", None) or 0)
    )
    whiff_rate = 1.0 - (total_contact / total_swings) if total_swings > 0 else 0.23

    # Decision tree for outcome classification
    if whiff_rate > 0.40:
        return "strikeout"
    if o_swing < 0.20 and z_swing < 0.55:
        return "walk_or_hbp"
    if barrel > 0.15 and avg_ev > 95:
        return "home_run"
    if hard_hit > 0.50 and avg_ev > 93:
        return "double"
    if bip > 0 and hard_hit > 0.40:
        return "single"
    if whiff_rate > 0.28:
        return "strikeout"
    if bip == 0 and total_pitches > 0:
        return "ball_in_play_out"
    if hard_hit < 0.20:
        return "ball_in_play_out"
    return "single"
