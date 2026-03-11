"""Shared helpers for analytics training tasks.

Data loading, rolling profile aggregation, feature conversion,
and sklearn model factory used by training, backtest, and batch
simulation tasks.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


async def load_training_data_from_db(
    *,
    sport: str,
    model_type: str,
    date_start: str | None,
    date_end: str | None,
    rolling_window: int = 30,
    db: "AsyncSession | None" = None,
) -> list[dict]:
    """Load historical training data from the database.

    For MLB game models: queries MLBGameAdvancedStats + SportsGame
    to build rolling team profiles (aggregated from prior N games)
    with win/loss labels.

    Args:
        db: Optional async session. When called from a Celery task,
            pass a session bound to the task's event loop to avoid
            "Future attached to a different loop" errors.
    """
    if sport.lower() != "mlb":
        raise ValueError(f"Unsupported sport: {sport}. Only 'mlb' is currently supported.")

    if model_type == "game":
        return await _load_mlb_game_training_data(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    if model_type == "plate_appearance":
        return await _load_mlb_pa_training_data(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    raise ValueError(
        f"Unsupported model_type: {model_type}. "
        f"Only 'game' and 'plate_appearance' are currently supported for MLB training."
    )


async def _load_mlb_game_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: "AsyncSession | None" = None,
) -> list[dict]:
    """Load MLB game training data using rolling team profiles.

    For each game, builds home/away profiles by aggregating each team's
    prior N games of advanced stats. This prevents data leakage — a team's
    features for game X only use data from games before X.

    Games where a team has fewer than 5 prior games are skipped to
    ensure profiles are meaningful.
    """
    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            return await _load_mlb_game_training_data_impl(
                db, date_start, date_end,
                rolling_window=rolling_window,
            )

    return await _load_mlb_game_training_data_impl(
        db, date_start, date_end,
        rolling_window=rolling_window,
    )


async def _load_mlb_game_training_data_impl(
    db: "AsyncSession",
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
) -> list[dict]:
    """Inner implementation with an explicit session."""
    from sqlalchemy import select

    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame

    min_games = 5

    # Parse date strings to datetime objects for timestamptz comparison
    dt_start = (
        datetime.strptime(date_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if date_start else None
    )
    dt_end = (
        datetime.strptime(date_end, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        if date_end else None
    )

    train_stmt = (
        select(SportsGame)
        .where(SportsGame.status == "final")
        .order_by(SportsGame.game_date.asc())
    )
    if dt_start:
        train_stmt = train_stmt.where(SportsGame.game_date >= dt_start)
    if dt_end:
        train_stmt = train_stmt.where(SportsGame.game_date <= dt_end)

    result = await db.execute(train_stmt)
    training_games = result.scalars().all()

    if not training_games:
        return []

    all_stats_stmt = (
        select(MLBGameAdvancedStats)
        .join(SportsGame, SportsGame.id == MLBGameAdvancedStats.game_id)
        .where(SportsGame.status == "final")
        .order_by(SportsGame.game_date.asc())
    )
    if dt_end:
        all_stats_stmt = all_stats_stmt.where(SportsGame.game_date <= dt_end)

    stats_result = await db.execute(all_stats_stmt)
    all_stats = stats_result.scalars().all()

    stats_by_game: dict[int, list] = defaultdict(list)
    for s in all_stats:
        stats_by_game[s.game_id].append(s)

    game_dates: dict[int, str] = {}
    for g in training_games:
        game_dates[g.id] = str(g.game_date)

    all_game_ids = list(stats_by_game.keys())
    if all_game_ids:
        dates_stmt = select(SportsGame.id, SportsGame.game_date).where(
            SportsGame.id.in_(all_game_ids)
        )
        dates_result = await db.execute(dates_stmt)
        for gid, gdate in dates_result:
            game_dates[gid] = str(gdate)

    team_history: dict[int, list[tuple[str, object]]] = defaultdict(list)
    for game_id, stats_list in stats_by_game.items():
        gdate = game_dates.get(game_id, "")
        for s in stats_list:
            team_history[s.team_id].append((gdate, s))

    for tid in team_history:
        team_history[tid].sort(key=lambda x: x[0])

    records = []
    skipped_insufficient = 0

    for game in training_games:
        game_stats = stats_by_game.get(game.id, [])
        if len(game_stats) != 2:
            continue

        home_stats = None
        away_stats = None
        for s in game_stats:
            if s.is_home:
                home_stats = s
            else:
                away_stats = s

        if not home_stats or not away_stats:
            continue

        home_score = get_game_score(game, is_home=True)
        away_score = get_game_score(game, is_home=False)
        if home_score is None or away_score is None:
            continue

        game_date_str = str(game.game_date)

        home_profile = build_rolling_profile(
            team_history[home_stats.team_id],
            before_date=game_date_str,
            window=rolling_window,
        )
        away_profile = build_rolling_profile(
            team_history[away_stats.team_id],
            before_date=game_date_str,
            window=rolling_window,
        )

        if home_profile is None or away_profile is None:
            skipped_insufficient += 1
            continue

        records.append({
            "home_profile": {"metrics": home_profile},
            "away_profile": {"metrics": away_profile},
            "home_win": 1 if home_score > away_score else 0,
            "home_score": home_score,
            "away_score": away_score,
        })

    logger.info(
        "mlb_training_data_loaded",
        extra={
            "records": len(records),
            "games_queried": len(training_games),
            "skipped_insufficient_history": skipped_insufficient,
            "rolling_window": rolling_window,
        },
    )
    return records


# ---------------------------------------------------------------------------
# Plate-appearance training data
# ---------------------------------------------------------------------------


async def _load_mlb_pa_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: "AsyncSession | None" = None,
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
    db: "AsyncSession",
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
        datetime.strptime(date_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if date_start else None
    )
    dt_end = (
        datetime.strptime(date_end, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
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
        return "walk"
    if barrel > 0.15 and avg_ev > 95:
        return "home_run"
    if hard_hit > 0.50 and avg_ev > 93:
        return "double"
    if bip > 0 and hard_hit > 0.40:
        return "single"
    if whiff_rate > 0.28:
        return "strikeout"
    if bip == 0 and total_pitches > 0:
        return "out"
    if hard_hit < 0.20:
        return "out"
    return "single"


# ---------------------------------------------------------------------------
# Profile aggregation
# ---------------------------------------------------------------------------


def build_rolling_profile(
    team_games: list[tuple[str, object]],
    *,
    before_date: str,
    window: int,
    min_games: int = 5,
) -> dict | None:
    """Aggregate a team's prior games into a rolling profile.

    Args:
        team_games: Chronologically sorted list of (date_str, MLBGameAdvancedStats).
        before_date: Only include games strictly before this date.
        window: Maximum number of prior games to include.
        min_games: Minimum prior games required; returns None if insufficient.
    """
    prior = [stats for date_str, stats in team_games if date_str < before_date]

    if len(prior) < min_games:
        return None

    recent = prior[-window:]
    all_metrics: list[dict] = [stats_to_metrics(s) for s in recent]

    aggregated: dict[str, float] = {}
    for key in all_metrics[0]:
        values = [m[key] for m in all_metrics if key in m]
        if values:
            aggregated[key] = round(sum(values) / len(values), 4)

    return aggregated


# ---------------------------------------------------------------------------
# Stats → metrics conversion
# ---------------------------------------------------------------------------


def stats_to_metrics(stats: Any) -> dict:
    """Convert MLBGameAdvancedStats row to metrics dict for feature builder.

    Exposes both raw DB columns and derived composites so the feature
    builder has a rich set of inputs to choose from.
    """
    total_pitches = stats.total_pitches or 0
    balls_in_play = stats.balls_in_play or 0

    return {
        # --- Raw plate discipline columns ---
        "total_pitches": float(total_pitches),
        "zone_pitches": float(stats.zone_pitches or 0),
        "zone_swings": float(stats.zone_swings or 0),
        "zone_contact": float(stats.zone_contact or 0),
        "outside_pitches": float(stats.outside_pitches or 0),
        "outside_swings": float(stats.outside_swings or 0),
        "outside_contact": float(stats.outside_contact or 0),
        # --- Raw plate discipline percentages ---
        "z_swing_pct": stats.z_swing_pct or 0.0,
        "o_swing_pct": stats.o_swing_pct or 0.0,
        "z_contact_pct": stats.z_contact_pct or 0.0,
        "o_contact_pct": stats.o_contact_pct or 0.0,
        # --- Raw quality of contact columns ---
        "balls_in_play": float(balls_in_play),
        "hard_hit_count": float(stats.hard_hit_count or 0),
        "barrel_count": float(stats.barrel_count or 0),
        # --- Raw quality of contact percentages ---
        "avg_exit_velo": stats.avg_exit_velo or 88.0,
        "hard_hit_pct": stats.hard_hit_pct or 0.0,
        "barrel_pct": stats.barrel_pct or 0.0,
        # --- Derived composites (original 8) ---
        "contact_rate": _safe_rate(stats.z_contact_pct, stats.o_contact_pct),
        "power_index": _power_index(stats.avg_exit_velo, stats.barrel_pct),
        "barrel_rate": stats.barrel_pct or 0.0,
        "hard_hit_rate": stats.hard_hit_pct or 0.0,
        "swing_rate": _safe_rate(stats.z_swing_pct, stats.o_swing_pct),
        "whiff_rate": _whiff_rate(stats),
        "avg_exit_velocity": stats.avg_exit_velo or 88.0,
        "expected_slug": _expected_slug(stats),
        # --- Additional derived ratios ---
        "zone_swing_rate": (
            (stats.zone_swings / stats.zone_pitches)
            if (stats.zone_pitches or 0) > 0 else 0.0
        ),
        "chase_rate": (
            (stats.outside_swings / stats.outside_pitches)
            if (stats.outside_pitches or 0) > 0 else 0.0
        ),
        "zone_contact_rate": (
            (stats.zone_contact / stats.zone_swings)
            if (stats.zone_swings or 0) > 0 else 0.0
        ),
        "outside_contact_rate": (
            (stats.outside_contact / stats.outside_swings)
            if (stats.outside_swings or 0) > 0 else 0.0
        ),
        "plate_discipline_index": _plate_discipline_index(stats),
    }


def _safe_rate(zone_pct: float | None, outside_pct: float | None) -> float:
    """Combine zone and outside rates into an overall rate."""
    z = zone_pct or 0.0
    o = outside_pct or 0.0
    return round((z + o) / 2, 4) if (z or o) else 0.0


def _power_index(avg_ev: float | None, barrel_pct: float | None) -> float:
    """Composite power metric from exit velocity and barrel rate."""
    ev = avg_ev or 88.0
    bp = barrel_pct or 0.07
    return round((ev / 88.0) * (1 + bp * 5), 4)


def _whiff_rate(stats: Any) -> float:
    """Calculate whiff rate from available swing/contact data."""
    total_swings = (stats.zone_swings or 0) + (stats.outside_swings or 0)
    total_contact = (stats.zone_contact or 0) + (stats.outside_contact or 0)
    if total_swings == 0:
        return 0.23
    return round(1.0 - (total_contact / total_swings), 4)


def _expected_slug(stats: Any) -> float:
    """Estimate expected slugging from quality of contact metrics."""
    ev = stats.avg_exit_velo or 88.0
    hh = stats.hard_hit_pct or 0.35
    bp = stats.barrel_pct or 0.07
    return round(0.3 + (ev - 80) * 0.01 + hh * 0.5 + bp * 2.0, 4)


def _plate_discipline_index(stats: Any) -> float:
    """Composite plate discipline: high zone swing + low chase = good."""
    z_swing = stats.z_swing_pct or 0.0
    o_swing = stats.o_swing_pct or 0.0
    # Reward swinging at strikes, penalize chasing
    return round(z_swing - o_swing * 0.5, 4) if (z_swing or o_swing) else 0.0


# ---------------------------------------------------------------------------
# Game score + sklearn model factory
# ---------------------------------------------------------------------------


def get_game_score(game: Any, *, is_home: bool) -> int | None:
    """Extract score from a SportsGame for home or away team."""
    if hasattr(game, "home_score") and hasattr(game, "away_score"):
        return game.home_score if is_home else game.away_score

    raw = getattr(game, "raw_data", None) or {}
    if is_home:
        return raw.get("home_score") or raw.get("homeScore")
    return raw.get("away_score") or raw.get("awayScore")


def get_sklearn_model(algorithm: str, model_type: str, random_state: int):
    """Create sklearn model instance based on algorithm choice."""
    if algorithm == "random_forest":
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        if model_type in ("plate_appearance", "game"):
            return RandomForestClassifier(
                n_estimators=200, max_depth=6, random_state=random_state
            )
        return RandomForestRegressor(
            n_estimators=200, max_depth=6, random_state=random_state
        )

    if algorithm == "xgboost":
        try:
            from xgboost import XGBClassifier, XGBRegressor
            if model_type in ("plate_appearance", "game"):
                return XGBClassifier(
                    n_estimators=200, max_depth=5, random_state=random_state,
                    use_label_encoder=False, eval_metric="logloss",
                )
            return XGBRegressor(
                n_estimators=200, max_depth=5, random_state=random_state,
            )
        except ImportError:
            pass

    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
    if model_type in ("plate_appearance", "game"):
        return GradientBoostingClassifier(
            n_estimators=100, max_depth=5, random_state=random_state,
        )
    return GradientBoostingRegressor(
        n_estimators=100, max_depth=4, random_state=random_state,
    )
