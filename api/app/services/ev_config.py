"""EV strategy configuration — book lists, eligibility rules, confidence tiers.

Static, version-controlled config for the Sharp Book EV Baseline Framework.
All books are still ingested/persisted; exclusion is SQL-level at query time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class ConfidenceTier(str, Enum):
    """Market confidence tier — how much to trust the line reflects true probability.

    Based on non-sharp book count: more books pricing a market means more
    two-way action keeping the line honest.
    """

    FULL = "full"      # 5+ non-sharp books — deep, efficient market
    DECENT = "decent"  # 3-4 non-sharp books — reasonable price discovery
    THIN = "thin"      # ≤2 non-sharp books — low liquidity, line may be stale/unbalanced


def market_confidence_tier(non_sharp_book_count: int) -> str:
    """Compute market confidence tier from non-sharp book count.

    Args:
        non_sharp_book_count: Number of non-sharp books pricing one side of the market.

    Returns:
        "full", "decent", or "thin".
    """
    if non_sharp_book_count >= 5:
        return ConfidenceTier.FULL.value
    if non_sharp_book_count >= 3:
        return ConfidenceTier.DECENT.value
    return ConfidenceTier.THIN.value


@dataclass(frozen=True, slots=True)
class EVStrategyConfig:
    """Configuration for a single EV calculation strategy."""

    strategy_name: str  # e.g., "pinnacle_devig"
    eligible_sharp_books: tuple[str, ...]  # Reference price sources (display names)
    min_qualifying_books: int  # Per-side minimum non-excluded books
    max_reference_staleness_seconds: int  # observed_at vs now()
    max_fair_prob_divergence: float  # Max |fair_prob - median_implied_prob| allowed


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """Result of evaluating whether EV can be computed for a market."""

    eligible: bool
    strategy_config: EVStrategyConfig | None
    disabled_reason: str | None  # "no_strategy" | "reference_missing" | "reference_stale" | "insufficient_books" | "fair_odds_outlier"
    ev_method: str | None  # e.g., "pinnacle_devig"
    confidence_tier: str | None  # "full" | "decent" | "thin"


# ---------------------------------------------------------------------------
# Book lists
# ---------------------------------------------------------------------------

# Books excluded from EV comparisons (offshore / exchanges / prediction markets).
# All books still ingested and persisted; exclusion is SQL-level at query time.
EXCLUDED_BOOKS: frozenset[str] = frozenset(
    {
        # Offshore — unreliable lines for EV
        "BetOnline.ag",
        "Bovada",
        # Prediction markets / exchanges — not traditional sportsbooks
        "Kalshi",
        "Polymarket",
    }
)

# ---------------------------------------------------------------------------
# Display constants — single source of truth for client rendering
# ---------------------------------------------------------------------------

BOOK_ABBREVIATIONS: dict[str, str] = {
    "BetMGM": "MGM",
    "BetRivers": "BR",
    "Caesars": "CZR",
    "DraftKings": "DK",
    "FanDuel": "FD",
    "Pinnacle": "PIN",
    "888sport": "888",
    "William Hill": "WH",
    "Betfair Exchange": "BFX",
    "Betfair Sportsbook": "BF",
    "Ladbrokes": "LAD",
    "Paddy Power": "PP",
    "William Hill (UK)": "WHUK",
}

CONFIDENCE_DISPLAY_LABELS: dict[str, str] = {
    "full": "Sharp",
    "decent": "Market",
    "thin": "Thin",
}

MARKET_DISPLAY_NAMES: dict[str, str] = {
    "spreads": "Spread",
    "totals": "Total",
    "h2h": "Moneyline",
    "moneyline": "Moneyline",
    "player_points": "Player Points",
    "player_rebounds": "Player Rebounds",
    "player_assists": "Player Assists",
    "player_threes": "Player Threes",
    "player_blocks": "Player Blocks",
    "player_steals": "Player Steals",
    "player_turnovers": "Player Turnovers",
    "player_points_rebounds_assists": "Player PRA",
    "player_points_rebounds": "Player Pts+Reb",
    "player_points_assists": "Player Pts+Ast",
    "player_rebounds_assists": "Player Reb+Ast",
    "player_double_double": "Double Double",
    "player_first_basket": "First Basket",
    "player_first_goal": "First Goal",
    "player_goals": "Player Goals",
    "player_shots_on_goal": "Shots on Goal",
    "player_power_play_points": "PP Points",
    "batter_hits": "Hits",
    "batter_total_bases": "Total Bases",
    "batter_rbis": "RBIs",
    "batter_runs_scored": "Runs",
    "batter_home_runs": "Home Runs",
    "batter_stolen_bases": "Stolen Bases",
    "pitcher_strikeouts": "Pitcher Ks",
    "pitcher_outs": "Pitcher Outs",
    "pitcher_hits_allowed": "Hits Allowed",
    "pitcher_walks": "Pitcher Walks",
    "pitcher_earned_runs": "Earned Runs",
    "team_totals": "Team Total",
    "alternate_spreads": "Alt Spread",
    "alternate_totals": "Alt Total",
}

FAIRBET_METHOD_DISPLAY_NAMES: dict[str, str] = {
    "pinnacle_devig": "Pinnacle Devig",
    "pinnacle_extrapolated": "Pinnacle Extrapolated",
}

FAIRBET_METHOD_EXPLANATIONS: dict[str, str] = {
    "pinnacle_devig": "Fair odds derived by removing vig from Pinnacle's line",
    "pinnacle_extrapolated": "Fair odds extrapolated from Pinnacle's reference line using logit-space projection",
}


# Books included in EV comparisons (reputable licensed sportsbooks + sharp books).
# These are the only books available via our configured Odds API regions
# (us, us_ex, eu, uk).
INCLUDED_BOOKS: frozenset[str] = frozenset(
    {
        # US sportsbooks
        "BetMGM",
        "BetRivers",
        "Caesars",
        "DraftKings",
        "FanDuel",
        # EU / sharp
        "Pinnacle",
        "888sport",
        "William Hill",
        # UK sportsbooks
        "Betfair Exchange",
        "Betfair Sportsbook",
        "Ladbrokes",
        "Paddy Power",
        "William Hill (UK)",
    }
)


# ---------------------------------------------------------------------------
# Strategy map: (league, market_category) -> EVStrategyConfig | None
# ---------------------------------------------------------------------------

_PINNACLE_MAINLINE_NBA_NHL = EVStrategyConfig(
    strategy_name="pinnacle_devig",
    eligible_sharp_books=("Pinnacle",),
    min_qualifying_books=3,
    max_reference_staleness_seconds=3600,  # 1 hour
    max_fair_prob_divergence=0.08,  # Tight — mainlines are efficient
)

_PINNACLE_MAINLINE_NCAAB = EVStrategyConfig(
    strategy_name="pinnacle_devig",
    eligible_sharp_books=("Pinnacle",),
    min_qualifying_books=3,
    max_reference_staleness_seconds=1800,  # 30 minutes
    max_fair_prob_divergence=0.10,  # Wider — less liquid
)

_PINNACLE_PLAYER_PROP = EVStrategyConfig(
    strategy_name="pinnacle_devig",
    eligible_sharp_books=("Pinnacle",),
    min_qualifying_books=3,
    max_reference_staleness_seconds=1800,  # 30 minutes
    max_fair_prob_divergence=0.10,  # Thin Pinnacle coverage
)

_PINNACLE_TEAM_PROP = EVStrategyConfig(
    strategy_name="pinnacle_devig",
    eligible_sharp_books=("Pinnacle",),
    min_qualifying_books=3,
    max_reference_staleness_seconds=1800,  # 30 minutes
    max_fair_prob_divergence=0.10,
)

_PINNACLE_ALTERNATE = EVStrategyConfig(
    strategy_name="pinnacle_devig",
    eligible_sharp_books=("Pinnacle",),
    min_qualifying_books=3,
    max_reference_staleness_seconds=1800,  # 30 minutes
    max_fair_prob_divergence=0.12,  # Widest — alt lines inherently have wider vig
)

# Map of (league_code, market_category) -> EVStrategyConfig | None
# None means EV is disabled for that combination.
_STRATEGY_MAP: dict[tuple[str, str], EVStrategyConfig | None] = {
    # NBA
    ("NBA", "mainline"): _PINNACLE_MAINLINE_NBA_NHL,
    ("NBA", "player_prop"): _PINNACLE_PLAYER_PROP,
    ("NBA", "team_prop"): _PINNACLE_TEAM_PROP,
    ("NBA", "alternate"): _PINNACLE_ALTERNATE,
    ("NBA", "period"): None,
    ("NBA", "game_prop"): None,
    # NHL
    ("NHL", "mainline"): _PINNACLE_MAINLINE_NBA_NHL,
    ("NHL", "player_prop"): _PINNACLE_PLAYER_PROP,
    ("NHL", "team_prop"): _PINNACLE_TEAM_PROP,
    ("NHL", "alternate"): _PINNACLE_ALTERNATE,
    ("NHL", "period"): None,
    ("NHL", "game_prop"): None,
    # NCAAB
    ("NCAAB", "mainline"): _PINNACLE_MAINLINE_NCAAB,
    ("NCAAB", "player_prop"): _PINNACLE_PLAYER_PROP,
    ("NCAAB", "team_prop"): _PINNACLE_TEAM_PROP,
    ("NCAAB", "alternate"): _PINNACLE_ALTERNATE,
    ("NCAAB", "period"): None,
    ("NCAAB", "game_prop"): None,
    # MLB
    ("MLB", "mainline"): _PINNACLE_MAINLINE_NBA_NHL,
    ("MLB", "player_prop"): _PINNACLE_PLAYER_PROP,
    ("MLB", "team_prop"): _PINNACLE_TEAM_PROP,
    ("MLB", "alternate"): _PINNACLE_ALTERNATE,
    ("MLB", "period"): None,
    ("MLB", "game_prop"): None,
}


# ---------------------------------------------------------------------------
# Logit-space extrapolation constants
# ---------------------------------------------------------------------------

# Per-sport, per-market logit slope (logit shift per 0.5-point line change).
# Operates in log-odds space so tails naturally compress.
# Calibrated so near 50%, a 1-half-point shift ≈ 1.5% prob (basketball).
# At p=0.50 the logit sensitivity is 0.25, so slope = 0.015/0.25 ≈ 0.06.
# Team totals use ~1.25x game totals (lower team scoring variance, σ≈11-12 vs σ≈15-16).
HALF_POINT_LOGIT_SLOPE: dict[str, dict[str, float]] = {
    "NBA": {"spreads": 0.06, "totals": 0.05, "team_totals": 0.065},
    "NCAAB": {"spreads": 0.07, "totals": 0.06, "team_totals": 0.075},
    "NHL": {"spreads": 0.18, "totals": 0.15, "team_totals": 0.19},
    "MLB": {"spreads": 0.20, "totals": 0.12, "team_totals": 0.15},
}

# Max number of half-points we'll extrapolate (beyond → too uncertain).
# 6 HP = 3 full points for basketball, 4 HP = 2 full goals for hockey.
MAX_EXTRAPOLATION_HALF_POINTS: dict[str, dict[str, int]] = {
    "NBA": {"spreads": 6, "totals": 4, "team_totals": 3},
    "NCAAB": {"spreads": 6, "totals": 4, "team_totals": 3},
    "NHL": {"spreads": 4, "totals": 4, "team_totals": 3},
    "MLB": {"spreads": 4, "totals": 4, "team_totals": 3},
}

# Max divergence (probability space) between extrapolated fair prob and median
# implied prob across non-sharp books.  Catches phantom EV from long-distance
# extrapolation drift (e.g., fair 80% vs market consensus 53%).
MAX_EXTRAPOLATED_PROB_DIVERGENCE: float = 0.07

# Max distance (full points) between two mainline lines before we refuse to
# extrapolate.  Mainline-to-mainline disagreement (e.g., Pinnacle 148.5 vs
# FanDuel 142.5) is market opinion, not an alternate-line relationship.
MAINLINE_DISAGREEMENT_MAX_POINTS: float = 2.0

# Max age (seconds) for a sharp reference used in extrapolation.  Stale
# references can amplify mismatch when market lines move.
SHARP_REF_MAX_AGE_SECONDS: int = 3600


def extrapolation_confidence(non_sharp_book_count: int) -> str:
    """Return confidence tier for an extrapolated market.

    Uses the same book-count logic as direct devig — the tier reflects
    market depth, not derivation method.

    Args:
        non_sharp_book_count: Number of non-sharp books pricing the market.

    Returns:
        "full", "decent", or "thin".
    """
    return market_confidence_tier(non_sharp_book_count)


def get_strategy(league_code: str, market_category: str) -> EVStrategyConfig | None:
    """Look up the EV strategy for a (league, market_category) pair.

    Args:
        league_code: League code (e.g., "NBA", "NHL", "NCAAB", "MLB").
        market_category: Market category (e.g., "mainline", "player_prop").

    Returns:
        EVStrategyConfig if EV is enabled for this combination, None otherwise.
    """
    return _STRATEGY_MAP.get((league_code.upper(), market_category))


def get_fairbet_debug_game_ids() -> frozenset[int]:
    """Return game IDs enabled for verbose EV debug logging.

    Set via FAIRBET_DEBUG_GAME_IDS env var (comma-separated ints).
    Returns empty frozenset when unset or on parse error.
    """
    raw = os.environ.get("FAIRBET_DEBUG_GAME_IDS", "")
    if not raw.strip():
        return frozenset()
    try:
        return frozenset(int(x.strip()) for x in raw.split(",") if x.strip())
    except ValueError:
        return frozenset()
