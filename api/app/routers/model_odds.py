"""Model odds API endpoint.

Serves the sim-derived model odds decision framework for MLB games,
combining sim predictions, market data, calibration, and uncertainty.

Distinct from FairBet (which derives fair odds from cross-book Pinnacle devig).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

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
    date: str = Query(default=None, description="Game date (YYYY-MM-DD)"),
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

    game_date = date or str(__import__("datetime").date.today())

    # 1. Get predictions for this date
    pred_stmt = (
        select(AnalyticsPredictionOutcome)
        .where(AnalyticsPredictionOutcome.sport == "mlb")
    )
    if game_id:
        pred_stmt = pred_stmt.where(AnalyticsPredictionOutcome.game_id == game_id)
    else:
        pred_stmt = pred_stmt.where(AnalyticsPredictionOutcome.game_date == game_date)

    # Get the most recent prediction per game_id
    pred_stmt = pred_stmt.order_by(AnalyticsPredictionOutcome.created_at.desc())
    pred_result = await db.execute(pred_stmt)
    all_preds = list(pred_result.scalars().all())

    # Deduplicate: keep most recent per game_id
    seen_games: set[int] = set()
    predictions: list = []
    for p in all_preds:
        if p.game_id not in seen_games:
            seen_games.add(p.game_id)
            predictions.append(p)

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

        # Find best market prices for each side
        market_entries = market_by_game.get(pred.game_id, [])
        home_prices = []
        away_prices = []
        for entry in market_entries:
            sel = entry["selection_key"].lower()
            if pred.home_team.lower() in sel or sel in pred.home_team.lower():
                home_prices.append(entry)
            elif pred.away_team.lower() in sel or sel in pred.away_team.lower():
                away_prices.append(entry)

        best_home_price = max((e["price"] for e in home_prices), default=None)
        best_away_price = max((e["price"] for e in away_prices), default=None)
        best_home_book = next(
            (e["book"] for e in home_prices if e["price"] == best_home_price),
            None,
        ) if best_home_price is not None else None
        best_away_book = next(
            (e["book"] for e in away_prices if e["price"] == best_away_price),
            None,
        ) if best_away_price is not None else None

        # Market implied probability for disagreement calculation
        market_home_wp = None
        if best_home_price is not None and best_away_price is not None:
            try:
                imp_h = american_to_implied(best_home_price)
                imp_a = american_to_implied(best_away_price)
                devigged = remove_vig([imp_h, imp_a])
                market_home_wp = devigged[0]
            except ValueError:
                pass

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
            pitcher_data_quality=True,  # TODO: derive from feature_snapshot
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
            "home": _decision_to_dict(home_decision, best_home_book),
            "away": _decision_to_dict(away_decision, best_away_book),
        })

    return {
        "games": games_output,
        "date": game_date,
        "count": len(games_output),
        "calibrator_loaded": calibrator is not None,
    }


def _decision_to_dict(decision, best_book: str | None) -> dict:
    """Convert ModelOddsDecision to API response dict."""
    return {
        "p_true": decision.p_true,
        "p_conservative": decision.p_conservative,
        "model_line": decision.fair_line_mid,
        "model_line_conservative": decision.fair_line_conservative,
        "model_range": [decision.fair_line_low, decision.fair_line_high],
        "current_market": {
            "best_price": decision.p_market and round(
                __import__("app.services.ev", fromlist=["implied_to_american"]).implied_to_american(decision.p_market), 1
            ),
            "best_book": best_book,
        } if decision.p_market else None,
        "edge_vs_conservative": decision.edge_vs_market,
        "target_entry": decision.target_bet_line,
        "strong_play_at": decision.strong_bet_line,
        "kelly_half": decision.half_kelly,
        "kelly_quarter": decision.quarter_kelly,
        "confidence": decision.confidence_tier,
        "decision": decision.decision,
        "required_edge": decision.required_edge,
    }
