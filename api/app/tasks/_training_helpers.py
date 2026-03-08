"""Shared helpers for analytics training tasks.

Data loading, rolling profile aggregation, feature conversion,
and sklearn model factory used by training, backtest, and batch
simulation tasks.
"""

from __future__ import annotations

import logging
from collections import defaultdict
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
        return []

    if model_type == "game":
        return await _load_mlb_game_training_data(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    return []


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
    from sqlalchemy import select

    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame

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

    train_stmt = (
        select(SportsGame)
        .where(SportsGame.status == "final")
        .order_by(SportsGame.game_date.asc())
    )
    if date_start:
        train_stmt = train_stmt.where(SportsGame.game_date >= date_start)
    if date_end:
        train_stmt = train_stmt.where(SportsGame.game_date <= date_end)

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
    if date_end:
        all_stats_stmt = all_stats_stmt.where(SportsGame.game_date <= date_end)

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
    """Convert MLBGameAdvancedStats row to metrics dict for feature builder."""
    return {
        "contact_rate": _safe_rate(stats.z_contact_pct, stats.o_contact_pct),
        "power_index": _power_index(stats.avg_exit_velo, stats.barrel_pct),
        "barrel_rate": stats.barrel_pct or 0.0,
        "hard_hit_rate": stats.hard_hit_pct or 0.0,
        "swing_rate": _safe_rate(stats.z_swing_pct, stats.o_swing_pct),
        "whiff_rate": _whiff_rate(stats),
        "avg_exit_velocity": stats.avg_exit_velo or 88.0,
        "expected_slug": _expected_slug(stats),
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
