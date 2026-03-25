"""Centralized NCAAB constants.

Single source of truth for league-average baselines, default event
probabilities, and simulation parameters. Import from here instead
of defining local copies.

All baseline values are 2024-25 NCAAB D1 season approximations.
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
    "offensive_rebound",
]

# ---------------------------------------------------------------------------
# Default event probabilities (league-average, per possession)
# ---------------------------------------------------------------------------
# Note: ``offensive_rebound`` is a meta-event handled by the simulator on
# missed shots. These six probabilities sum to 1.0.

DEFAULT_EVENT_PROBS: dict[str, float] = {
    "two_pt_make": 0.220,       # ~53% of poss are 2PT att, ~48% make
    "two_pt_miss": 0.238,       # ~53% of poss are 2PT att, ~52% miss (before ORB)
    "three_pt_make": 0.102,     # ~30% of poss are 3PT att, ~34% make
    "three_pt_miss": 0.198,     # ~30% of poss are 3PT att, ~66% miss
    "free_throw_trip": 0.072,   # ~7.2% of possessions result in FT trip
    "turnover": 0.170,          # ~17% turnover rate
}

# Keyed with ``_probability`` suffix (used by game simulator).
DEFAULT_EVENT_PROBS_SUFFIXED: dict[str, float] = {
    "two_pt_make_probability": 0.220,
    "three_pt_make_probability": 0.102,
    "three_pt_miss_probability": 0.198,
    "free_throw_trip_probability": 0.072,
    "turnover_probability": 0.170,
}

# ---------------------------------------------------------------------------
# League-average baselines (four-factor model)
# ---------------------------------------------------------------------------

BASELINE_PACE = 68.0
BASELINE_OFF_RATING = 105.0
BASELINE_DEF_RATING = 105.0
BASELINE_OFF_EFG_PCT = 0.500
BASELINE_OFF_TOV_PCT = 0.170
BASELINE_OFF_ORB_PCT = 0.280
BASELINE_OFF_FT_RATE = 0.300
BASELINE_DEF_EFG_PCT = 0.500
BASELINE_DEF_TOV_PCT = 0.170
BASELINE_DEF_ORB_PCT = 0.280
BASELINE_DEF_FT_RATE = 0.300
BASELINE_FG3_RATE = 0.360
BASELINE_FT_PCT = 0.700

# ---------------------------------------------------------------------------
# Feature-builder baselines (superset used for normalization)
# ---------------------------------------------------------------------------

FEATURE_BASELINES: dict[str, float] = {
    # Offensive four factors
    "off_rating": BASELINE_OFF_RATING,
    "off_efg_pct": BASELINE_OFF_EFG_PCT,
    "off_tov_pct": BASELINE_OFF_TOV_PCT,
    "off_orb_pct": BASELINE_OFF_ORB_PCT,
    "off_ft_rate": BASELINE_OFF_FT_RATE,
    # Defensive four factors
    "def_rating": BASELINE_DEF_RATING,
    "def_efg_pct": BASELINE_DEF_EFG_PCT,
    "def_tov_pct": BASELINE_DEF_TOV_PCT,
    "def_orb_pct": BASELINE_DEF_ORB_PCT,
    "def_ft_rate": BASELINE_DEF_FT_RATE,
    # Pace & efficiency
    "pace": BASELINE_PACE,
    "net_rating": 0.0,
    "fg3_rate": BASELINE_FG3_RATE,
    "ft_pct": BASELINE_FT_PCT,
    # Player-level baselines
    "off_rating_player": BASELINE_OFF_RATING,
    "usage_rate": 0.200,
    "ts_pct": 0.540,
    "efg_pct": BASELINE_OFF_EFG_PCT,
    "game_score": 10.0,
    "points": 12.0,
    "rebounds": 5.0,
    "assists": 3.0,
}

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

HALVES = 2
HALF_POSSESSIONS = 34       # ~68 per team per game / 2 halves
OT_POSSESSIONS = 8          # 5-minute OT
MAX_OVERTIMES = 5
ORB_CHANCE = 0.28            # offensive rebound probability on missed shots
MAX_CONSECUTIVE_ORBS = 3     # cap to prevent infinite loops
