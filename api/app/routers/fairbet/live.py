"""FairBet Live endpoint: +EV fair-bet computation on live in-game odds.

GET /api/fairbet/live?game_id=...

Reads aggregated live odds from Redis (all bookmakers per market),
runs the same EV pipeline as pre-game odds (Shin devig, Pinnacle
reference, extrapolation), and returns annotated BetDefinition objects.

Nothing is persisted to the DB — purely ephemeral computation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select

from app.db import get_db
from app.db.sports import SportsGame, SportsLeague
from app.services.ev import american_to_implied
from app.services.ev_config import (
    INCLUDED_BOOKS,
    SHARP_REF_MAX_AGE_SECONDS,
    get_strategy,
)
from app.services.fairbet_display import (
    book_abbreviation,
    build_explanation_steps,
    fair_american_odds,
    market_display_name,
    selection_display,
)
from app.services.game_status import LIVE_STATUSES
from app.services.live_odds_redis import discover_live_game_ids, read_all_live_snapshots_for_game

from .ev_annotation import (
    BookOdds,
    _annotate_pair_ev,
    _pair_opposite_sides,
    derive_entity_key,
)
from .ev_extrapolation import _build_sharp_reference, _try_extrapolated_ev

logger = logging.getLogger(__name__)

router = APIRouter()

# Minimum books per bet to show in results
MIN_BOOKS_FOR_LIVE = 3

# Market key classification (mirrors scraper/sports_scraper/models/schemas.py)
_MAINLINE_KEYS = frozenset({"h2h", "spreads", "totals", "spread", "total", "moneyline"})
_PLAYER_PROP_PREFIXES = ("player_", "batter_", "pitcher_")
_TEAM_PROP_PREFIXES = ("team_total",)
_ALTERNATE_PREFIXES = ("alternate_",)


def _classify_market(market_key: str) -> str:
    """Classify a market key into a category."""
    key = market_key.lower()
    if key in _MAINLINE_KEYS:
        return "mainline"
    if key.startswith(_PLAYER_PROP_PREFIXES):
        return "player_prop"
    if key.startswith(_TEAM_PROP_PREFIXES):
        return "team_prop"
    if key.startswith(_ALTERNATE_PREFIXES):
        return "alternate"
    return "mainline"


def _build_selection_key(selection_name: str, market_key: str, line: float | None) -> str:
    """Build a canonical selection_key from Odds API selection name.

    Maps raw names like 'Over', 'Under', team names to the format used
    by the pre-game EV pipeline: 'total:over', 'team:slug', etc.
    """
    name_lower = selection_name.lower().strip()

    if name_lower in ("over", "under"):
        return f"total:{name_lower}"

    # Team name — slugify
    slug = name_lower.replace(" ", "_").replace(".", "").replace("'", "")
    return f"team:{slug}"


class LiveBetDefinition(BaseModel):
    """A live bet with EV annotation — same shape as pre-game BetDefinition."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    league_code: str
    home_team: str
    away_team: str
    game_date: datetime | None
    market_key: str
    selection_key: str
    line_value: float
    market_category: str | None = None
    player_name: str | None = None
    true_prob: float | None = None
    reference_price: float | None = None
    opposite_reference_price: float | None = None
    books: list[BookOdds]
    ev_confidence_tier: str | None = None
    ev_disabled_reason: str | None = None
    ev_method: str | None = None
    has_fair: bool = False
    estimated_sharp_price: float | None = None
    extrapolation_ref_line: float | None = None
    extrapolation_distance: float | None = None
    consensus_book_count: int | None = None
    consensus_iqr: float | None = None
    per_book_fair_probs: dict[str, float] | None = None
    confidence: float | None = None
    confidence_flags: list[str] = []
    fair_american_odds: int | None = None
    selection_display: str | None = None
    market_display_name: str | None = None
    best_book: str | None = None
    best_ev_percent: float | None = None
    is_reliably_positive: bool | None = None
    explanation_steps: list[dict] | None = None


