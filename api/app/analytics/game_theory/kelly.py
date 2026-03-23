"""Kelly Criterion bet sizing.

Given a model probability and sportsbook odds, computes the optimal fraction
of bankroll to wager.  Supports full, half, and quarter Kelly variants.

Integrates with the existing EV pipeline — accepts the same probability and
odds formats used throughout the fairbet system.
"""

from __future__ import annotations

import logging

from .types import KellyResult

logger = logging.getLogger(__name__)


def american_to_decimal(american: float) -> float:
    """Convert American odds to decimal odds."""
    if american >= 100:
        return (american / 100.0) + 1.0
    elif american <= -100:
        return (100.0 / abs(american)) + 1.0
    else:
        raise ValueError(f"Invalid American odds: {american}")


def kelly_fraction(model_prob: float, decimal_odds: float) -> float:
    """Compute the full Kelly fraction.

    Formula: f* = (p * b - q) / b
    where p = win probability, q = 1-p, b = net odds (decimal - 1).

    Returns 0.0 when there is no edge (negative Kelly).
    """
    if model_prob <= 0.0 or model_prob >= 1.0:
        return 0.0
    if decimal_odds <= 1.0:
        return 0.0

    b = decimal_odds - 1.0  # net payout per dollar wagered
    q = 1.0 - model_prob
    f = (model_prob * b - q) / b
    return max(f, 0.0)


def compute_kelly(
    model_prob: float,
    american_odds: float,
    bankroll: float = 1000.0,
    variant: str = "half",
    max_fraction: float = 0.25,
) -> KellyResult:
    """Compute optimal wager size using the Kelly Criterion.

    Args:
        model_prob: Model's estimated true probability of the outcome (0-1).
        american_odds: Sportsbook odds in American format.
        bankroll: Total bankroll available.
        variant: ``"full"``, ``"half"``, or ``"quarter"`` Kelly.
        max_fraction: Cap on the fraction to prevent ruin (default 25%).

    Returns:
        KellyResult with sizing details.

    Raises:
        ValueError: If ``variant`` is not one of the accepted values.
    """
    if variant not in ("full", "half", "quarter"):
        raise ValueError(f"variant must be 'full', 'half', or 'quarter', got '{variant}'")

    decimal_odds = american_to_decimal(american_odds)
    implied_prob = 1.0 / decimal_odds

    edge = model_prob - implied_prob
    full = kelly_fraction(model_prob, decimal_odds)
    half = full / 2.0
    quarter = full / 4.0

    fractions = {"full": full, "half": half, "quarter": quarter}
    chosen = min(fractions[variant], max_fraction)
    wager = round(chosen * bankroll, 2)

    return KellyResult(
        edge=round(edge, 6),
        kelly_fraction=round(full, 6),
        half_kelly=round(half, 6),
        quarter_kelly=round(quarter, 6),
        recommended_wager=wager,
        bankroll=bankroll,
        model_prob=model_prob,
        implied_prob=round(implied_prob, 6),
        american_odds=american_odds,
        decimal_odds=round(decimal_odds, 4),
        kelly_variant=variant,
    )


def compute_kelly_batch(
    bets: list[dict],
    bankroll: float = 1000.0,
    variant: str = "half",
    max_fraction: float = 0.25,
    max_total_exposure: float = 0.50,
) -> list[KellyResult]:
    """Compute Kelly sizing for multiple independent bets.

    Scales wagers down proportionally if total exposure exceeds
    ``max_total_exposure``.

    Args:
        bets: List of dicts with keys ``model_prob`` and ``american_odds``.
        bankroll: Total bankroll.
        variant: Kelly variant.
        max_fraction: Per-bet cap.
        max_total_exposure: Total bankroll fraction cap across all bets.

    Returns:
        List of KellyResult, one per bet, with wagers possibly scaled.
    """
    results = [
        compute_kelly(
            model_prob=b["model_prob"],
            american_odds=b["american_odds"],
            bankroll=bankroll,
            variant=variant,
            max_fraction=max_fraction,
        )
        for b in bets
    ]

    # Filter to positive-edge bets
    positive = [r for r in results if r.edge > 0]
    if not positive:
        return results

    total_fraction = sum(
        {"full": r.kelly_fraction, "half": r.half_kelly, "quarter": r.quarter_kelly}[variant]
        for r in positive
    )

    if total_fraction > max_total_exposure:
        scale = max_total_exposure / total_fraction
        scaled = []
        for r in results:
            if r.edge > 0:
                frac = {"full": r.kelly_fraction, "half": r.half_kelly, "quarter": r.quarter_kelly}[variant]
                new_wager = round(min(frac * scale, max_fraction) * bankroll, 2)
                scaled.append(KellyResult(
                    edge=r.edge,
                    kelly_fraction=r.kelly_fraction,
                    half_kelly=r.half_kelly,
                    quarter_kelly=r.quarter_kelly,
                    recommended_wager=new_wager,
                    bankroll=r.bankroll,
                    model_prob=r.model_prob,
                    implied_prob=r.implied_prob,
                    american_odds=r.american_odds,
                    decimal_odds=r.decimal_odds,
                    kelly_variant=variant,
                ))
            else:
                scaled.append(r)
        return scaled

    return results
