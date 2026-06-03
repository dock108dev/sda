"""Generic sport game-model training data loaders."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from app.tasks._training_helpers import build_rolling_profile, get_game_score
from app.utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic sport game training data loader
# ---------------------------------------------------------------------------


async def _load_sport_game_training_data_impl(
    db: AsyncSession,
    date_start: str | None,
    date_end: str | None,
    *,
    sport_code: str,
    stats_model: type,
    rolling_window: int = 30,
) -> list[dict]:
    """Load game training data for any sport using rolling team profiles.

    This is the generic counterpart of ``_load_mlb_game_training_data_impl``.
    It filters games by league and uses the supplied advanced-stats model.
    No pitcher/starter features are included (MLB-specific).
    """
    from sqlalchemy import select

    from app.db.sports import SportsGame, SportsLeague

    # Resolve league
    league_stmt = select(SportsLeague.id).where(SportsLeague.code == sport_code.upper())
    league_id = (await db.execute(league_stmt)).scalar_one_or_none()
    if league_id is None:
        logger.warning("league_not_found", extra={"sport_code": sport_code})
        return []

    dt_start = start_of_et_day_utc(date.fromisoformat(date_start)) if date_start else None
    dt_end = end_of_et_day_utc(date.fromisoformat(date_end)) if date_end else None

    train_stmt = (
        select(SportsGame)
        .where(SportsGame.status == "final", SportsGame.league_id == league_id)
        .order_by(SportsGame.game_date.asc())
    )
    if dt_start:
        train_stmt = train_stmt.where(SportsGame.game_date >= dt_start)
    if dt_end:
        train_stmt = train_stmt.where(SportsGame.game_date < dt_end)

    result = await db.execute(train_stmt)
    training_games = result.scalars().all()

    if not training_games:
        return []

    # Load all advanced stats up through the end date
    all_stats_stmt = (
        select(stats_model)
        .join(SportsGame, SportsGame.id == stats_model.game_id)
        .where(SportsGame.status == "final", SportsGame.league_id == league_id)
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
        from sqlalchemy import select as _sel

        dates_stmt = _sel(SportsGame.id, SportsGame.game_date).where(
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

    # --- Closing lines for market probability ---
    from app.db.odds import ClosingLine

    closing_stmt = (
        select(ClosingLine)
        .where(
            ClosingLine.game_id.in_([g.id for g in training_games]),
            ClosingLine.market_key.in_(["h2h", "moneyline"]),
        )
    )
    closing_result = await db.execute(closing_stmt)
    all_closing_lines = closing_result.scalars().all()

    market_wp_by_game: dict[int, dict[str, float]] = {}
    from app.services.ev import american_to_implied, remove_vig

    lines_by_game: dict[int, list] = defaultdict(list)
    for cl in all_closing_lines:
        lines_by_game[cl.game_id].append(cl)

    for game_id, lines in lines_by_game.items():
        home_price = None
        away_price = None
        for cl in lines:
            sel = (cl.selection or "").lower()
            if "home" in sel:
                home_price = cl.price_american
            elif "away" in sel:
                away_price = cl.price_american
        if home_price is not None and away_price is not None:
            try:
                implied = [american_to_implied(home_price), american_to_implied(away_price)]
                true_probs = remove_vig(implied)
                market_wp_by_game[game_id] = {"home_wp": true_probs[0], "away_wp": true_probs[1]}
            except (ValueError, ZeroDivisionError):
                logger.debug("market_line_parse_failed", exc_info=True)

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

        market = market_wp_by_game.get(game.id, {"home_wp": 0.5, "away_wp": 0.5})

        records.append({
            "home_profile": {"metrics": home_profile},
            "away_profile": {"metrics": away_profile},
            "market_profile": {"metrics": market},
            "home_win": 1 if home_score > away_score else 0,
            "home_score": home_score,
            "away_score": away_score,
        })

    logger.info(
        f"{sport_code.lower()}_training_data_loaded",
        extra={
            "records": len(records),
            "games_queried": len(training_games),
            "skipped_insufficient_history": skipped_insufficient,
            "rolling_window": rolling_window,
            "games_with_market": len(market_wp_by_game),
        },
    )
    return records


# ---------------------------------------------------------------------------
# NBA game training data
# ---------------------------------------------------------------------------


async def _load_nba_game_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load NBA game training data using rolling team profiles."""
    from app.db.nba_advanced import NBAGameAdvancedStats

    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            return await _load_sport_game_training_data_impl(
                db, date_start, date_end,
                sport_code="NBA", stats_model=NBAGameAdvancedStats,
                rolling_window=rolling_window,
            )

    return await _load_sport_game_training_data_impl(
        db, date_start, date_end,
        sport_code="NBA", stats_model=NBAGameAdvancedStats,
        rolling_window=rolling_window,
    )


# ---------------------------------------------------------------------------
# NHL game training data
# ---------------------------------------------------------------------------


async def _load_nhl_game_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load NHL game training data using rolling team profiles."""
    from app.db.nhl_advanced import NHLGameAdvancedStats

    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            return await _load_sport_game_training_data_impl(
                db, date_start, date_end,
                sport_code="NHL", stats_model=NHLGameAdvancedStats,
                rolling_window=rolling_window,
            )

    return await _load_sport_game_training_data_impl(
        db, date_start, date_end,
        sport_code="NHL", stats_model=NHLGameAdvancedStats,
        rolling_window=rolling_window,
    )


# ---------------------------------------------------------------------------
# NCAAB game training data
# ---------------------------------------------------------------------------


async def _load_ncaab_game_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load NCAAB game training data using rolling team profiles."""
    from app.db.ncaab_advanced import NCAABGameAdvancedStats

    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            return await _load_sport_game_training_data_impl(
                db, date_start, date_end,
                sport_code="NCAAB", stats_model=NCAABGameAdvancedStats,
                rolling_window=rolling_window,
            )

    return await _load_sport_game_training_data_impl(
        db, date_start, date_end,
        sport_code="NCAAB", stats_model=NCAABGameAdvancedStats,
        rolling_window=rolling_window,
    )


# ---------------------------------------------------------------------------
# NFL game training data
# ---------------------------------------------------------------------------


async def _load_nfl_game_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load NFL game training data using rolling team profiles."""
    from app.db.nfl_advanced import NFLGameAdvancedStats

    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            return await _load_sport_game_training_data_impl(
                db, date_start, date_end,
                sport_code="NFL", stats_model=NFLGameAdvancedStats,
                rolling_window=rolling_window,
            )

    return await _load_sport_game_training_data_impl(
        db, date_start, date_end,
        sport_code="NFL", stats_model=NFLGameAdvancedStats,
        rolling_window=rolling_window,
    )
