"""EV eligibility evaluation logic.

Determines whether EV can be computed for a given (league, market_category)
pair by checking strategy existence, sharp book presence, freshness, and
minimum book counts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .ev_config import (
    INCLUDED_BOOKS,
    EligibilityResult,
    EVStrategyConfig,
    get_strategy,
    market_confidence_tier,
)

logger = logging.getLogger(__name__)


def _find_sharp_entry(
    books: list[dict],
    eligible_sharp_books: tuple[str, ...],
) -> dict | None:
    """Find the first sharp book entry in a list of book dicts.

    Args:
        books: List of {"book": str, "price": float, "observed_at": datetime, ...}.
        eligible_sharp_books: Tuple of eligible sharp book display names.

    Returns:
        The first matching book dict, or None.
    """
    for entry in books:
        if entry["book"] in eligible_sharp_books:
            return entry
    return None


def evaluate_ev_eligibility(
    league_code: str,
    market_category: str,
    side_a_books: list[dict],
    side_b_books: list[dict],
    now: datetime | None = None,
) -> EligibilityResult:
    """Evaluate whether EV can be computed for a two-way market.

    Checks (in order):
    1. Strategy exists for (league, market_category)
    2. Sharp book present on both sides
    3. Sharp book observed_at within max_reference_staleness_seconds of now
    4. >= min_qualifying_books non-excluded books per side

    Args:
        league_code: League code (e.g., "NBA").
        market_category: Market category (e.g., "mainline").
        side_a_books: Book entries for side A.
        side_b_books: Book entries for side B.
        now: Current time (defaults to utcnow, injectable for testing).

    Returns:
        EligibilityResult with eligible=True or disabled_reason explaining why not.
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Strategy exists?
    config = get_strategy(league_code, market_category)
    if config is None:
        return EligibilityResult(
            eligible=False,
            strategy_config=None,
            disabled_reason="no_strategy",
            ev_method=None,
            confidence_tier=None,
        )

    # Branch: consensus strategies skip sharp book checks
    if config.strategy_name == "median_consensus":
        return _evaluate_consensus_eligibility(
            config, side_a_books, side_b_books,
        )

    # 2. Sharp book present on both sides?
    sharp_a = _find_sharp_entry(side_a_books, config.eligible_sharp_books)
    sharp_b = _find_sharp_entry(side_b_books, config.eligible_sharp_books)

    if sharp_a is None or sharp_b is None:
        return EligibilityResult(
            eligible=False,
            strategy_config=config,
            disabled_reason="reference_missing",
            ev_method=config.strategy_name,
            confidence_tier=None,
        )

    # 3. Freshness check
    sharp_a_observed = sharp_a.get("observed_at")
    sharp_b_observed = sharp_b.get("observed_at")

    if sharp_a_observed is not None and sharp_b_observed is not None:
        # Use the older of the two timestamps
        oldest = min(sharp_a_observed, sharp_b_observed)
        age_seconds = (now - oldest).total_seconds()
        if age_seconds > config.max_reference_staleness_seconds:
            return EligibilityResult(
                eligible=False,
                strategy_config=config,
                disabled_reason="reference_stale",
                ev_method=config.strategy_name,
                confidence_tier=None,
            )

    # 4. Minimum qualifying books per side (must be in INCLUDED_BOOKS)
    qualifying_a = sum(1 for b in side_a_books if b["book"] in INCLUDED_BOOKS)
    qualifying_b = sum(1 for b in side_b_books if b["book"] in INCLUDED_BOOKS)

    # Non-sharp book count = total included minus sharp books
    non_sharp_a = sum(1 for b in side_a_books if b["book"] in INCLUDED_BOOKS and b["book"] not in config.eligible_sharp_books)
    non_sharp_b = sum(1 for b in side_b_books if b["book"] in INCLUDED_BOOKS and b["book"] not in config.eligible_sharp_books)
    non_sharp_count = min(non_sharp_a, non_sharp_b)

    if (
        qualifying_a < config.min_qualifying_books
        or qualifying_b < config.min_qualifying_books
    ):
        return EligibilityResult(
            eligible=False,
            strategy_config=config,
            disabled_reason="insufficient_books",
            ev_method=config.strategy_name,
            confidence_tier=market_confidence_tier(non_sharp_count),
        )

    return EligibilityResult(
        eligible=True,
        strategy_config=config,
        disabled_reason=None,
        ev_method=config.strategy_name,
        confidence_tier=market_confidence_tier(non_sharp_count),
    )


def _evaluate_consensus_eligibility(
    config: EVStrategyConfig,
    side_a_books: list[dict],
    side_b_books: list[dict],
) -> EligibilityResult:
    """Evaluate eligibility for median consensus strategy.

    Instead of requiring a sharp book, requires min_qualifying_books
    common books present on both sides simultaneously.
    """
    a_book_names = {b["book"] for b in side_a_books if b["book"] in INCLUDED_BOOKS}
    b_book_names = {b["book"] for b in side_b_books if b["book"] in INCLUDED_BOOKS}
    common_books = a_book_names & b_book_names
    common_count = len(common_books)

    # Non-sharp count = all included books (no sharp books in consensus)
    non_sharp_a = len(a_book_names)
    non_sharp_b = len(b_book_names)
    non_sharp_count = min(non_sharp_a, non_sharp_b)

    if common_count < config.min_qualifying_books:
        return EligibilityResult(
            eligible=False,
            strategy_config=config,
            disabled_reason="insufficient_books",
            ev_method=config.strategy_name,
            confidence_tier=market_confidence_tier(non_sharp_count),
        )

    return EligibilityResult(
        eligible=True,
        strategy_config=config,
        disabled_reason=None,
        ev_method=config.strategy_name,
        confidence_tier=market_confidence_tier(non_sharp_count),
    )
