"""Centralized NFL constants.

Single source of truth for league-average baselines, default drive
outcome probabilities, and simulation parameters.

All baseline values are 2024 NFL season approximations.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Drive outcome types (canonical order)
# ---------------------------------------------------------------------------

DRIVE_OUTCOMES: list[str] = [
    "touchdown",
    "field_goal",
    "punt",
    "turnover",
    "turnover_on_downs",
    "end_of_half",
]

# ---------------------------------------------------------------------------
# Default drive outcome probabilities (league-average)
# ---------------------------------------------------------------------------
# Based on ~2024 NFL season: ~12 drives per team per game.

DEFAULT_DRIVE_PROBS: dict[str, float] = {
    "touchdown": 0.22,
    "field_goal": 0.12,
    "punt": 0.45,
    "turnover": 0.12,
    "turnover_on_downs": 0.04,
    "end_of_half": 0.05,
}

# Keyed with ``_probability`` suffix (used by game simulator).
DEFAULT_DRIVE_PROBS_SUFFIXED: dict[str, float] = {
    "touchdown_probability": 0.22,
    "field_goal_probability": 0.12,
    "punt_probability": 0.45,
    "turnover_probability": 0.12,
    "turnover_on_downs_probability": 0.04,
    "end_of_half_probability": 0.05,
}

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

EXTRA_POINT_SUCCESS_RATE = 0.94
TWO_POINT_SUCCESS_RATE = 0.48
TWO_POINT_ATTEMPT_RATE = 0.06  # ~6% of TDs go for 2
FIELD_GOAL_SUCCESS_RATE = 0.85  # league average across all distances

# ---------------------------------------------------------------------------
# League-average baselines
# ---------------------------------------------------------------------------

BASELINE_EPA_PER_PLAY = 0.0
BASELINE_PASS_RATE = 0.58
BASELINE_SUCCESS_RATE = 0.45
BASELINE_EXPLOSIVE_RATE = 0.08
BASELINE_TURNOVER_RATE = 0.12  # per drive
BASELINE_CPOE = 0.0
BASELINE_SACK_RATE = 0.065  # sacks per pass attempt

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

DRIVES_PER_HALF = 6  # ~12 per team per game / 2 halves
MAX_OVERTIMES = 1  # NFL regular season
OT_DRIVES = 2  # each team gets at least 1 drive in OT
