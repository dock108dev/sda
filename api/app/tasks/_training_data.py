"""Data loading for analytics training tasks.

Loads historical game and plate-appearance training data from
the database, building rolling team/player profiles for use as
model features. Supports MLB, NBA, NHL, NCAAB, and NFL game models.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from app.tasks._training_data_pa import _derive_pa_outcome  # noqa: F401
from app.tasks._training_helpers import build_rolling_profile, get_game_score
from app.utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc

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
    sport_lower = sport.lower()

    # Game model type is supported for all sports
    if model_type == "game":
        _game_loaders = {
            "mlb": _load_mlb_game_training_data,
            "nba": _load_nba_game_training_data,
            "nhl": _load_nhl_game_training_data,
            "ncaab": _load_ncaab_game_training_data,
            "nfl": _load_nfl_game_training_data,
        }
        loader = _game_loaders.get(sport_lower)
        if loader is None:
            raise ValueError(
                f"Unsupported sport for game model: {sport}. "
                f"Supported: {', '.join(sorted(_game_loaders))}."
            )
        return await loader(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    # Non-game model types are MLB-only
    if sport_lower != "mlb":
        raise ValueError(
            f"Unsupported sport '{sport}' for model_type '{model_type}'. "
            f"Only 'mlb' supports non-game model types."
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

    if model_type == "pitch":
        return await _load_mlb_pitch_training_data(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    if model_type == "batted_ball":
        return await _load_mlb_batted_ball_training_data(
            date_start, date_end, rolling_window=rolling_window, db=db
        )

    raise ValueError(
        f"Unsupported model_type: {model_type}. "
        f"Supported types: 'game', 'plate_appearance', 'player_plate_appearance', "
        f"'pitch', 'batted_ball'."
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

    # Parse date strings to ET-aware UTC boundaries so late-night ET
    # games aren't misattributed to the wrong calendar day.
    dt_start = start_of_et_day_utc(date.fromisoformat(date_start)) if date_start else None
    dt_end = end_of_et_day_utc(date.fromisoformat(date_end)) if date_end else None

    train_stmt = (
        select(SportsGame)
        .where(SportsGame.status == "final")
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

    # --- Load starting pitcher data for each game ---
    from app.db.mlb_advanced import MLBPitcherGameStats

    pitcher_stmt = (
        select(MLBPitcherGameStats)
        .where(MLBPitcherGameStats.game_id.in_([g.id for g in training_games]))
    )
    pitcher_result = await db.execute(pitcher_stmt)
    all_pitcher_stats = pitcher_result.scalars().all()

    # Group by game, find starter (pitcher with most IP)
    pitchers_by_game: dict[int, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for ps in all_pitcher_stats:
        pitchers_by_game[ps.game_id][ps.team_id].append(ps)

    def _get_starter_metrics(game_id: int, team_id: int) -> dict:
        """Get rolling metrics for the starting pitcher of a game."""
        team_pitchers = pitchers_by_game.get(game_id, {}).get(team_id, [])
        if not team_pitchers:
            return {}
        # Starter = pitcher with most IP in this game
        starter = max(team_pitchers, key=lambda p: getattr(p, "innings_pitched", 0) or 0)
        return {
            "k_rate": getattr(starter, "k_rate", None),
            "bb_rate": getattr(starter, "bb_rate", None),
            "era": getattr(starter, "era", None),
            "whip": getattr(starter, "whip", None),
            "innings_pitched": getattr(starter, "innings_pitched", None),
        }

    # --- Load closing lines for market probability feature ---
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

    # Build market WP per game
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

        # Starter pitcher metrics for this game
        home_starter = _get_starter_metrics(game.id, home_stats.team_id)
        away_starter = _get_starter_metrics(game.id, away_stats.team_id)

        # Market probability (devigged Pinnacle lines)
        market = market_wp_by_game.get(game.id, {"home_wp": 0.5, "away_wp": 0.5})

        records.append({
            "home_profile": {"metrics": home_profile},
            "away_profile": {"metrics": away_profile},
            "home_starter_profile": {"metrics": home_starter},
            "away_starter_profile": {"metrics": away_starter},
            "market_profile": {"metrics": market},
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
            "games_with_market": len(market_wp_by_game),
            "games_with_pitchers": sum(1 for g in training_games if g.id in pitchers_by_game),
        },
    )
    return records


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


async def _load_mlb_pitch_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load MLB pitch-outcome training data using MLBPitchDatasetBuilder."""
    from app.analytics.datasets.mlb_pitch_dataset import MLBPitchDatasetBuilder

    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            builder = MLBPitchDatasetBuilder(db)
            return await builder.build(
                date_start=date_start,
                date_end=date_end,
                rolling_window=rolling_window,
            )

    builder = MLBPitchDatasetBuilder(db)
    return await builder.build(
        date_start=date_start,
        date_end=date_end,
        rolling_window=rolling_window,
    )


async def _load_mlb_batted_ball_training_data(
    date_start: str | None,
    date_end: str | None,
    *,
    rolling_window: int = 30,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Load MLB batted ball training data using MLBBattedBallDatasetBuilder."""
    from app.analytics.datasets.mlb_batted_ball_dataset import (
        MLBBattedBallDatasetBuilder,
    )

    if db is None:
        from app.db import get_async_session

        async with get_async_session() as db:
            builder = MLBBattedBallDatasetBuilder(db)
            return await builder.build(
                date_start=date_start,
                date_end=date_end,
                rolling_window=rolling_window,
            )

    builder = MLBBattedBallDatasetBuilder(db)
    return await builder.build(
        date_start=date_start,
        date_end=date_end,
        rolling_window=rolling_window,
    )
