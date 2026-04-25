"""Bet grouping, EV annotation, and display enrichment for FairBet odds."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...db.odds import FairbetGameOddsWork
from ...services.ev import american_to_implied
from ...services.ev_config import (
    SHARP_REF_MAX_AGE_SECONDS,
    get_fairbet_debug_game_ids,
    get_strategy,
)
from ...services.fairbet_display import (
    book_abbreviation,
    build_explanation_steps,
    confidence_display_label,
    ev_method_display_name,
    ev_method_explanation,
    fair_american_odds,
    market_display_name,
    selection_display,
)
from .ev_annotation import BookOdds, _annotate_pair_ev, _pair_opposite_sides, derive_entity_key
from .ev_extrapolation import _build_sharp_reference, _try_extrapolated_ev
from .ev_staleness import filter_stale_books

logger = logging.getLogger(__name__)


def enrich_and_finalize(
    rows: list[FairbetGameOddsWork],
    sort_key: str,
    *,
    has_fair: bool | None,
    min_ev: float | None,
    book: str | None,
    min_books_for_fairbet: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Convert raw DB rows into API-ready bets with EV and display fields."""

    def _abbr(team: Any) -> str | None:
        if team is None:
            return None
        value = getattr(team, "abbreviation", None)
        return value if isinstance(value, str) else None

    bets_map: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        game = row.game
        key = (row.game_id, row.market_key, row.selection_key, row.line_value)
        if key not in bets_map:
            bets_map[key] = {
                "game_id": row.game_id,
                "league_code": game.league.code if game.league else "UNKNOWN",
                "home_team": game.home_team.name if game.home_team else "Unknown",
                "away_team": game.away_team.name if game.away_team else "Unknown",
                "home_team_abbr": _abbr(game.home_team),
                "away_team_abbr": _abbr(game.away_team),
                "game_date": game.game_date,
                "market_key": row.market_key,
                "selection_key": row.selection_key,
                "line_value": row.line_value,
                "market_category": row.market_category,
                "player_name": row.player_name,
                "entity_key": derive_entity_key(row.selection_key, row.market_key, row.player_name),
                "books": [],
            }
        bets_map[key]["books"].append(
            {"book": row.book, "price": row.price, "observed_at": row.observed_at}
        )

    bets_map = filter_stale_books(bets_map, sharp_books={"Pinnacle"})
    bets_map = {
        k: b for k, b in bets_map.items() if len(b.get("books", [])) >= min_books_for_fairbet
    }

    market_groups: dict[tuple, list[tuple]] = {}
    for key in bets_map:
        game_id_k, market_key_k, _, line_value_k = key
        entity_key = bets_map[key]["entity_key"]
        group_key = (game_id_k, market_key_k, entity_key, abs(line_value_k))
        market_groups.setdefault(group_key, []).append(key)

    ev_diagnostics: dict[str, int] = {"total_pairs": 0, "total_unpaired": 0}
    sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"}, max_age_seconds=SHARP_REF_MAX_AGE_SECONDS)

    for _, bet_keys in market_groups.items():
        pairs, unpaired = _pair_opposite_sides(bet_keys)
        for key_a, key_b in pairs:
            ev_diagnostics["total_pairs"] += 1
            reason = _annotate_pair_ev(key_a, key_b, bets_map)
            if reason == "entity_mismatch":
                _debug_ids = get_fairbet_debug_game_ids()
                if key_a[0] in _debug_ids:
                    logger.info(
                        "entity_pair_blocked",
                        extra={
                            "game_id": key_a[0],
                            "entity_a": bets_map[key_a].get("entity_key"),
                            "entity_b": bets_map[key_b].get("entity_key"),
                            "market_key": key_a[1],
                            "line_value": key_a[3],
                        },
                    )
            if reason == "reference_missing":
                extrap_reason = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
                if extrap_reason is None:
                    ev_diagnostics["extrapolated"] = ev_diagnostics.get("extrapolated", 0) + 1
                    reason = None
                else:
                    reason = extrap_reason
            bucket = reason or "passed"
            ev_diagnostics[bucket] = ev_diagnostics.get(bucket, 0) + 1

        for key in unpaired:
            ev_diagnostics["total_unpaired"] += 1
            ev_diagnostics["no_pair"] = ev_diagnostics.get("no_pair", 0) + 1
            sample_league = bets_map[key].get("league_code", "UNKNOWN")
            sample_cat = bets_map[key].get("market_category", "mainline")
            cfg = get_strategy(sample_league, sample_cat)
            sharp = set(cfg.eligible_sharp_books) if cfg else set()
            bets_map[key]["ev_disabled_reason"] = "no_pair"
            bets_map[key]["books"] = [
                BookOdds(book=b["book"], price=b["price"], observed_at=b["observed_at"], is_sharp=b["book"] in sharp)
                for b in bets_map[key]["books"]
            ]

    bets_list = list(bets_map.values())
    if sort_key == "ev":
        def best_ev(bet: dict[str, Any]) -> float:
            evs = [b.display_ev for b in bet["books"] if b.display_ev is not None]
            if evs:
                return max(evs)
            raw = [b.ev_percent for b in bet["books"] if b.ev_percent is not None]
            return max(raw) if raw else float("-inf")
        bets_list.sort(key=best_ev, reverse=True)
    elif sort_key == "game_time":
        bets_list.sort(
            key=lambda b: (
                b.get("game_date") or datetime.min.replace(tzinfo=UTC),
                b.get("game_id", 0),
                b.get("market_key", ""),
                b.get("selection_key", ""),
                b.get("line_value", 0),
            )
        )
    elif sort_key == "market":
        bets_list.sort(
            key=lambda b: (
                b.get("market_key", ""),
                b.get("selection_key", ""),
                b.get("game_date") or datetime.min.replace(tzinfo=UTC),
                b.get("game_id", 0),
                b.get("line_value", 0),
            )
        )
    else:
        bets_list.sort(
            key=lambda b: (
                b.get("game_id", 0),
                b.get("market_key", ""),
                b.get("selection_key", ""),
                b.get("line_value", 0),
            )
        )
    for bet in bets_list:
        bet["books"].sort(key=lambda b: -b.price)

    if has_fair is not None:
        bets_list = [b for b in bets_list if b.get("has_fair", False) == has_fair]
    if min_ev is not None:
        bets_list = [
            bet
            for bet in bets_list
            if any(
                (
                    (b.display_ev is not None and b.display_ev >= min_ev) or
                    (b.display_ev is None and b.ev_percent is not None and b.ev_percent >= min_ev)
                )
                for b in bet["books"]
            )
        ]
    if book:
        for bet in bets_list:
            bet["books"] = [b for b in bet["books"] if b.book == book or b.is_sharp]

    for bet in bets_list:
        bet["fair_american_odds"] = fair_american_odds(bet.get("true_prob"))
        bet["selection_display"] = selection_display(
            bet.get("selection_key", ""),
            bet.get("market_key", ""),
            home_team=bet.get("home_team"),
            away_team=bet.get("away_team"),
            player_name=bet.get("player_name"),
            line_value=bet.get("line_value"),
        )
        bet["market_display_name"] = market_display_name(bet.get("market_key", ""))
        bet["confidence_display_label"] = confidence_display_label(bet.get("ev_confidence_tier"))
        bet["ev_method_display_name"] = ev_method_display_name(bet.get("ev_method"))
        bet["ev_method_explanation"] = ev_method_explanation(bet.get("ev_method"))

        best_ev_val: float | None = None
        best_book_name: str | None = None
        for b in bet["books"]:
            ev_val = b.display_ev if b.display_ev is not None else b.ev_percent
            if ev_val is not None and (best_ev_val is None or ev_val > best_ev_val):
                best_ev_val = ev_val
                best_book_name = b.book
        bet["best_book"] = best_book_name
        bet["best_ev_percent"] = round(best_ev_val, 2) if best_ev_val is not None else None
        bet["is_reliably_positive"] = (
            best_ev_val is not None and best_ev_val > 0 and (bet.get("confidence") or 0) >= 0.7
        )

        best_book_price: float | None = None
        if best_book_name:
            for b in bet["books"]:
                if b.book == best_book_name:
                    best_book_price = b.price
                    break
        bet["explanation_steps"] = build_explanation_steps(
            ev_method=bet.get("ev_method"),
            ev_disabled_reason=bet.get("ev_disabled_reason"),
            true_prob=bet.get("true_prob"),
            reference_price=bet.get("reference_price"),
            opposite_reference_price=bet.get("opposite_reference_price"),
            fair_odds=bet["fair_american_odds"],
            best_book=best_book_name,
            best_book_price=best_book_price,
            best_ev_percent=bet["best_ev_percent"],
            estimated_sharp_price=bet.get("estimated_sharp_price"),
            extrapolation_ref_line=bet.get("extrapolation_ref_line"),
            extrapolation_distance=bet.get("extrapolation_distance"),
            per_book_fair_probs=bet.get("per_book_fair_probs"),
            consensus_iqr=bet.get("consensus_iqr"),
        )

        enriched_books: list[BookOdds] = []
        for b in bet["books"]:
            abbr = book_abbreviation(b.book)
            price_dec: float | None = None
            try:
                imp = american_to_implied(b.price)
                price_dec = round(1.0 / imp, 3) if imp > 0 else None
            except (ValueError, ZeroDivisionError):
                logger.debug("skipped_invalid_odds_conversion", extra={"price": b.price})
            ev_tier: str | None = None
            ev_val = b.display_ev if b.display_ev is not None else b.ev_percent
            if ev_val is not None:
                if ev_val >= 5.0:
                    ev_tier = "strong_positive"
                elif ev_val >= 0.0:
                    ev_tier = "positive"
                else:
                    ev_tier = "negative"
            elif b.is_sharp:
                ev_tier = "neutral"
            enriched_books.append(
                b.model_copy(update={"book_abbr": abbr, "price_decimal": price_dec, "ev_tier": ev_tier})
            )
        bet["books"] = enriched_books

    return bets_list, ev_diagnostics
