"""Data loading for analytics training tasks.

Loads historical game and plate-appearance training data from
the database, building rolling team/player profiles for use as
model features. Supports MLB, NBA, NHL, NCAAB, and NFL game models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.tasks._training_data_game import (
    _load_nba_game_training_data,
    _load_ncaab_game_training_data,
    _load_nfl_game_training_data,
    _load_nhl_game_training_data,
)
from app.tasks._training_data_mlb_game import _load_mlb_game_training_data
from app.tasks._training_data_pa import _derive_pa_outcome  # noqa: F401

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
