"""Calibration dataset builder.

Joins sim predictions to closing market lines and actual outcomes
to produce the training dataset for probability calibration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Market keys that represent moneyline / head-to-head
_MONEYLINE_KEYS = frozenset({"h2h", "moneyline"})


@dataclass(frozen=True, slots=True)
class CalibrationRow:
    """Single row in the calibration dataset."""

    game_id: int
    game_date: str
    home_team: str
    away_team: str
    sim_home_wp: float
    sim_wp_std_dev: float | None
    sim_iterations: int | None
    market_close_home_wp: float | None
    actual_home_win: bool
    brier_score: float


@dataclass(frozen=True, slots=True)
class DatasetStats:
    """Summary statistics for a calibration dataset."""

    total_predictions: int
    with_market_data: int
    without_market_data: int
    date_range: tuple[str, str] | None
    coverage_pct: float


async def build_calibration_dataset(
    db: AsyncSession,
    sport: str = "mlb",
    *,
    date_start: str | None = None,
    date_end: str | None = None,
    require_market: bool = False,
) -> list[CalibrationRow]:
    """Build a calibration dataset by joining predictions to closing lines.

    Args:
        db: Async database session.
        sport: Sport code (default "mlb").
        date_start: Optional start date filter (YYYY-MM-DD).
        date_end: Optional end date filter (YYYY-MM-DD).
        require_market: If True, only include rows with market data.

    Returns:
        List of CalibrationRow objects ready for calibrator training.
    """
    from app.db.analytics import AnalyticsPredictionOutcome
    from app.db.odds import ClosingLine
    from app.services.ev import american_to_implied, remove_vig

    # 1. Fetch resolved predictions
    stmt = (
        select(AnalyticsPredictionOutcome)
        .where(
            AnalyticsPredictionOutcome.outcome_recorded_at.isnot(None),
            AnalyticsPredictionOutcome.sport == sport,
            AnalyticsPredictionOutcome.brier_score.isnot(None),
        )
        .order_by(AnalyticsPredictionOutcome.game_date.asc())
    )
    if date_start:
        stmt = stmt.where(AnalyticsPredictionOutcome.game_date >= date_start)
    if date_end:
        stmt = stmt.where(AnalyticsPredictionOutcome.game_date <= date_end)

    result = await db.execute(stmt)
    predictions = list(result.scalars().all())

    if not predictions:
        return []

    # 2. Batch-load closing lines for these games (Pinnacle moneyline)
    game_ids = list({p.game_id for p in predictions})
    cl_stmt = (
        select(ClosingLine)
        .where(
            ClosingLine.game_id.in_(game_ids),
            ClosingLine.market_key.in_(_MONEYLINE_KEYS),
            ClosingLine.provider == "Pinnacle",
        )
    )
    cl_result = await db.execute(cl_stmt)
    closing_lines = list(cl_result.scalars().all())

    # Index closing lines by game_id → list of (selection, price)
    cl_by_game: dict[int, list[tuple[str, float]]] = {}
    for cl in closing_lines:
        cl_by_game.setdefault(cl.game_id, []).append(
            (cl.selection, cl.price_american)
        )

    # 3. For each prediction, try to pair with devigged closing line
    rows: list[CalibrationRow] = []
    for pred in predictions:
        market_close_home_wp = _devig_closing_lines(
            cl_by_game.get(pred.game_id, []),
            pred.home_team,
            pred.away_team,
            remove_vig,
            american_to_implied,
        )

        if require_market and market_close_home_wp is None:
            continue

        rows.append(
            CalibrationRow(
                game_id=pred.game_id,
                game_date=pred.game_date or "",
                home_team=pred.home_team,
                away_team=pred.away_team,
                sim_home_wp=pred.predicted_home_wp,
                sim_wp_std_dev=pred.sim_wp_std_dev,
                sim_iterations=pred.sim_iterations,
                market_close_home_wp=market_close_home_wp,
                actual_home_win=bool(pred.home_win_actual),
                brier_score=pred.brier_score,
            )
        )

    return rows


def _devig_closing_lines(
    lines: list[tuple[str, float]],
    home_team: str,
    away_team: str,
    remove_vig_fn: Any,
    american_to_implied_fn: Any,
) -> float | None:
    """Devig Pinnacle closing moneyline to extract home win probability.

    Expects exactly 2 lines (home + away). If we can't identify which
    is home vs away, or only have 1 side, returns None.
    """
    if len(lines) < 2:
        return None

    # Try to identify home/away sides by matching team names
    home_price: float | None = None
    away_price: float | None = None

    home_lower = home_team.lower()
    away_lower = away_team.lower()

    for selection, price in lines:
        sel_lower = selection.lower()
        if home_lower in sel_lower or sel_lower in home_lower:
            home_price = price
        elif away_lower in sel_lower or sel_lower in away_lower:
            away_price = price

    if home_price is None or away_price is None:
        # Fallback: assume first two lines are the two sides
        # Use the first match for each side based on order
        if len(lines) >= 2:
            home_price = lines[0][1]
            away_price = lines[1][1]
        else:
            return None

    try:
        implied_home = american_to_implied_fn(home_price)
        implied_away = american_to_implied_fn(away_price)
        true_probs = remove_vig_fn([implied_home, implied_away])
        return true_probs[0]
    except (ValueError, ZeroDivisionError):
        return None


async def get_dataset_stats(
    db: AsyncSession,
    sport: str = "mlb",
) -> DatasetStats:
    """Get summary statistics for the calibration dataset."""
    rows = await build_calibration_dataset(db, sport)
    if not rows:
        return DatasetStats(
            total_predictions=0,
            with_market_data=0,
            without_market_data=0,
            date_range=None,
            coverage_pct=0.0,
        )

    with_market = sum(1 for r in rows if r.market_close_home_wp is not None)
    dates = [r.game_date for r in rows if r.game_date]
    date_range = (min(dates), max(dates)) if dates else None

    return DatasetStats(
        total_predictions=len(rows),
        with_market_data=with_market,
        without_market_data=len(rows) - with_market,
        date_range=date_range,
        coverage_pct=round(with_market / len(rows) * 100, 1) if rows else 0.0,
    )
