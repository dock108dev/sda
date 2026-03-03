"""Display-oriented helpers for FairBet odds.

Pure functions that compute human-readable labels from raw bet data,
so clients don't need to duplicate formatting/lookup logic.
"""

from __future__ import annotations

import math
from typing import Any

from .ev import american_to_implied, calculate_ev, implied_to_american
from .ev_config import (
    BOOK_ABBREVIATIONS,
    CONFIDENCE_DISPLAY_LABELS,
    FAIRBET_METHOD_DISPLAY_NAMES,
    FAIRBET_METHOD_EXPLANATIONS,
    MARKET_DISPLAY_NAMES,
)


def fair_american_odds(true_prob: float | None) -> int | None:
    """Convert true probability to display-ready American odds.

    Args:
        true_prob: Devigged true probability (0-1).

    Returns:
        Rounded American odds integer, or None if input is None/degenerate.
    """
    if true_prob is None:
        return None
    raw = implied_to_american(true_prob)
    if raw == 0.0:
        return None
    return round(raw)


def market_display_name(market_key: str) -> str:
    """Look up human-readable market name with fallback.

    Args:
        market_key: Raw market key (e.g., "player_points", "spreads").

    Returns:
        Display name (e.g., "Player Points", "Spread").
        Falls back to title-cased key with underscores replaced.
    """
    return MARKET_DISPLAY_NAMES.get(market_key, market_key.replace("_", " ").title())


def book_abbreviation(book_name: str) -> str:
    """Look up short book abbreviation with fallback.

    Args:
        book_name: Full book display name (e.g., "DraftKings").

    Returns:
        Abbreviation (e.g., "DK"). Falls back to first 3 chars uppercased.
    """
    return BOOK_ABBREVIATIONS.get(book_name, book_name[:3].upper())


def confidence_display_label(tier: str | None) -> str | None:
    """Map confidence tier to display label.

    Args:
        tier: Confidence tier string ("full", "decent", "thin").

    Returns:
        Display label ("Sharp", "Market", "Thin"), or None.
    """
    if tier is None:
        return None
    return CONFIDENCE_DISPLAY_LABELS.get(tier, tier.title())


def ev_method_display_name(method: str | None) -> str | None:
    """Map EV method to display name.

    Args:
        method: EV method string (e.g., "pinnacle_devig").

    Returns:
        Display name (e.g., "Pinnacle Devig"), or None.
    """
    if method is None:
        return None
    return FAIRBET_METHOD_DISPLAY_NAMES.get(method, method.replace("_", " ").title())


def ev_method_explanation(method: str | None) -> str | None:
    """Map EV method to short explanation.

    Args:
        method: EV method string (e.g., "pinnacle_devig").

    Returns:
        Explanation string, or None.
    """
    if method is None:
        return None
    return FAIRBET_METHOD_EXPLANATIONS.get(method)


