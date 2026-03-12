"""Display-oriented helpers for FairBet odds.

Pure functions that compute human-readable labels from raw bet data,
so clients don't need to duplicate formatting/lookup logic.
"""

from __future__ import annotations

from typing import Any

from .ev_config import (
    BOOK_ABBREVIATIONS,
    CONFIDENCE_DISPLAY_LABELS,
    FAIRBET_METHOD_DISPLAY_NAMES,
    FAIRBET_METHOD_EXPLANATIONS,
    MARKET_DISPLAY_NAMES,
)
from .fairbet_explanation_steps import (
    _build_extrapolated_steps,
    _build_fallback_steps,
    _build_median_consensus_steps,
    _build_not_available_step,
    _build_pinnacle_devig_steps,
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
    from .ev import implied_to_american

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
# Explanation step orchestrator
# ---------------------------------------------------------------------------


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
