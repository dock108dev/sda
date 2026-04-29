"""Structured odds table builder for game detail view.

Groups raw odds entries into a structured table with opening/closing lines,
best-line flags, and display-ready formatting — so clients don't need to
duplicate grouping/sorting/best-line detection logic.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from ..db.odds import SportsGameOdds
from .derived_metrics import _fmt_american_odds

# Market type display order
_MARKET_ORDER = {"spread": 0, "total": 1, "moneyline": 2}

_MARKET_DISPLAY: dict[str, str] = {
    "spread": "Spread",
    "total": "Total",
    "moneyline": "Moneyline",
}


def build_odds_table(
    odds: Sequence[SportsGameOdds],
) -> list[dict[str, Any]]:
    """Build a structured odds table from raw odds entries.

    Groups mainline odds by market_type, separates opening vs closing lines,
    and flags the best line per side within closing lines.

    Args:
        odds: Raw odds entries from the database.

    Returns:
        List of OddsTableGroup dicts ordered: spread, total, moneyline.
        Each group contains openingLines and closingLines arrays.
    """
    if not odds:
        return []

    # Filter to mainline only
    mainline = [o for o in odds if (o.market_category or "mainline") == "mainline"]
    if not mainline:
        return []

    # Group by market_type
    by_market: dict[str, list[SportsGameOdds]] = defaultdict(list)
    for o in mainline:
        by_market[o.market_type].append(o)

    result: list[dict[str, Any]] = []

    for market_type in sorted(by_market.keys(), key=lambda m: _MARKET_ORDER.get(m, 99)):
        entries = by_market[market_type]

        opening_lines: list[dict[str, Any]] = []
        closing_lines: list[dict[str, Any]] = []

        for o in entries:
            line_dict: dict[str, Any] = {
                "book": o.book,
                "side": o.side,
                "line": o.line,
                "price": o.price,
                "priceDisplay": _fmt_american_odds(o.price),
                "isClosingLine": o.is_closing_line,
                "isBest": False,
            }
            if o.is_closing_line:
                closing_lines.append(line_dict)
            else:
                opening_lines.append(line_dict)

        # Flag best price per side within closing lines
        # "Best" means the most favorable price for the bettor
        sides: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        for line in closing_lines:
            sides[line["side"]].append(line)

        for side_lines in sides.values():
            if not side_lines:
                continue
            # Higher price is better for the bettor in American odds
            best = max(
                side_lines,
                key=lambda line: line["price"] if line["price"] is not None else float("-inf"),
            )
            best["isBest"] = True

        result.append({
            "marketType": market_type,
            "marketDisplay": _MARKET_DISPLAY.get(market_type, market_type.title()),
            "openingLines": opening_lines,
            "closingLines": closing_lines,
        })

    return result
