"""EV confidence scoring functions.

Provides confidence factors that modulate how much trust to place in
an EV estimate based on probability level, Pinnacle alignment, book
spread, and extrapolation distance.
"""

from __future__ import annotations

import math


def probability_confidence(true_prob: float) -> float:
    """Confidence decay for low-probability outcomes.

    Below 25% true probability, confidence decays as sqrt(p / 0.25).
    This penalizes EV estimates for extreme longshots where small
    devig errors produce large EV percentage swings.

    Args:
        true_prob: True (no-vig) probability of the outcome (0-1).

    Returns:
        Confidence factor between 0.0 and 1.0.
    """
    if true_prob >= 0.25:
        return 1.0
    if true_prob <= 0:
        return 0.0
    return math.sqrt(true_prob / 0.25)


def pinnacle_alignment_factor(fair_prob: float, pinnacle_implied: float) -> float:
    """Confidence factor based on vig gap between fair and Pinnacle implied.

    A small gap means Pinnacle has low vig on this side — the devig is
    reliable. A large gap (> 4%) indicates unusually high vig, suggesting
    Pinnacle may be uncertain about this market.

    Args:
        fair_prob: Devigged true probability (0-1).
        pinnacle_implied: Pinnacle's raw (vigged) implied probability (0-1).

    Returns:
        1.0 for gap <= 2%, 0.85 for gap <= 4%, 0.7 for gap > 4%.
    """
    gap = abs(fair_prob - pinnacle_implied)
    if gap <= 0.02:
        return 1.0
    if gap <= 0.04:
        return 0.85
    return 0.7


def book_spread_factor(book_implieds: list[float]) -> float:
    """Confidence decay when one book is a pricing outlier.

    Compares the most generous book (lowest implied prob = best odds for bettor)
    against the median of all non-sharp books. Large spread indicates one book
    is an outlier rather than genuine market-wide value.
    """
    if len(book_implieds) < 2:
        return 0.80  # Thin market — inherently less reliable
    sorted_probs = sorted(book_implieds)
    n = len(sorted_probs)
    mid = n // 2
    median = sorted_probs[mid] if n % 2 == 1 else (sorted_probs[mid - 1] + sorted_probs[mid]) / 2.0
    spread = abs(sorted_probs[0] - median)
    if spread <= 0.03:
        return 1.0
    if spread <= 0.06:
        return 0.85
    if spread <= 0.10:
        return 0.70
    return 0.55


def extrapolation_distance_factor(n_half_points: float) -> float:
    """Numeric confidence factor based on extrapolation distance.

    Reduces confidence as the logit-space extrapolation extends further
    from the reference line.

    Args:
        n_half_points: Number of half-points from the reference line.

    Returns:
        Confidence factor between 0.70 and 0.95.
    """
    abs_hp = abs(n_half_points)
    if abs_hp <= 2:
        return 0.90
    if abs_hp <= 4:
        return 0.80
    return 0.65