class LiveGameInfo(BaseModel):
    """A game that currently has live odds in Redis."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    league_code: str
    home_team: str
    away_team: str
    game_date: datetime | None
    status: str | None


@router.get("/live/games")
async def fairbet_live_games(
    league: str | None = Query(None, description="Filter by league code"),
) -> list[LiveGameInfo]:
    """List all games that currently have live odds data in Redis."""
    pairs = discover_live_game_ids(league)
    if not pairs:
        return []

    game_ids = [gid for _, gid in pairs]
    league_map = {gid: lc for lc, gid in pairs}

    results: list[LiveGameInfo] = []
    async for session in get_db():
        from sqlalchemy.orm import aliased

        from app.db.sports import SportsTeam

        HomeTeam = aliased(SportsTeam)
        AwayTeam = aliased(SportsTeam)

        stmt = (
            select(
                SportsGame.id,
                SportsGame.game_date,
                SportsGame.status,
                HomeTeam.name.label("home_name"),
                AwayTeam.name.label("away_name"),
            )
            .outerjoin(HomeTeam, SportsGame.home_team_id == HomeTeam.id)
            .outerjoin(AwayTeam, SportsGame.away_team_id == AwayTeam.id)
            .where(SportsGame.id.in_(game_ids))
        )
        rows = await session.execute(stmt)

        for gid, game_date, status, home_name, away_name in rows:
            # Only include games that are actually live (in_progress, live, halftime)
            if not status or status.lower().strip() not in LIVE_STATUSES:
                continue
            results.append(LiveGameInfo(
                game_id=gid,
                league_code=league_map.get(gid, ""),
                home_team=home_name or "Unknown",
                away_team=away_name or "Unknown",
                game_date=game_date,
                status=status,
            ))

    # Sort by game_date
    results.sort(key=lambda g: g.game_date or datetime.min.replace(tzinfo=UTC))
    return results


class FairbetLiveResponse(BaseModel):
    """Response with EV-annotated live odds."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    league_code: str
    home_team: str
    away_team: str
    bets: list[LiveBetDefinition]
    total: int
    books_available: list[str]
    market_categories_available: list[str]
    last_updated_at: str | None
    ev_diagnostics: dict[str, int] = {}
    redis_status: str = "ok"


