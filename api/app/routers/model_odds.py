"""Model odds API endpoint.

Serves the sim-derived model odds decision framework for MLB games,
combining sim predictions, market data, calibration, and uncertainty.

Distinct from FairBet (which derives fair odds from cross-book Pinnacle devig).
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/model-odds", tags=["model-odds"])

# Cache for the calibrator (loaded once per process)
_calibrator_cache: dict[str, Any] = {}


def _get_calibrator(sport: str = "mlb"):
    """Load the most recent calibration model, cached per-sport."""
    from app.analytics.calibration.calibrator import SimCalibrator

    if sport in _calibrator_cache:
        return _calibrator_cache[sport]

    artifact_dir = Path("artifacts/calibration")
    if not artifact_dir.exists():
        return None

    # Find most recent artifact for this sport
    pattern = f"{sport}_calibrator_*.joblib"
    artifacts = sorted(artifact_dir.glob(pattern), reverse=True)
    if not artifacts:
        return None

    try:
        cal = SimCalibrator()
        cal.load(artifacts[0])
        _calibrator_cache[sport] = cal
        logger.info("calibrator_loaded_for_model_odds", extra={"path": str(artifacts[0])})
        return cal
    except Exception:
        logger.warning("calibrator_load_failed", exc_info=True)
        return None


@router.get("/mlb")
async def get_model_odds_mlb(
    date: str | None = Query(default=None, description="Game date (YYYY-MM-DD)"),
    game_id: int | None = Query(default=None, description="Specific game ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get model odds analysis for MLB games.

    Returns per-game decision framework with:
    - True probability and model line
    - Conservative probability and target entry
    - Confidence band and uncertainty scoring
    - Kelly sizing and play classification
    """
    from app.analytics.calibration.uncertainty import compute_uncertainty
    from app.db.analytics import AnalyticsPredictionOutcome
    from app.db.odds import FairbetGameOddsWork
    from app.services.ev import american_to_implied, remove_vig
    from app.services.model_odds import compute_model_odds

    game_date = date or str(date_type.today())

    # 1. Get most recent prediction per game_id (deduplicated at DB level)
    # Uses a subquery to find the max created_at per game_id, avoiding
    # pulling all rows and deduplicating in Python.
    from sqlalchemy import func as sa_func

    latest_sq = (
        select(
            AnalyticsPredictionOutcome.game_id,
            sa_func.max(AnalyticsPredictionOutcome.id).label("max_id"),
        )
        .where(AnalyticsPredictionOutcome.sport == "mlb")
    )
    if game_id:
        latest_sq = latest_sq.where(AnalyticsPredictionOutcome.game_id == game_id)
    else:
        latest_sq = latest_sq.where(AnalyticsPredictionOutcome.game_date == game_date)
    latest_sq = latest_sq.group_by(AnalyticsPredictionOutcome.game_id).subquery()

    pred_stmt = (
        select(AnalyticsPredictionOutcome)
        .join(latest_sq, AnalyticsPredictionOutcome.id == latest_sq.c.max_id)
    )
    pred_result = await db.execute(pred_stmt)
    predictions = list(pred_result.scalars().all())

    if not predictions:
        return {"games": [], "date": game_date, "count": 0}

    # 2. Get current market odds from FairBet work table
    game_ids = [p.game_id for p in predictions]
    market_stmt = (
        select(FairbetGameOddsWork)
        .where(
            FairbetGameOddsWork.game_id.in_(game_ids),
            FairbetGameOddsWork.market_key.in_(["h2h", "moneyline"]),
        )
    )
    market_result = await db.execute(market_stmt)
    market_rows = list(market_result.scalars().all())

    # Index market data by game_id → list of (selection_key, book, price)
    market_by_game: dict[int, list[dict]] = {}
    for row in market_rows:
        market_by_game.setdefault(row.game_id, []).append({
            "selection_key": row.selection_key,
            "book": row.book,
            "price": row.price,
        })

    # 3. Load calibrator
    calibrator = _get_calibrator("mlb")

    # 4. Compute model odds for each game
    games_output: list[dict] = []
    for pred in predictions:
        raw_wp = pred.predicted_home_wp
        calibrated_wp = calibrator.calibrate(raw_wp) if calibrator else raw_wp

        # Match market entries to home/away sides
        market_entries = market_by_game.get(pred.game_id, [])
        best_home_price, best_home_book, best_away_price, best_away_book = (
            _find_best_prices(market_entries, pred.home_team, pred.away_team)
        )

        # Devig from a single book's pair (avoids cross-book distortion)
        market_home_wp = _devig_same_book_pair(
            market_entries,
            _slugify(pred.home_team),
            _slugify(pred.away_team),
            american_to_implied,
            remove_vig,
        )
        market_disagreement = (
            abs(calibrated_wp - market_home_wp)
            if market_home_wp is not None else None
        )

        # Compute uncertainty
        uncertainty = compute_uncertainty(
            sim_wp_std_dev=pred.sim_wp_std_dev,
            profile_games_home=pred.profile_games_home,
            profile_games_away=pred.profile_games_away,
            market_disagreement=market_disagreement,
            pitcher_data_quality=True,
        )

        # Compute model odds for home side
        home_decision = compute_model_odds(
            calibrated_wp=calibrated_wp,
            market_price=best_home_price,
            uncertainty=uncertainty,
        )

        # Compute model odds for away side
        away_calibrated = 1.0 - calibrated_wp
        away_decision = compute_model_odds(
            calibrated_wp=away_calibrated,
            market_price=best_away_price,
            uncertainty=uncertainty,
        )

        games_output.append({
            "game_id": pred.game_id,
            "game_date": pred.game_date,
            "home_team": pred.home_team,
            "away_team": pred.away_team,
            "sim_raw_home_wp": round(raw_wp, 4),
            "calibrated": calibrator is not None,
            "home": _decision_to_dict(home_decision, best_home_price, best_home_book),
            "away": _decision_to_dict(away_decision, best_away_price, best_away_book),
        })

    return {
        "games": games_output,
        "date": game_date,
        "count": len(games_output),
        "calibrator_loaded": calibrator is not None,
    }


