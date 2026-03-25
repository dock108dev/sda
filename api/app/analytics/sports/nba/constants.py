"""Centralized NBA constants.

Single source of truth for league-average baselines, default event
probabilities, and simulation parameters. Import from here instead
of defining local copies.

All baseline values are 2024-25 NBA season approximations.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Possession event types (canonical order)
# ---------------------------------------------------------------------------

POSSESSION_EVENTS: list[str] = [
    "two_pt_make",
    "two_pt_miss",
    "three_pt_make",
    "three_pt_miss",
    "free_throw_trip",
    "turnover",
]

# ---------------------------------------------------------------------------
# Default event probabilities (league-average)
# ---------------------------------------------------------------------------

DEFAULT_EVENT_PROBS: dict[str, float] = {
    "two_pt_make": 0.26,
    "two_pt_miss": 0.16,
    "three_pt_make": 0.126,
    "three_pt_miss": 0.224,
    "free_throw_trip": 0.10,
    "turnover": 0.13,
}

# Keyed with ``_probability`` suffix (used by game simulator).
DEFAULT_EVENT_PROBS_SUFFIXED: dict[str, float] = {
    "two_pt_make_probability": 0.26,
    "three_pt_make_probability": 0.126,
    "three_pt_miss_probability": 0.224,
    "free_throw_trip_probability": 0.10,
    "turnover_probability": 0.13,
}

# ---------------------------------------------------------------------------
# League-average baselines
# ---------------------------------------------------------------------------

BASELINE_PACE = 100.0
BASELINE_OFF_RATING = 114.0
BASELINE_DEF_RATING = 114.0
BASELINE_EFG_PCT = 0.540
BASELINE_TS_PCT = 0.580
BASELINE_TOV_PCT = 0.130
BASELINE_ORB_PCT = 0.250
BASELINE_DRB_PCT = 0.750
BASELINE_FT_RATE = 0.270
BASELINE_FG3_RATE = 0.350
BASELINE_FT_PCT = 0.780
BASELINE_AST_PCT = 0.600

# ---------------------------------------------------------------------------
# Feature-builder baselines (superset used for normalization)
# ---------------------------------------------------------------------------

FEATURE_BASELINES: dict[str, float] = {
    # Ratings
    "off_rating": BASELINE_OFF_RATING,
    "def_rating": BASELINE_DEF_RATING,
    "net_rating": 0.0,
    "pace": BASELINE_PACE,
    # Shooting efficiency
    "efg_pct": BASELINE_EFG_PCT,
    "ts_pct": BASELINE_TS_PCT,
    "fg3_pct": BASELINE_FG3_RATE,
    "ft_pct": BASELINE_FT_PCT,
    "ft_rate": BASELINE_FT_RATE,
    # Possession metrics
    "tov_pct": BASELINE_TOV_PCT,
    "orb_pct": BASELINE_ORB_PCT,
    "drb_pct": BASELINE_DRB_PCT,
    "ast_pct": BASELINE_AST_PCT,
    # Player usage
    "usage_rate": 0.200,
    # Scoring distribution
    "paint_points": 48.0,
    "fastbreak_points": 12.0,
    "second_chance_points": 12.0,
    # Defensive metrics
    "contested_shots": 40.0,
    "deflections": 15.0,
    "steals": 7.5,
    "blocks": 5.0,
}

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

QUARTERS = 4
QUARTER_POSSESSIONS = 25  # ~100 per team per game / 4
OT_POSSESSIONS = 6  # ~5 min OT
MAX_OVERTIMES = 5

# ---------------------------------------------------------------------------
# Points per event
# ---------------------------------------------------------------------------

POINTS_PER_EVENT: dict[str, float] = {
    "two_pt_make": 2,
    "two_pt_miss": 0,
    "three_pt_make": 3,
    "three_pt_miss": 0,
    "free_throw_trip": 1.5,  # avg ~2 FTA, ~78% make rate
    "turnover": 0,
}
