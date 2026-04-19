"""Pure-computation EV annotation helpers for FairBet odds.

Contains the BookOdds model and stateless helpers that pair opposite
sides of a market, compute confidence, and annotate bets with EV data.
These have no dependency on FastAPI, SQLAlchemy, or the database —
they operate entirely on in-memory dicts.

Extrapolation logic (logit-space sharp-reference EV) lives in
ev_extrapolation.py.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ...services.ev import (
    book_spread_factor,
    compute_ev_for_market,
    evaluate_ev_eligibility,
    extrapolation_distance_factor,
    pinnacle_alignment_factor,
    probability_confidence,
)
from ...services.ev_consensus import compute_ev_median_consensus, consensus_agreement_factor

logger = logging.getLogger(__name__)


class BookOdds(BaseModel):
    """Odds from a single book for a bet."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    book: str
    price: float
    observed_at: datetime
    ev_percent: float | None = None
    display_ev: float | None = None
    implied_prob: float | None = None
    is_sharp: bool = False
    ev_method: str | None = None
    ev_confidence_tier: str | None = None
    book_abbr: str | None = None
    price_decimal: float | None = None
    ev_tier: str | None = None


def derive_entity_key(
    selection_key: str,
    market_key: str,
    player_name: str | None = None,
) -> str:
    """Derive canonical entity key from selection_key for entity-safe grouping.

    Rules:
      - player:{slug}:{over/under}  ->  "player:{slug}:{hash8}"  (with player_name)
      - player:{slug}:{over/under}  ->  "player:{slug}"           (without player_name)
      - team:{slug}                 ->  "game"                    (spreads/ML are game-level)
      - total:{team_slug}:{o/u}     ->  "team_total:{team_slug}" (team total)
      - total:{over/under}          ->  "game"                    (game total)
    """
    if not selection_key:
        return "game"
    parts = selection_key.split(":")

    if parts[0] == "player" and len(parts) >= 3:
        slug = parts[1]
        if player_name:
            h = hashlib.blake2s(f"{player_name}:{market_key}".encode(), digest_size=4).hexdigest()
            return f"player:{slug}:{h}"
        return f"player:{slug}"

    if parts[0] == "total" and len(parts) == 3 and parts[2] in ("over", "under"):
        # New-format team_total: "total:{team_slug}:{over/under}"
        return f"team_total:{parts[1]}"

    # team:{slug} (spreads/ML), total:{over/under} (game total), anything else
    return "game"


def _pair_opposite_sides(
    bet_keys: list[tuple],
) -> tuple[list[tuple[tuple, tuple]], list[tuple]]:
    """Pair bet keys that represent opposite sides of a two-way market.

    Two keys are opposite sides when they share (game_id, market_key, abs(line_value))
    but have different selection_keys.

    Returns:
        (pairs, unpaired) — list of (key_a, key_b) pairs + list of unmatched keys.
    """
    pairs: list[tuple[tuple, tuple]] = []
    used: set[int] = set()

    for i, key_a in enumerate(bet_keys):
        if i in used:
            continue
        for j in range(i + 1, len(bet_keys)):
            if j in used:
                continue
            key_b = bet_keys[j]
            # selection_key is index 2, line_value is index 3
            # in the tuple (game_id, market_key, selection_key, line_value)
            if key_a[2] == key_b[2]:
                continue  # Same selection_key — not opposite sides

            # Defensive entity check (slug-only, no player_name hash needed here)
            entity_a = derive_entity_key(key_a[2], key_a[1])
            entity_b = derive_entity_key(key_b[2], key_b[1])
            if entity_a != entity_b:
                continue  # Different entities — not a valid pair

            # Line values must be compatible to be the same market:
            # Spreads: sum to ~0 (e.g., -3.5 and +3.5)
            # Totals/ML: equal non-negative (e.g., both 200.5 or both 0)
            line_a, line_b = key_a[3], key_b[3]
            lines_sum_to_zero = abs(line_a + line_b) < 0.01
            lines_equal_nonneg = (
                abs(line_a - line_b) < 0.01 and line_a >= 0 and line_b >= 0
            )
            if lines_sum_to_zero or lines_equal_nonneg:
                pairs.append((key_a, key_b))
                used.add(i)
                used.add(j)
                break

    unpaired = [bet_keys[i] for i in range(len(bet_keys)) if i not in used]
    return pairs, unpaired


