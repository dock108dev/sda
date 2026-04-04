"""Expected Value (EV) calculation engine.

Computes true probabilities by devigging sharp book lines (Pinnacle by default),
then calculates EV% for every book's price on each market.

Uses the eligibility gate from ev_config to determine whether EV can be computed
for a given (league, market_category) pair.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from .ev_config import (
    INCLUDED_BOOKS,
    EVStrategyConfig,
    market_confidence_tier,
)
from .ev_confidence import (  # noqa: F401 — re-exported
    book_spread_factor,
    extrapolation_distance_factor,
    pinnacle_alignment_factor,
    probability_confidence,
)
from .ev_eligibility import (  # noqa: F401 — re-exported
    _evaluate_consensus_eligibility,
    _find_sharp_entry,
    evaluate_ev_eligibility,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EVComputeResult:
    """Structured return from compute_ev_for_market()."""

    annotated_a: list[dict] = field(default_factory=list)
    annotated_b: list[dict] = field(default_factory=list)
    true_prob_a: float | None = None
    true_prob_b: float | None = None
    reference_price_a: float | None = None
    reference_price_b: float | None = None
    ev_method: str | None = None
    confidence_tier: str | None = None
    fair_odds_suspect: bool = False


def american_to_implied(price: float) -> float:
    """Convert American odds to implied probability (0-1 range).

    Args:
        price: American odds (e.g., -110, +150)

    Returns:
        Implied probability as a float between 0 and 1.
    """
    if price >= 100:
        return 100.0 / (price + 100.0)
    elif price <= -100:
        return abs(price) / (abs(price) + 100.0)
    else:
        raise ValueError(f"Invalid American odds: {price} (must be <= -100 or >= +100)")


def implied_to_american(prob: float) -> float:
    """Convert implied probability (0-1) to American odds.

    Args:
        prob: Implied probability as a float between 0 and 1.

    Returns:
        American odds (e.g., -300, +300). Returns 0.0 for degenerate inputs.
    """
    if prob <= 0 or prob >= 1:
        return 0.0
    if prob >= 0.5:
        return -(prob / (1 - prob)) * 100.0
    else:
        return ((1 - prob) / prob) * 100.0


def shin_add_vig(true_probs: list[float], overround: float = 1.02) -> list[float]:
    """Add vig using Shin's model (inverse of remove_vig).

    Given true probabilities summing to ~1.0, produces implied probabilities
    summing to *overround*.  Allocates more vig to longshots than favorites,
    mirroring how sharp books actually price markets.

    Falls back to proportional scaling when overround <= 1.

    Args:
        true_probs: List of true (no-vig) probabilities.
        overround: Target sum of implied probabilities (e.g., 1.02 for 2% vig).

    Returns:
        List of implied (vigged) probabilities.
    """
    if overround <= 1.0:
        return [p * overround for p in true_probs]

    z = 1.0 - 1.0 / overround

    result: list[float] = []
    for p in true_probs:
        a = 2.0 * (1.0 - z) * p + z
        q = math.sqrt(a * a - z * z) / (2.0 * (1.0 - z))
        result.append(q)
    return result


def prob_to_vigged_american(true_prob: float, overround: float = 1.02) -> float:
    """Convert true probability to estimated vigged American price.

    Uses Shin's model to add vig (consistent with how remove_vig strips it),
    allocating more vig to the longshot side.

    Assumes Pinnacle-typical ~2% total overround by default.

    Args:
        true_prob: True probability (0-1).
        overround: Target total overround (default 1.02 = ~2% vig).

    Returns:
        Estimated vigged American odds.
    """
    vigged_probs = shin_add_vig([true_prob, 1.0 - true_prob], overround)
    vigged_prob = max(0.001, min(0.999, vigged_probs[0]))
    return implied_to_american(vigged_prob)


def remove_vig(implied_probs: list[float]) -> list[float]:
    """Remove vig using Shin's method (accounts for favorite-longshot bias).

    Shin's model distributes more vig correction to longshots, producing
    fairer true probabilities than simple additive normalization.

    Falls back to additive normalization when overround <= 0.

    Args:
        implied_probs: List of implied probabilities for all outcomes in a market.

    Returns:
        List of true (no-vig) probabilities summing to ~1.0.
    """
    total = sum(implied_probs)
    if total <= 0:
        return implied_probs

    # z = informed trading proportion (Shin's parameter)
    z = 1.0 - 1.0 / total

    # Fall back to additive when there's no meaningful overround
    if z <= 0:
        return [p / total for p in implied_probs]

    result: list[float] = []
    for q in implied_probs:
        numerator = math.sqrt(z ** 2 + 4.0 * (1.0 - z) * (q ** 2) / total) - z
        denominator = 2.0 * (1.0 - z)
        result.append(numerator / denominator)
    return result


def calculate_ev(book_price: float, true_prob: float) -> float:
    """Calculate expected value percentage for a bet.

    EV% = (true_prob * net_profit) - ((1 - true_prob) * stake)
    Simplified: EV% = (decimal_odds * true_prob) - 1

    Args:
        book_price: American odds offered by the book.
        true_prob: True probability of the outcome (0-1).

    Returns:
        EV as a percentage (e.g., 3.5 means +3.5% EV).
    """
    # Convert to decimal odds
    if book_price >= 100:
        decimal_odds = (book_price / 100.0) + 1.0
    elif book_price <= -100:
        decimal_odds = (100.0 / abs(book_price)) + 1.0
    else:
        raise ValueError(
            f"Invalid American odds: {book_price}. Must be >= +100 or <= -100."
        )

    return (decimal_odds * true_prob - 1.0) * 100.0


def _median(sorted_values: list[float]) -> float:
    """Return the median of an already-sorted list of floats."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def _annotate_side(
    books: list[dict],
    sharp_books: set[str],
    true_prob: float | None,
) -> list[dict]:
    """Annotate a list of book entries with implied_prob, ev_percent, is_sharp.

    Entries with invalid American odds (between -100 and +100) are included
    in the output but with implied_prob and ev_percent set to None.
    """
    annotated: list[dict] = []
    for entry in books:
        result = {**entry}
        result["is_sharp"] = entry["book"] in sharp_books
        try:
            result["implied_prob"] = american_to_implied(entry["price"])
            if true_prob is not None:
                result["ev_percent"] = round(calculate_ev(entry["price"], true_prob), 2)
                result["true_prob"] = round(true_prob, 4)
            else:
                result["ev_percent"] = None
                result["true_prob"] = None
        except ValueError:
            logger.warning(
                "invalid_book_price_skipped",
                extra={"book": entry["book"], "price": entry["price"]},
            )
            result["implied_prob"] = None
            result["ev_percent"] = None
            result["true_prob"] = None
        annotated.append(result)
    return annotated


