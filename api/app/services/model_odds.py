"""Model odds decision engine.

Combines calibrated probability, market price, and uncertainty
to produce the complete decision framework: conservative model line,
target entry, Kelly sizing, and play classification.

This is the sim-derived pricing layer — distinct from FairBet which
derives fair odds from cross-book Pinnacle devig.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analytics.calibration.uncertainty import (
    TAX_FRICTION_BUFFER,
    TIER_REQUIRED_EDGE,
    UncertaintyResult,
    apply_uncertainty,
)
from app.services.ev import american_to_implied, implied_to_american


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModelOddsDecision:
    """Complete model-odds output for one side of a game."""

    # Core probabilities
    p_true: float
    p_market: float | None
    p_conservative: float

    # Confidence band
    p_low: float
    p_high: float
    uncertainty_score: float
    confidence_tier: str

    # Prices (American odds)
    fair_line_mid: float
    fair_line_conservative: float
    fair_line_low: float
    fair_line_high: float
    target_bet_line: float
    strong_bet_line: float

    # Value assessment
    edge_vs_market: float | None
    kelly_fraction: float
    half_kelly: float
    quarter_kelly: float

    # Decision
    decision: str  # "no_play" | "lean" | "playable" | "strong_play"

    # Metadata
    required_edge: float
    uncertainty_factors: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_model_odds(
    *,
    calibrated_wp: float,
    market_price: float | None = None,
    uncertainty: UncertaintyResult,
) -> ModelOddsDecision:
    """Compute the full model-odds decision framework for one side.

    Args:
        calibrated_wp: Calibrated true probability for this side (0-1).
        market_price: Current best market price in American odds (or None).
        uncertainty: Uncertainty assessment from compute_uncertainty().

    Returns:
        ModelOddsDecision with all pricing, sizing, and decision fields.
    """
    # Step 1: Apply uncertainty → conservative probability + bands
    core = apply_uncertainty(calibrated_wp, uncertainty)

    # Step 2: Market implied probability
    p_market: float | None = None
    if market_price is not None:
        try:
            p_market = american_to_implied(market_price)
        except ValueError:
            p_market = None

    # Step 3: Required edge threshold
    base_edge = TIER_REQUIRED_EDGE.get(uncertainty.confidence_tier, 0.05)
    required_edge = base_edge + TAX_FRICTION_BUFFER

    # Step 4: Target bet line and strong bet line
    # Target = conservative probability shifted by required_edge toward 0.5.
    # For favorites (>0.5): subtract edge (lower probability = less negative odds).
    # For underdogs (<0.5): add edge (higher probability = higher positive odds).
    # Clamp so the line never crosses 0.5 (an underdog target shouldn't
    # become a favorite line, and vice versa).
    is_favorite = core.p_conservative > 0.5
    if is_favorite:
        target_p = max(0.501, core.p_conservative - required_edge)
    else:
        target_p = min(0.499, core.p_conservative + required_edge)
    target_p = max(0.01, min(0.99, target_p))
    target_bet_line = implied_to_american(target_p) if 0.01 < target_p < 0.99 else 0.0

    # Strong = target + additional 2% edge (same direction, same clamp)
    if is_favorite:
        strong_p = max(0.501, target_p - 0.02)
    else:
        strong_p = min(0.499, target_p + 0.02)
    strong_p = max(0.01, min(0.99, strong_p))
    strong_bet_line = implied_to_american(strong_p) if 0.01 < strong_p < 0.99 else 0.0

    # Step 5: Edge vs market
    edge_vs_market: float | None = None
    if p_market is not None:
        edge_vs_market = round(core.p_conservative - p_market, 4)

    # Step 6: Kelly sizing
    kelly_fraction = 0.0
    if market_price is not None and p_market is not None:
        kelly_fraction = _kelly_criterion(core.p_conservative, market_price)

    half_kelly = round(kelly_fraction / 2, 6)
    quarter_kelly = round(kelly_fraction / 4, 6)

    # Step 7: Decision classification
    decision = _classify_decision(
        p_conservative=core.p_conservative,
        p_market=p_market,
        market_price=market_price,
        target_bet_line=target_bet_line,
        confidence_tier=uncertainty.confidence_tier,
    )

    # Weighted uncertainty score (0-1), consistent with tier assignment
    # in compute_uncertainty() which uses the same weights.
    from app.analytics.calibration.uncertainty import UNCERTAINTY_WEIGHTS
    factors = uncertainty.factors
    uncertainty_score = round(
        sum(factors.get(k, 0) * w for k, w in UNCERTAINTY_WEIGHTS.items()), 4,
    )

    return ModelOddsDecision(
        p_true=core.p_true,
        p_market=p_market,
        p_conservative=core.p_conservative,
        p_low=core.p_low,
        p_high=core.p_high,
        uncertainty_score=uncertainty_score,
        confidence_tier=uncertainty.confidence_tier,
        fair_line_mid=core.fair_line_mid,
        fair_line_conservative=core.fair_line_conservative,
        fair_line_low=core.fair_line_low,
        fair_line_high=core.fair_line_high,
        target_bet_line=round(target_bet_line, 1),
        strong_bet_line=round(strong_bet_line, 1),
        edge_vs_market=edge_vs_market,
        kelly_fraction=round(kelly_fraction, 6),
        half_kelly=half_kelly,
        quarter_kelly=quarter_kelly,
        decision=decision,
        required_edge=round(required_edge, 4),
        uncertainty_factors=factors,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kelly_criterion(p_conservative: float, market_price: float) -> float:
    """Compute Kelly fraction for a bet.

    Kelly = (p * b - q) / b
    where p = probability, q = 1-p, b = net decimal payout.

    Returns 0.0 if edge is non-positive.
    """
    try:
        if market_price >= 100:
            b = market_price / 100.0
        elif market_price <= -100:
            b = 100.0 / abs(market_price)
        else:
            return 0.0
    except (ZeroDivisionError, ValueError):
        return 0.0

    q = 1.0 - p_conservative
    kelly = (p_conservative * b - q) / b if b > 0 else 0.0
    return max(0.0, kelly)


def _classify_decision(
    *,
    p_conservative: float,
    p_market: float | None,
    market_price: float | None,
    target_bet_line: float,
    confidence_tier: str,
) -> str:
    """Classify the betting decision based on edge and confidence.

    Returns one of: "no_play", "lean", "playable", "strong_play".
    """
    if confidence_tier == "very_low":
        return "no_play"

    if market_price is None or p_market is None:
        return "no_play"

    # Edge = conservative probability - market implied probability
    edge = p_conservative - p_market

    if edge <= 0:
        return "no_play"

    # Is market price better than target entry?
    # For favorites (p > 0.5): market price should be less negative than target
    # For underdogs (p < 0.5): market price should be more positive than target
    market_is_better_than_target = _price_beats_threshold(
        market_price, target_bet_line, p_conservative > 0.5,
    )

    if market_is_better_than_target and confidence_tier in ("high", "medium"):
        # Strong play: beats target with good confidence, AND edge > 5%
        if edge > 0.05 and confidence_tier == "high":
            return "strong_play"
        return "playable"

    if edge > 0:
        return "lean"

    return "no_play"


def _price_beats_threshold(
    market_price: float,
    threshold_price: float,
    is_favorite: bool,
) -> bool:
    """Check if market price is better than the threshold for the bettor.

    "Better" means: for a bet on the favorite side, a less negative (or
    more positive) price; for an underdog, a more positive price.
    """
    # Higher American odds = better for the bettor in all cases
    # -110 is better than -150 (less juice)
    # +130 is better than +110 (more payout)
    return market_price > threshold_price
