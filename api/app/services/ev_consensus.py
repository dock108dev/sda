"""Median consensus EV calculation for player props.

Instead of anchoring to a single sharp book (Pinnacle), this module
individually devigs each book's over/under pair and takes the median
as the "synthetic sharp" fair value. This is more appropriate for
player props where no single book is meaningfully sharper than others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .ev import (
    INCLUDED_BOOKS,
    EVComputeResult,
    EVStrategyConfig,
    american_to_implied,
    calculate_ev,
    market_confidence_tier,
    remove_vig,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConsensusMetadata:
    """Metadata from median consensus EV computation."""

    consensus_book_count: int = 0
    consensus_iqr: float = 0.0
    per_book_fair_probs: dict[str, float] = field(default_factory=dict)


def _median(values: list[float]) -> float:
    """Return median of a list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _iqr(values: list[float]) -> float:
    """Return interquartile range of a list of floats."""
    if len(values) < 4:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    lower = s[:mid]
    upper = s[mid:] if n % 2 == 0 else s[mid + 1:]
    q1 = _median(lower)
    q3 = _median(upper)
    return q3 - q1


def consensus_agreement_factor(devigged_probs: list[float]) -> float:
    """Confidence factor based on IQR of per-book devigged probs.

    IQR < 2% → 1.0 (strong agreement)
    IQR < 4% → 0.85 (moderate agreement)
    IQR >= 4% → 0.70 (weak agreement)

    Args:
        devigged_probs: List of per-book devigged true probabilities.

    Returns:
        Confidence factor between 0.70 and 1.0.
    """
    if len(devigged_probs) < 4:
        return 0.85  # Not enough books for meaningful IQR
    iqr_val = _iqr(devigged_probs)
    if iqr_val < 0.02:
        return 1.0
    if iqr_val < 0.04:
        return 0.85
    return 0.70


def compute_ev_median_consensus(
    side_a_books: list[dict],
    side_b_books: list[dict],
    strategy_config: EVStrategyConfig,
) -> tuple[EVComputeResult, ConsensusMetadata | None]:
    """Compute EV using median consensus of individually devigged books.

    For each book present on BOTH sides: devig that book's pair individually
    using Shin's method. Take the median of all per-book devigged true_prob_a
    values as the fair probability. Calculate EV for each book against the
    median fair probability.

    Args:
        side_a_books: Book entries for side A.
        side_b_books: Book entries for side B.
        strategy_config: The consensus strategy configuration.

    Returns:
        (EVComputeResult, ConsensusMetadata) tuple.
    """
    # Build lookup: book_name -> price for each side
    a_prices: dict[str, float] = {}
    for entry in side_a_books:
        if entry["book"] in INCLUDED_BOOKS:
            a_prices[entry["book"]] = entry["price"]

    b_prices: dict[str, float] = {}
    for entry in side_b_books:
        if entry["book"] in INCLUDED_BOOKS:
            b_prices[entry["book"]] = entry["price"]

    # Find books present on both sides
    common_books = sorted(set(a_prices.keys()) & set(b_prices.keys()))

    # Devig each book individually
    per_book_probs: dict[str, float] = {}
    for book_name in common_books:
        try:
            impl_a = american_to_implied(a_prices[book_name])
            impl_b = american_to_implied(b_prices[book_name])
            true_probs = remove_vig([impl_a, impl_b])
            per_book_probs[book_name] = true_probs[0]
        except (ValueError, ZeroDivisionError):
            logger.warning(
                "consensus_devig_skip",
                extra={"book": book_name, "price_a": a_prices[book_name], "price_b": b_prices[book_name]},
            )

    if not per_book_probs:
        # Can't compute — return empty result
        return (
            EVComputeResult(
                annotated_a=[{**e, "is_sharp": False, "implied_prob": None, "ev_percent": None, "true_prob": None} for e in side_a_books],
                annotated_b=[{**e, "is_sharp": False, "implied_prob": None, "ev_percent": None, "true_prob": None} for e in side_b_books],
            ),
            None,
        )

    # Take median as fair probability
    prob_values = list(per_book_probs.values())
    fair_prob_a = _median(prob_values)
    fair_prob_b = 1.0 - fair_prob_a

    # Compute IQR for agreement metadata
    iqr_val = _iqr(prob_values) if len(prob_values) >= 4 else 0.0

    # Sanity check: fair prob divergence
    fair_odds_suspect = False
    all_implied_a = []
    all_implied_b = []
    for entry in side_a_books:
        try:
            all_implied_a.append(american_to_implied(entry["price"]))
        except ValueError:
            logger.debug("skipped_invalid_price_consensus", extra={"price": entry["price"], "book": entry.get("book")})
    for entry in side_b_books:
        try:
            all_implied_b.append(american_to_implied(entry["price"]))
        except ValueError:
            logger.debug("skipped_invalid_price_consensus", extra={"price": entry["price"], "book": entry.get("book")})

    if all_implied_a and all_implied_b:
        median_impl_a = _median(sorted(all_implied_a))
        median_impl_b = _median(sorted(all_implied_b))
        divergence = max(
            abs(fair_prob_a - median_impl_a),
            abs(fair_prob_b - median_impl_b),
        )
        if divergence > strategy_config.max_fair_prob_divergence:
            fair_odds_suspect = True

    # Annotate both sides
    annotated_a = []
    for entry in side_a_books:
        result = {**entry, "is_sharp": False}
        try:
            result["implied_prob"] = american_to_implied(entry["price"])
            result["ev_percent"] = round(calculate_ev(entry["price"], fair_prob_a), 2)
            result["true_prob"] = round(fair_prob_a, 4)
        except ValueError:
            result["implied_prob"] = None
            result["ev_percent"] = None
            result["true_prob"] = None
        annotated_a.append(result)

    annotated_b = []
    for entry in side_b_books:
        result = {**entry, "is_sharp": False}
        try:
            result["implied_prob"] = american_to_implied(entry["price"])
            result["ev_percent"] = round(calculate_ev(entry["price"], fair_prob_b), 2)
            result["true_prob"] = round(fair_prob_b, 4)
        except ValueError:
            result["implied_prob"] = None
            result["ev_percent"] = None
            result["true_prob"] = None
        annotated_b.append(result)

    # Non-sharp book count for confidence tier (all books are non-sharp in consensus)
    non_sharp_a = sum(1 for b in side_a_books if b["book"] in INCLUDED_BOOKS)
    non_sharp_b = sum(1 for b in side_b_books if b["book"] in INCLUDED_BOOKS)
    tier = market_confidence_tier(min(non_sharp_a, non_sharp_b))

    metadata = ConsensusMetadata(
        consensus_book_count=len(per_book_probs),
        consensus_iqr=round(iqr_val, 4),
        per_book_fair_probs=per_book_probs,
    )

    ev_result = EVComputeResult(
        annotated_a=annotated_a,
        annotated_b=annotated_b,
        true_prob_a=fair_prob_a,
        true_prob_b=fair_prob_b,
        reference_price_a=None,
        reference_price_b=None,
        ev_method="median_consensus",
        confidence_tier=tier,
        fair_odds_suspect=fair_odds_suspect,
    )

    return ev_result, metadata