def _slugify(text: str) -> str:
    """Convert team name to the slug format used in FairBet selection keys.

    Mirrors scraper/sports_scraper/odds/fairbet.py:slugify() so that
    "New York Yankees" → "new_york_yankees" matches "team:new_york_yankees".
    """
    import re
    slug = text.lower()
    slug = re.sub(r"[\s\-]+", "_", slug)
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug


def _find_best_prices(
    market_entries: list[dict],
    home_team: str,
    away_team: str,
) -> tuple[float | None, str | None, float | None, str | None]:
    """Match market entries to home/away sides using slugified team names.

    FairBet selection_keys are formatted as "team:{slug}" (e.g.
    "team:new_york_yankees"). We slugify the team names and check
    for that pattern rather than doing raw substring matching.
    """
    home_prices = []
    away_prices = []
    home_slug = _slugify(home_team)
    away_slug = _slugify(away_team)

    for entry in market_entries:
        sel = entry["selection_key"]
        # selection_key is "team:{slug}" for moneyline bets
        if f"team:{home_slug}" == sel:
            home_prices.append(entry)
        elif f"team:{away_slug}" == sel:
            away_prices.append(entry)

    best_home_price = max((e["price"] for e in home_prices), default=None)
    best_away_price = max((e["price"] for e in away_prices), default=None)

    best_home_book = next(
        (e["book"] for e in home_prices if e["price"] == best_home_price), None,
    ) if best_home_price is not None else None
    best_away_book = next(
        (e["book"] for e in away_prices if e["price"] == best_away_price), None,
    ) if best_away_price is not None else None

    return best_home_price, best_home_book, best_away_price, best_away_book


def _devig_same_book_pair(
    market_entries: list[dict],
    home_slug: str,
    away_slug: str,
    american_to_implied_fn,
    remove_vig_fn,
) -> float | None:
    """Devig a home/away moneyline pair from the same book.

    Cross-book devig produces invalid probabilities because each book's
    vig structure is different. We find a single book that has both sides
    and devig that pair. Prefers Pinnacle, falls back to any complete pair.
    """
    # Group by book → collect (side, price)
    by_book: dict[str, dict[str, float]] = {}
    for entry in market_entries:
        sel = entry["selection_key"]
        book = entry["book"]
        by_book.setdefault(book, {})[sel] = entry["price"]

    # Prefer Pinnacle if it has both sides
    preferred_order = ["Pinnacle"] + [b for b in by_book if b != "Pinnacle"]

    for book in preferred_order:
        sides = by_book.get(book, {})
        home_price = sides.get(f"team:{home_slug}")
        away_price = sides.get(f"team:{away_slug}")
        if home_price is not None and away_price is not None:
            try:
                imp_h = american_to_implied_fn(home_price)
                imp_a = american_to_implied_fn(away_price)
                return remove_vig_fn([imp_h, imp_a])[0]
            except ValueError:
                continue

    return None


def _decision_to_dict(
    decision,
    raw_market_price: float | None,
    best_book: str | None,
) -> dict:
    """Convert ModelOddsDecision to API response dict.

    Uses the raw market price directly instead of round-tripping
    through probability conversion, which avoids rounding drift.
    """
    return {
        "p_true": decision.p_true,
        "p_conservative": decision.p_conservative,
        "model_line": decision.fair_line_mid,
        "model_line_conservative": decision.fair_line_conservative,
        "model_range": [decision.fair_line_low, decision.fair_line_high],
        "current_market": {
            "best_price": raw_market_price,
            "best_book": best_book,
        } if raw_market_price is not None else None,
        "edge_vs_conservative": decision.edge_vs_market,
        "target_entry": decision.target_bet_line,
        "strong_play_at": decision.strong_bet_line,
        "kelly_half": decision.half_kelly,
        "kelly_quarter": decision.quarter_kelly,
        "confidence": decision.confidence_tier,
        "decision": decision.decision,
        "required_edge": decision.required_edge,
    }
