"""Data loading for analytics training tasks.

Loads historical MLB game and plate-appearance training data from
the database, building rolling team/player profiles for use as
model features.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.tasks._training_data_pa import _derive_pa_outcome  # noqa: F401
from app.tasks._training_helpers import build_rolling_profile, get_game_score

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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
    db: AsyncSession | None = None,
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
        from app.tasks._training_data_pa import _load_mlb_pa_training_data

        return await _load_mlb_pa_training_data(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    if model_type == "player_plate_appearance":
        from app.tasks._training_data_pa import _load_mlb_player_pa_training_data

        return await _load_mlb_player_pa_training_data(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    raise ValueError(
        f"Unsupported model_type: {model_type}. "
        f"Supported types: 'game', 'plate_appearance', 'player_plate_appearance'."
    )


async def _load_mlb_game_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
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
    db: AsyncSession,
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
) -> list[dict]:
    """Inner implementation with an explicit session."""
    from sqlalchemy import select

    from app.db.mlb_advanced import MLBGameAdvancedStats
    from app.db.sports import SportsGame

    # Parse date strings to datetime objects for timestamptz comparison
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
