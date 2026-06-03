"""FairBet live endpoint models and market helpers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .ev_annotation import BookOdds

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


def _slugify(text: str) -> str:
    return text.lower().strip().replace(" ", "_").replace(".", "").replace("'", "")


def _build_selection_key(
    selection_name: str,
    market_key: str,
    line: float | None,
    description: str | None = None,
) -> str:
    """Build a canonical selection_key from Odds API selection name.

    Maps raw names to the format used by the pre-game EV pipeline:
      - player_prop Over/Under  -> 'player:{slug}:{over|under}'  (slug from `description`)
      - team_prop  Over/Under   -> 'total:{slug}:{over|under}'   (slug from `description`)
      - game total Over/Under   -> 'total:{over|under}'
      - team selection          -> 'team:{slug}'

    Without `description`, every player's Over/Under in the same market would
    collide on the same key — see live endpoint dedup.
    """
    name_lower = selection_name.lower().strip()

    if name_lower in ("over", "under"):
        category = _classify_market(market_key)
        slug = _slugify(description) if description else ""
        if slug:
            if category == "player_prop":
                return f"player:{slug}:{name_lower}"
            if category == "team_prop":
                return f"total:{slug}:{name_lower}"
        return f"total:{name_lower}"

    return f"team:{_slugify(name_lower)}"


class LiveBetDefinition(BaseModel):
    """A live bet with EV annotation — same shape as pre-game BetDefinition."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    league_code: str
    home_team: str
    away_team: str
    home_team_abbr: str | None = None
    away_team_abbr: str | None = None
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