@router.get("/live")
async def fairbet_live(
    game_id: int = Query(..., description="Game ID"),
    market_category: str | None = Query(None, description="Filter by market category"),
    sort_by: str = Query("ev", description="Sort: ev, market"),
) -> FairbetLiveResponse:
    """Compute +EV fair-bet odds for a live game.

    Reads all bookmakers' live odds from Redis, runs the same EV pipeline
    as pre-game (Shin devig, Pinnacle reference, extrapolation), and
    returns annotated bet definitions. Nothing persisted.
    """
    # Look up game info from DB
    async for session in get_db():
        from sqlalchemy.orm import aliased

        from app.db.sports import SportsTeam

        HomeTeam = aliased(SportsTeam)
        AwayTeam = aliased(SportsTeam)

        stmt = (
            select(
                SportsGame.id,
                SportsGame.game_date,
                SportsGame.status,
                SportsLeague.code,
                HomeTeam.name.label("home_name"),
                AwayTeam.name.label("away_name"),
            )
            .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
            .outerjoin(HomeTeam, SportsGame.home_team_id == HomeTeam.id)
            .outerjoin(AwayTeam, SportsGame.away_team_id == AwayTeam.id)
            .where(SportsGame.id == game_id)
        )
        result = await session.execute(stmt)
        row = result.one_or_none()

        if not row:
            raise HTTPException(status_code=404, detail="Game not found")

        _, game_date, game_status, league_code, home_team_name, away_team_name = row
        home_team_name = home_team_name or "Unknown"
        away_team_name = away_team_name or "Unknown"

    # Read all live snapshots from Redis
    snapshots, redis_error = read_all_live_snapshots_for_game(league_code, game_id)
    redis_status = "error" if redis_error else "ok"

    if not snapshots:
        return FairbetLiveResponse(
            game_id=game_id,
            league_code=league_code,
            home_team=home_team_name,
            away_team=away_team_name,
            bets=[],
            total=0,
            books_available=[],
            market_categories_available=[],
            last_updated_at=None,
            redis_status=redis_status,
        )

    # Build bets_map from Redis snapshots (same format as pre-game odds.py)
    now = datetime.now(UTC)
    bets_map: dict[tuple, dict[str, Any]] = {}
    all_books: set[str] = set()
    all_categories: set[str] = set()
    latest_update: float | None = None

    for market_key, snapshot in snapshots.items():
        books_data = snapshot.get("books", {})
        market_category = _classify_market(market_key)

        if market_category:
            all_categories.add(market_category)

        ts = snapshot.get("last_updated_at")
        if ts and (latest_update is None or ts > latest_update):
            latest_update = ts

        # Aggregate selections across all books to find unique (selection, line) combos
        # Then build bet entries
        for book_name, selections in books_data.items():
            if book_name not in INCLUDED_BOOKS:
                continue
            all_books.add(book_name)

            for sel in selections:
                selection_name = sel.get("selection", "")
                line = sel.get("line")
                price = sel.get("price")

                if not selection_name or price is None:
                    continue

                selection_key = _build_selection_key(selection_name, market_key, line)
                line_value = float(line) if line is not None else 0.0

                key = (game_id, market_key, selection_key, line_value)

                if key not in bets_map:
                    bets_map[key] = {
                        "game_id": game_id,
                        "league_code": league_code,
                        "home_team": home_team_name,
                        "away_team": away_team_name,
                        "game_date": game_date,
                        "market_key": market_key,
                        "selection_key": selection_key,
                        "line_value": line_value,
                        "market_category": market_category,
                        "player_name": sel.get("description"),
                        "entity_key": derive_entity_key(selection_key, market_key),
                        "books": [],
                    }

                bets_map[key]["books"].append({
                    "book": book_name,
                    "price": float(price),
                    "observed_at": now,  # Live odds are always "now"
                })

    # Filter by market_category if requested
    if market_category:
        bets_map = {
            k: v for k, v in bets_map.items()
            if v.get("market_category") == market_category
        }

    # Drop bets with insufficient books
    bets_map = {
        k: v for k, v in bets_map.items()
        if len(v["books"]) >= MIN_BOOKS_FOR_LIVE
    }

    # --- EV annotation (same pipeline as pre-game) ---
    market_groups: dict[tuple, list[tuple]] = {}
    for key in bets_map:
        game_id_k, market_key_k, _, line_value_k = key
        entity_key = bets_map[key]["entity_key"]
        group_key = (game_id_k, market_key_k, entity_key, abs(line_value_k))
        market_groups.setdefault(group_key, []).append(key)

    ev_diagnostics: dict[str, int] = {"total_pairs": 0, "total_unpaired": 0}
    sharp_refs = _build_sharp_reference(
        bets_map, {"Pinnacle"}, max_age_seconds=SHARP_REF_MAX_AGE_SECONDS
    )

    for group_key, bet_keys in market_groups.items():
        pairs, unpaired = _pair_opposite_sides(bet_keys)

        for key_a, key_b in pairs:
            ev_diagnostics["total_pairs"] += 1
            reason = _annotate_pair_ev(key_a, key_b, bets_map)
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
                BookOdds(
                    book=b["book"],
                    price=b["price"],
                    observed_at=b["observed_at"],
                    is_sharp=b["book"] in sharp,
                )
                for b in bets_map[key]["books"]
            ]

    # --- Sort ---
    bets_list = list(bets_map.values())

    if sort_by == "ev":
        def best_ev(bet: dict) -> float:
            evs = [b.display_ev for b in bet["books"] if isinstance(b, BookOdds) and b.display_ev is not None]
            if evs:
                return max(evs)
            raw = [b.ev_percent for b in bet["books"] if isinstance(b, BookOdds) and b.ev_percent is not None]
            return max(raw) if raw else float("-inf")

        bets_list.sort(key=best_ev, reverse=True)
    elif sort_by == "market":
        bets_list.sort(key=lambda b: (b.get("market_key", ""), b.get("selection_key", "")))

    # Sort books within each bet by price (best first)
    for bet in bets_list:
        if bet["books"] and isinstance(bet["books"][0], BookOdds):
            bet["books"].sort(key=lambda b: -b.price)

    # --- Enrich with display fields ---
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

        # Best book + best EV
        best_ev_val: float | None = None
        best_book_name: str | None = None
        for b in bet["books"]:
            if not isinstance(b, BookOdds):
                continue
            ev_val = b.display_ev if b.display_ev is not None else b.ev_percent
            if ev_val is not None and (best_ev_val is None or ev_val > best_ev_val):
                best_ev_val = ev_val
                best_book_name = b.book
        bet["best_book"] = best_book_name
        bet["best_ev_percent"] = round(best_ev_val, 2) if best_ev_val is not None else None
        bet["is_reliably_positive"] = (
            best_ev_val is not None
            and best_ev_val > 0
            and (bet.get("confidence") or 0) >= 0.7
        )

        # Explanation steps
        best_book_price: float | None = None
        if best_book_name:
            for b in bet["books"]:
                if isinstance(b, BookOdds) and b.book == best_book_name:
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

        # BookOdds-level enrichment
        enriched_books: list[BookOdds] = []
        for b in bet["books"]:
            if not isinstance(b, BookOdds):
                continue
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
                b.model_copy(update={
                    "book_abbr": abbr,
                    "price_decimal": price_dec,
                    "ev_tier": ev_tier,
                })
            )
        bet["books"] = enriched_books

    # Remove internal keys before serialization
    for bet in bets_list:
        bet.pop("entity_key", None)

    return FairbetLiveResponse(
        game_id=game_id,
        league_code=league_code,
        home_team=home_team_name,
        away_team=away_team_name,
        bets=[LiveBetDefinition(**bet) for bet in bets_list],
        total=len(bets_list),
        books_available=sorted(all_books),
        market_categories_available=sorted(all_categories),
        last_updated_at=(
            datetime.fromtimestamp(latest_update, tz=UTC).isoformat()
            if latest_update else None
        ),
        ev_diagnostics=ev_diagnostics,
        redis_status=redis_status,
    )
