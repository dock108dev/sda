"""Filter stale non-sharp books from EV computation.

Drops non-sharp books whose observed_at trails the sharp book by more than
STALE_BOOK_MAX_LAG_SECONDS within the same bet entry. This prevents inflated
EV from stale outlier prices (e.g., BetMGM at -110 when the market has moved
to -125+).
"""

from __future__ import annotations

import logging
from typing import Any

from ...services.ev_config import STALE_BOOK_MAX_LAG_SECONDS

logger = logging.getLogger(__name__)


def filter_stale_books(
    bets_map: dict[tuple, dict[str, Any]],
    sharp_books: set[str],
    max_lag_seconds: int = STALE_BOOK_MAX_LAG_SECONDS,
) -> dict[tuple, dict[str, Any]]:
    """Remove non-sharp books whose observed_at is stale relative to the sharp book.

    For each bet entry, finds the sharp book's observed_at timestamp and drops
    any non-sharp book more than ``max_lag_seconds`` behind it.

    If no sharp book is present (e.g., player props using median consensus),
    the most recent book's timestamp is used as the reference instead, so
    books that are lagging behind the market still get dropped.

    Args:
        bets_map: Mapping of bet keys to bet dicts (each with a ``books`` list
            of ``{"book": str, "price": float, "observed_at": datetime}``).
        sharp_books: Set of book names considered sharp (e.g., ``{"Pinnacle"}``).
        max_lag_seconds: Maximum allowed lag in seconds before a book is dropped.

    Returns:
        The same ``bets_map`` with stale books removed from each entry's
        ``books`` list.
    """
    total_dropped = 0

    for key, bet in bets_map.items():
        books = bet["books"]

        # Find the latest sharp book timestamp in this bet
        sharp_ts = None
        for b in books:
            if b["book"] in sharp_books:
                ts = b["observed_at"]
                if sharp_ts is None or ts > sharp_ts:
                    sharp_ts = ts

        # When no sharp book is present (e.g., player props using median
        # consensus), fall back to the most recent book's timestamp as the
        # reference.  This catches a stale line at one book when the rest of
        # the market has already moved — the main source of phantom +40% edges.
        ref_ts = max(b["observed_at"] for b in books) if sharp_ts is None else sharp_ts

        fresh: list[dict[str, Any]] = []
        for b in books:
            if b["book"] in sharp_books:
                fresh.append(b)
                continue

            lag = (ref_ts - b["observed_at"]).total_seconds()
            if lag > max_lag_seconds:
                total_dropped += 1
                logger.info(
                    "stale_book_dropped",
                    extra={
                        "bet_key": str(key),
                        "book": b["book"],
                        "lag_seconds": round(lag, 1),
                        "ref_observed_at": ref_ts.isoformat(),
                        "book_observed_at": b["observed_at"].isoformat(),
                        "ref_source": "sharp" if sharp_ts else "newest_book",
                    },
                )
            else:
                fresh.append(b)

        bet["books"] = fresh

    if total_dropped:
        logger.info(
            "stale_books_filter_summary",
            extra={"total_dropped": total_dropped},
        )

    return bets_map