def compute_ev_for_market(
    side_a_books: list[dict],
    side_b_books: list[dict],
    strategy_config: EVStrategyConfig,
) -> EVComputeResult:
    """Compute EV for all books on both sides of a two-way market.

    Finds the sharp book on each side, devigs to get true probabilities,
    then annotates every book's entry with EV%.

    Args:
        side_a_books: List of {"book": str, "price": float, ...} for side A.
        side_b_books: List of {"book": str, "price": float, ...} for side B.
        strategy_config: The strategy configuration to use.

    Returns:
        EVComputeResult with annotated sides and metadata.
    """
    sharp_books = set(strategy_config.eligible_sharp_books)

    # Find sharp prices on each side
    sharp_a_price: float | None = None
    sharp_b_price: float | None = None

    for entry in side_a_books:
        if entry["book"] in sharp_books:
            sharp_a_price = entry["price"]
            break

    for entry in side_b_books:
        if entry["book"] in sharp_books:
            sharp_b_price = entry["price"]
            break

    # Compute true probabilities if we have both sides from sharp book
    true_prob_a: float | None = None
    true_prob_b: float | None = None

    if sharp_a_price is not None and sharp_b_price is not None:
        try:
            implied_a = american_to_implied(sharp_a_price)
            implied_b = american_to_implied(sharp_b_price)
            true_probs = remove_vig([implied_a, implied_b])
            true_prob_a = true_probs[0]
            true_prob_b = true_probs[1]
        except ValueError:
            logger.warning(
                "invalid_sharp_price_skipped",
                extra={
                    "sharp_a_price": sharp_a_price,
                    "sharp_b_price": sharp_b_price,
                },
            )

    # Annotate both sides (bad prices handled per-entry inside _annotate_side)
    annotated_a = _annotate_side(side_a_books, sharp_books, true_prob_a)
    annotated_b = _annotate_side(side_b_books, sharp_books, true_prob_b)

    # Sanity check: compare devigged fair probs against median implied prob
    fair_odds_suspect = False
    if true_prob_a is not None and true_prob_b is not None:
        implied_probs_a: list[float] = []
        implied_probs_b: list[float] = []
        _skipped = 0
        for entry in side_a_books:
            try:
                implied_probs_a.append(american_to_implied(entry["price"]))
            except ValueError:
                _skipped += 1
        for entry in side_b_books:
            try:
                implied_probs_b.append(american_to_implied(entry["price"]))
            except ValueError:
                _skipped += 1
        if _skipped:
            logger.debug(
                "ev_sanity_check_invalid_odds_skipped",
                extra={"skipped": _skipped},
            )

        if implied_probs_a and implied_probs_b:
            median_implied_a = _median(sorted(implied_probs_a))
            median_implied_b = _median(sorted(implied_probs_b))

            divergence = max(
                abs(true_prob_a - median_implied_a),
                abs(true_prob_b - median_implied_b),
            )
            if divergence > strategy_config.max_fair_prob_divergence:
                fair_odds_suspect = True

    # Non-sharp book count (min of both sides) for confidence tier
    sharp_set = set(strategy_config.eligible_sharp_books)
    non_sharp_a = sum(1 for b in side_a_books if b["book"] in INCLUDED_BOOKS and b["book"] not in sharp_set)
    non_sharp_b = sum(1 for b in side_b_books if b["book"] in INCLUDED_BOOKS and b["book"] not in sharp_set)
    tier = market_confidence_tier(min(non_sharp_a, non_sharp_b))

    return EVComputeResult(
        annotated_a=annotated_a,
        annotated_b=annotated_b,
        true_prob_a=true_prob_a,
        true_prob_b=true_prob_b,
        reference_price_a=sharp_a_price,
        reference_price_b=sharp_b_price,
        ev_method=strategy_config.strategy_name,
        confidence_tier=tier,
        fair_odds_suspect=fair_odds_suspect,
    )