def _compute_side_confidence(
    true_prob: float | None,
    pinnacle_implied: float | None,
    extrapolation_hp: float | None = None,
    book_implieds: list[float] | None = None,
    consensus_devigged_probs: list[float] | None = None,
) -> tuple[float, list[str]]:
    """Compute confidence multiplier and flags for one side of a market.

    Args:
        true_prob: Devigged true probability for this side.
        pinnacle_implied: Pinnacle's raw vigged implied probability for this side.
        extrapolation_hp: Half-points from reference (None for direct devig).
        book_implieds: Non-sharp implied probabilities for book outlier detection.

    Returns:
        (confidence, flags) — confidence is 0-1 multiplier, flags is list of strings.
    """
    if true_prob is None:
        return 1.0, []

    confidence = 1.0
    flags: list[str] = []

    # Probability-based decay for longshots
    prob_conf = probability_confidence(true_prob)
    if prob_conf < 1.0:
        confidence *= prob_conf
        flags.append("low_probability")

    # Pinnacle alignment (vig gap check) — skip for consensus
    if pinnacle_implied is not None and consensus_devigged_probs is None:
        align = pinnacle_alignment_factor(true_prob, pinnacle_implied)
        if align < 1.0:
            confidence *= align
            flags.append("high_vig")

    # Consensus agreement factor (replaces pinnacle alignment for consensus)
    if consensus_devigged_probs is not None:
        agree = consensus_agreement_factor(consensus_devigged_probs)
        if agree < 1.0:
            confidence *= agree
            flags.append("consensus_spread")

    # Extrapolation distance penalty
    if extrapolation_hp is not None:
        extrap = extrapolation_distance_factor(extrapolation_hp)
        confidence *= extrap
        flags.append("extrapolated")

    # Book consensus spread — penalize when one book is a pricing outlier
    if book_implieds is not None:
        spread_conf = book_spread_factor(book_implieds)
        if spread_conf < 1.0:
            confidence *= spread_conf
            flags.append("book_outlier")

    return round(confidence, 4), flags


def _apply_display_ev(
    books: list[BookOdds],
    confidence: float,
) -> list[BookOdds]:
    """Set display_ev = ev_percent (raw mathematical EV) on each BookOdds.

    Confidence is communicated separately via ev_confidence_tier, not baked
    into the displayed number.  This keeps the card chip consistent with the
    explanation-step walkthrough that derives EV from first principles.

    Returns a new list with display_ev populated.
    """
    result: list[BookOdds] = []
    for b in books:
        display_ev = (
            round(b.ev_percent, 2)
            if b.ev_percent is not None
            else None
        )
        result.append(b.model_copy(update={"display_ev": display_ev}))
    return result