def selection_display(
    selection_key: str,
    market_key: str,
    home_team: str | None = None,
    away_team: str | None = None,
    player_name: str | None = None,
    line_value: float | None = None,
) -> str:
    """Build a human-readable selection display name.

    Parses the selection_key parts to produce labels like:
    - "BOS -3.5" (team spread)
    - "Over 215.5" (game total)
    - "LeBron James Over 25.5" (player prop)
    - "BOS ML" (moneyline)

    Args:
        selection_key: Raw selection key (e.g., "team:bos:home", "total:over").
        market_key: Raw market key (e.g., "spreads", "player_points").
        home_team: Home team display name.
        away_team: Away team display name.
        player_name: Player name (for player props).
        line_value: Line value for display.

    Returns:
        Human-readable selection string.
    """
    if not selection_key:
        return market_display_name(market_key)

    parts = selection_key.split(":")

    # Player props: "player:{slug}:{over/under}"
    if parts[0] == "player" and len(parts) >= 3:
        side = parts[-1].title()  # "Over" or "Under"
        name = player_name or parts[1].replace("_", " ").title()
        if line_value is not None:
            return f"{name} {side} {line_value}"
        return f"{name} {side}"

    # Game totals: "total:{over/under}"
    if parts[0] == "total" and len(parts) == 2:
        side = parts[1].title()  # "Over" or "Under"
        if line_value is not None:
            return f"{side} {line_value}"
        return side

    # Team totals: "total:{team_slug}:{over/under}"
    if parts[0] == "total" and len(parts) == 3:
        team_slug = parts[1].replace("_", " ").title()
        side = parts[2].title()
        if line_value is not None:
            return f"{team_slug} {side} {line_value}"
        return f"{team_slug} {side}"

    # Team spread/ML: "team:{slug}" or "team:{slug}:{home/away}"
    if parts[0] == "team":
        # Resolve to actual team name if possible
        team_name = None
        if len(parts) >= 3:
            if parts[2] == "home" and home_team:
                team_name = home_team
            elif parts[2] == "away" and away_team:
                team_name = away_team
        if team_name is None:
            team_name = parts[1].replace("_", " ").upper() if len(parts) >= 2 else "Team"

        is_ml = "moneyline" in market_key.lower() or "h2h" in market_key.lower()
        if is_ml:
            return f"{team_name} ML"
        if line_value is not None:
            sign = "+" if line_value > 0 else ""
            return f"{team_name} {sign}{line_value}"
        return team_name

    # Fallback
    return selection_key.replace(":", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Explanation step builder
# ---------------------------------------------------------------------------

_DISABLED_REASON_LABELS: dict[str, str] = {
    "no_strategy": "No EV strategy for this market type",
    "reference_missing": "Sharp book reference not available",
    "reference_stale": "Sharp book reference is outdated",
    "insufficient_books": "Not enough books for reliable comparison",
    "fair_odds_outlier": "Fair odds diverge too far from market consensus",
    "entity_mismatch": "Cannot pair opposite sides of this market",
    "no_pair": "Opposite side of this market not found",
}


def _fmt_pct(value: float, decimals: int = 1) -> str:
    """Format a 0-1 probability as a percentage string (e.g., '52.4%')."""
    return f"{value * 100:.{decimals}f}%"


def _fmt_american(price: float) -> str:
    """Format American odds with a leading +/- sign."""
    rounded = round(price)
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _step(
    step_number: int,
    title: str,
    description: str,
    detail_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a single step dict."""
    return {
        "step_number": step_number,
        "title": title,
        "description": description,
        "detail_rows": detail_rows or [],
    }


def _row(label: str, value: str, *, is_highlight: bool = False) -> dict[str, Any]:
    return {"label": label, "value": value, "is_highlight": is_highlight}


def _build_ev_step(
    step_number: int,
    true_prob: float,
    best_book: str,
    best_book_price: float,
    best_ev_percent: float | None,
) -> dict[str, Any]:
    """Build the 'Calculate EV at best price' step."""
    # Decimal odds
    if best_book_price >= 100:
        decimal_odds = (best_book_price / 100.0) + 1.0
    else:
        decimal_odds = (100.0 / abs(best_book_price)) + 1.0

    profit_per_dollar = decimal_odds - 1.0
    ev_val = calculate_ev(best_book_price, true_prob)

    rows = [
        _row("Best price", f"{_fmt_american(best_book_price)} ({best_book})"),
        _row("Win", f"{_fmt_pct(true_prob)} x ${profit_per_dollar:.2f} profit = +${true_prob * profit_per_dollar:.4f}"),
        _row("Loss", f"{_fmt_pct(1 - true_prob)} x $1.00 risked = -${(1 - true_prob):.4f}"),
        _row("EV", f"{ev_val:+.2f}%", is_highlight=True),
    ]
    return _step(
        step_number,
        "Calculate EV at best price",
        "Expected value measures the average profit per dollar wagered at the best available price.",
        rows,
    )


def _build_pinnacle_devig_steps(
    *,
    reference_price: float,
    opposite_reference_price: float,
    true_prob: float,
    fair_odds: int | None,
    best_book: str | None,
    best_book_price: float | None,
    best_ev_percent: float | None,
) -> list[dict[str, Any]]:
    """Path 1: Pinnacle paired devig walkthrough."""
    implied_a = american_to_implied(reference_price)
    implied_b = american_to_implied(opposite_reference_price)
    total = implied_a + implied_b
    vig = total - 1.0
    z = 1.0 - 1.0 / total

    steps: list[dict[str, Any]] = []

    # Step 1: Convert odds to implied probability
    steps.append(_step(
        1,
        "Convert odds to implied probability",
        "Each side's American odds are converted to an implied win probability.",
        [
            _row("This side", f"{_fmt_american(reference_price)} \u2192 {_fmt_pct(implied_a)}"),
            _row("Other side", f"{_fmt_american(opposite_reference_price)} \u2192 {_fmt_pct(implied_b)}"),
            _row("Total", f"{_fmt_pct(total)}"),
        ],
    ))

    # Step 2: Identify the vig
    steps.append(_step(
        2,
        "Identify the vig",
        "The total implied probability exceeds 100% \u2014 the excess is the bookmaker's margin (vig).",
        [
            _row("Total implied", _fmt_pct(total)),
            _row("Should be", "100.0%"),
            _row("Vig (margin)", _fmt_pct(vig), is_highlight=True),
        ],
    ))

    # Step 3: Remove the vig (Shin's method)
    fair_odds_display = _fmt_american(implied_to_american(true_prob)) if true_prob else "N/A"
    steps.append(_step(
        3,
        "Remove the vig (Shin's method)",
        "Shin's method accounts for favorite-longshot bias, allocating more vig correction to longshots than favorites.",
        [
            _row("Shin parameter (z)", f"{z:.4f}"),
            _row("Formula", "p = (\u221a(z\u00b2 + 4(1\u2212z)q\u00b2) \u2212 z) / (2(1\u2212z))"),
            _row("Fair probability", _fmt_pct(true_prob), is_highlight=True),
            _row("Fair odds", fair_odds_display if fair_odds is None else _fmt_american(fair_odds)),
        ],
    ))

    # Step 4: EV at best price (only if best_book available)
    if best_book and best_book_price is not None and true_prob is not None:
        steps.append(_build_ev_step(4, true_prob, best_book, best_book_price, best_ev_percent))

    return steps


def _build_extrapolated_steps(
    *,
    reference_price: float,
    opposite_reference_price: float,
    true_prob: float,
    fair_odds: int | None,
    best_book: str | None,
    best_book_price: float | None,
    best_ev_percent: float | None,
    estimated_sharp_price: float | None,
    extrapolation_ref_line: float | None,
    extrapolation_distance: float | None,
) -> list[dict[str, Any]]:
    """Path 2: Pinnacle extrapolated walkthrough."""
    implied_a = american_to_implied(reference_price)
    implied_b = american_to_implied(opposite_reference_price)
    total = implied_a + implied_b
    vig = total - 1.0

    steps: list[dict[str, Any]] = []

    # Step 1: Convert reference line odds
    steps.append(_step(
        1,
        "Convert odds to implied probability",
        "The nearest Pinnacle line's odds are converted to implied probabilities.",
        [
            _row("This side", f"{_fmt_american(reference_price)} \u2192 {_fmt_pct(implied_a)}"),
            _row("Other side", f"{_fmt_american(opposite_reference_price)} \u2192 {_fmt_pct(implied_b)}"),
            _row("Total", f"{_fmt_pct(total)}"),
        ],
    ))

    # Step 2: Identify the vig
    steps.append(_step(
        2,
        "Identify the vig",
        "The total implied probability exceeds 100% \u2014 the excess is the bookmaker's margin (vig).",
        [
            _row("Total implied", _fmt_pct(total)),
            _row("Should be", "100.0%"),
            _row("Vig (margin)", _fmt_pct(vig), is_highlight=True),
        ],
    ))

    # Step 3: Extrapolate to target line
    rows: list[dict[str, Any]] = []
    if extrapolation_ref_line is not None:
        rows.append(_row("Reference line", str(extrapolation_ref_line)))
    if extrapolation_distance is not None:
        rows.append(_row("Distance", f"{extrapolation_distance} half-points"))
    if estimated_sharp_price is not None:
        rows.append(_row("Estimated sharp price", _fmt_american(estimated_sharp_price)))
    rows.append(_row("Fair probability", _fmt_pct(true_prob), is_highlight=True))
    fair_odds_display = _fmt_american(implied_to_american(true_prob)) if true_prob else "N/A"
    rows.append(_row("Fair odds", fair_odds_display if fair_odds is None else _fmt_american(fair_odds)))

    steps.append(_step(
        3,
        "Extrapolate to target line",
        "No exact Pinnacle match exists for this line. Fair odds are projected from the nearest reference line using logit-space interpolation.",
        rows,
    ))

    # Step 4: EV at best price
    if best_book and best_book_price is not None and true_prob is not None:
        steps.append(_build_ev_step(4, true_prob, best_book, best_book_price, best_ev_percent))

    return steps


def _build_median_consensus_steps(
    *,
    true_prob: float,
    fair_odds: int | None,
    best_book: str | None,
    best_book_price: float | None,
    best_ev_percent: float | None,
    per_book_fair_probs: dict[str, float] | None,
    consensus_iqr: float | None,
) -> list[dict[str, Any]]:
    """Path: Median consensus walkthrough for player props."""
    steps: list[dict[str, Any]] = []

    # Step 1: Collect book prices
    rows: list[dict[str, Any]] = []
    if per_book_fair_probs:
        rows.append(_row("Books contributing", str(len(per_book_fair_probs))))
        for book_name, prob in sorted(per_book_fair_probs.items()):
            rows.append(_row(book_name, _fmt_pct(prob)))
    steps.append(_step(
        1,
        "Devig each book individually",
        "Each book's over/under pair is devigged independently using Shin's method to find its implied fair probability.",
        rows,
    ))

    # Step 2: Take the median
    median_rows = [
        _row("Fair probability (median)", _fmt_pct(true_prob), is_highlight=True),
    ]
    if consensus_iqr is not None:
        median_rows.append(_row("IQR (agreement)", _fmt_pct(consensus_iqr)))
    fair_odds_display = _fmt_american(implied_to_american(true_prob)) if true_prob else "N/A"
    median_rows.append(_row("Fair odds", fair_odds_display if fair_odds is None else _fmt_american(fair_odds)))

    steps.append(_step(
        2,
        "Take median fair probability",
        "The median across all books is used as the consensus fair value, which is robust against individual book outliers.",
        median_rows,
    ))

    # Step 3: EV at best price
    if best_book and best_book_price is not None and true_prob is not None:
        steps.append(_build_ev_step(3, true_prob, best_book, best_book_price, best_ev_percent))

    return steps


def _build_fallback_steps(
    *,
    true_prob: float,
    fair_odds: int | None,
    best_book: str | None,
    best_book_price: float | None,
    best_ev_percent: float | None,
) -> list[dict[str, Any]]:
    """Path 3: Fallback when true_prob is known but method is unknown."""
    fair_odds_display = _fmt_american(implied_to_american(true_prob)) if true_prob else "N/A"
    steps: list[dict[str, Any]] = [
        _step(
            1,
            "Fair probability",
            "A fair probability was determined for this market.",
            [
                _row("Fair probability", _fmt_pct(true_prob), is_highlight=True),
                _row("Fair odds", fair_odds_display if fair_odds is None else _fmt_american(fair_odds)),
            ],
        ),
    ]
    if best_book and best_book_price is not None:
        steps.append(_build_ev_step(2, true_prob, best_book, best_book_price, best_ev_percent))
    return steps


def _build_not_available_step(ev_disabled_reason: str | None) -> list[dict[str, Any]]:
    """Path 4: Fair odds not available."""
    label = _DISABLED_REASON_LABELS.get(
        ev_disabled_reason or "", "Fair odds are not available for this market"
    )
    return [_step(1, "Fair odds not available", label)]


def build_explanation_steps(
    *,
    ev_method: str | None,
    ev_disabled_reason: str | None,
    true_prob: float | None,
    reference_price: float | None,
    opposite_reference_price: float | None,
    fair_odds: int | None,
    best_book: str | None,
    best_book_price: float | None,
    best_ev_percent: float | None,
    estimated_sharp_price: float | None,
    extrapolation_ref_line: float | None,
    extrapolation_distance: float | None,
    per_book_fair_probs: dict[str, float] | None = None,
    consensus_iqr: float | None = None,
) -> list[dict[str, Any]]:
    """Build the step-by-step explanation of how fair odds were derived.

    Returns a list of step dicts matching the ExplanationStep schema.
    All data is passed explicitly so this remains a pure function with
    no dependency on router-layer models.
    """
    if ev_disabled_reason:
        return _build_not_available_step(ev_disabled_reason)

    if ev_method == "median_consensus" and true_prob is not None:
        return _build_median_consensus_steps(
            true_prob=true_prob,
            fair_odds=fair_odds,
            best_book=best_book,
            best_book_price=best_book_price,
            best_ev_percent=best_ev_percent,
            per_book_fair_probs=per_book_fair_probs,
            consensus_iqr=consensus_iqr,
        )

    if (
        ev_method == "pinnacle_devig"
        and reference_price is not None
        and opposite_reference_price is not None
        and true_prob is not None
    ):
        return _build_pinnacle_devig_steps(
            reference_price=reference_price,
            opposite_reference_price=opposite_reference_price,
            true_prob=true_prob,
            fair_odds=fair_odds,
            best_book=best_book,
            best_book_price=best_book_price,
            best_ev_percent=best_ev_percent,
        )

    if (
        ev_method == "pinnacle_extrapolated"
        and reference_price is not None
        and opposite_reference_price is not None
        and true_prob is not None
    ):
        return _build_extrapolated_steps(
            reference_price=reference_price,
            opposite_reference_price=opposite_reference_price,
            true_prob=true_prob,
            fair_odds=fair_odds,
            best_book=best_book,
            best_book_price=best_book_price,
            best_ev_percent=best_ev_percent,
            estimated_sharp_price=estimated_sharp_price,
            extrapolation_ref_line=extrapolation_ref_line,
            extrapolation_distance=extrapolation_distance,
        )

    if true_prob is not None:
        return _build_fallback_steps(
            true_prob=true_prob,
            fair_odds=fair_odds,
            best_book=best_book,
            best_book_price=best_book_price,
            best_ev_percent=best_ev_percent,
        )

    return _build_not_available_step(ev_disabled_reason)