def _annotate_pair_ev(
    key_a: tuple,
    key_b: tuple,
    bets_map: dict[tuple, dict[str, Any]],
) -> str | None:
    """Compute and annotate EV for a single market pair in-place.

    Returns the disabled_reason string if EV was not computed, or None on success.
    """
    # Defense-in-depth: never compute EV across different entities
    entity_a = bets_map[key_a].get("entity_key", "game")
    entity_b = bets_map[key_b].get("entity_key", "game")
    if entity_a != entity_b:
        for key in (key_a, key_b):
            bets_map[key]["ev_disabled_reason"] = "entity_mismatch"
            bets_map[key]["books"] = [
                BookOdds(
                    book=b["book"] if isinstance(b, dict) else b.book,
                    price=b["price"] if isinstance(b, dict) else b.price,
                    observed_at=b["observed_at"] if isinstance(b, dict) else b.observed_at,
                )
                for b in bets_map[key]["books"]
            ]
        return "entity_mismatch"

    books_a = bets_map[key_a]["books"]
    books_b = bets_map[key_b]["books"]
    league_code = bets_map[key_a].get("league_code", "UNKNOWN")
    market_cat = bets_map[key_a].get("market_category", "mainline")

    eligibility = evaluate_ev_eligibility(
        league_code,
        market_cat,
        books_a,
        books_b,
    )

    logger.info(
        "ev_eligibility_result",
        extra={
            "league": league_code,
            "market_category": market_cat,
            "market_key": bets_map[key_a]["market_key"],
            "eligible": eligibility.eligible,
            "disabled_reason": eligibility.disabled_reason,
            "confidence_tier": eligibility.confidence_tier,
            "books_a_count": len(books_a),
            "books_b_count": len(books_b),
            "books_a_names": [b["book"] for b in books_a],
        },
    )

    if eligibility.eligible and eligibility.strategy_config is not None:
        strategy_config = eligibility.strategy_config
        is_consensus = strategy_config.strategy_name == "median_consensus"
        consensus_metadata = None

        if is_consensus:
            ev_result, consensus_metadata = compute_ev_median_consensus(
                books_a, books_b, strategy_config,
            )
        else:
            ev_result = compute_ev_for_market(
                books_a, books_b, strategy_config,
            )

        if ev_result.fair_odds_suspect:
            logger.warning(
                "fair_odds_outlier",
                extra={
                    "league": league_code,
                    "market_category": market_cat,
                    "market_key": bets_map[key_a]["market_key"],
                },
            )
            # Devig produced implausible fair odds — skip EV annotation
            sharp = set(eligibility.strategy_config.eligible_sharp_books)
            for key in (key_a, key_b):
                bets_map[key]["ev_disabled_reason"] = "fair_odds_outlier"
                bets_map[key]["ev_confidence_tier"] = ev_result.confidence_tier
                bets_map[key]["ev_method"] = ev_result.ev_method
                bets_map[key]["books"] = [
                    BookOdds(
                        book=b["book"],
                        price=b["price"],
                        observed_at=b["observed_at"],
                        is_sharp=b["book"] in sharp,
                    )
                    for b in bets_map[key]["books"]
                ]
            return "fair_odds_outlier"

        # Update with annotated data
        bets_map[key_a]["books"] = [
            BookOdds(
                book=b["book"],
                price=b["price"],
                observed_at=b["observed_at"],
                ev_percent=b.get("ev_percent"),
                implied_prob=round(b.get("implied_prob", 0), 4)
                if b.get("implied_prob")
                else None,
                is_sharp=b.get("is_sharp", False),
                ev_method=ev_result.ev_method,
                ev_confidence_tier=ev_result.confidence_tier,
            )
            for b in ev_result.annotated_a
        ]
        bets_map[key_b]["books"] = [
            BookOdds(
                book=b["book"],
                price=b["price"],
                observed_at=b["observed_at"],
                ev_percent=b.get("ev_percent"),
                implied_prob=round(b.get("implied_prob", 0), 4)
                if b.get("implied_prob")
                else None,
                is_sharp=b.get("is_sharp", False),
                ev_method=ev_result.ev_method,
                ev_confidence_tier=ev_result.confidence_tier,
            )
            for b in ev_result.annotated_b
        ]

        # Build consensus devigged probs list (if consensus method)
        consensus_devigged_probs: list[float] | None = None
        if is_consensus and consensus_metadata is not None:
            consensus_devigged_probs = list(consensus_metadata.per_book_fair_probs.values())

        # Compute confidence and display_ev for each side
        for key, true_prob, annotated in [
            (key_a, ev_result.true_prob_a, ev_result.annotated_a),
            (key_b, ev_result.true_prob_b, ev_result.annotated_b),
        ]:
            # Find Pinnacle's vigged implied prob from annotated entries
            pinnacle_implied = None
            non_sharp_implieds: list[float] = []
            for b in annotated:
                if b.get("is_sharp"):
                    pinnacle_implied = b.get("implied_prob")
                elif b.get("implied_prob") is not None:
                    non_sharp_implieds.append(b["implied_prob"])

            confidence, flags = _compute_side_confidence(
                true_prob, pinnacle_implied,
                book_implieds=non_sharp_implieds or None,
                consensus_devigged_probs=consensus_devigged_probs,
            )
            bets_map[key]["books"] = _apply_display_ev(
                bets_map[key]["books"], confidence
            )
            bets_map[key]["confidence"] = confidence
            bets_map[key]["confidence_flags"] = flags

        # Set true_prob and EV metadata on the bet definition
        if (
            ev_result.annotated_a
            and ev_result.annotated_a[0].get("true_prob") is not None
        ):
            bets_map[key_a]["true_prob"] = ev_result.annotated_a[0]["true_prob"]
        if (
            ev_result.annotated_b
            and ev_result.annotated_b[0].get("true_prob") is not None
        ):
            bets_map[key_b]["true_prob"] = ev_result.annotated_b[0]["true_prob"]

        bets_map[key_a]["reference_price"] = ev_result.reference_price_a
        bets_map[key_a]["opposite_reference_price"] = ev_result.reference_price_b
        bets_map[key_b]["reference_price"] = ev_result.reference_price_b
        bets_map[key_b]["opposite_reference_price"] = ev_result.reference_price_a

        bets_map[key_a]["ev_method"] = ev_result.ev_method
        bets_map[key_a]["ev_confidence_tier"] = ev_result.confidence_tier
        bets_map[key_b]["ev_method"] = ev_result.ev_method
        bets_map[key_b]["ev_confidence_tier"] = ev_result.confidence_tier

        bets_map[key_a]["has_fair"] = True
        bets_map[key_b]["has_fair"] = True

        # Attach consensus metadata if available
        if consensus_metadata is not None:
            for key in (key_a, key_b):
                bets_map[key]["consensus_book_count"] = consensus_metadata.consensus_book_count
                bets_map[key]["consensus_iqr"] = consensus_metadata.consensus_iqr
                bets_map[key]["per_book_fair_probs"] = consensus_metadata.per_book_fair_probs

        return None
    else:
        # Not eligible: attach disabled metadata, convert books to BookOdds
        sharp = (
            set(eligibility.strategy_config.eligible_sharp_books)
            if eligibility.strategy_config
            else set()
        )
        for key in (key_a, key_b):
            bets_map[key]["ev_disabled_reason"] = eligibility.disabled_reason
            bets_map[key]["ev_confidence_tier"] = eligibility.confidence_tier
            bets_map[key]["ev_method"] = eligibility.ev_method
            bets_map[key]["books"] = [
                BookOdds(
                    book=b["book"],
                    price=b["price"],
                    observed_at=b["observed_at"],
                    is_sharp=b["book"] in sharp,
                )
                for b in bets_map[key]["books"]
            ]
        return eligibility.disabled_reason


def _market_base(market_key: str) -> str | None:
    """Normalize market_key to base type for extrapolation.

    Args:
        market_key: Raw market key (e.g., "spreads", "alternate_spreads", "totals",
                     "team_totals").

    Returns:
        "spreads", "totals", or "team_totals" for extrapolatable markets,
        None otherwise.
    """
    lower = market_key.lower()
    if "spread" in lower:
        return "spreads"
    # "team_total" check MUST come before "total" since "team_totals" contains "total"
    if "team_total" in lower:
        return "team_totals"
    if "total" in lower:
        return "totals"
    return None


