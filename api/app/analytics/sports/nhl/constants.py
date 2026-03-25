"""Centralized NHL constants.

Single source of truth for league-average baselines, default event
probabilities, and simulation parameters. Import from here instead
of defining local copies.

All baseline values are 2024-25 NHL season approximations.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shot attempt event types (canonical order)
# ---------------------------------------------------------------------------

SHOT_EVENTS: list[str] = [
    "goal",
    "save",
    "blocked_shot",
    "missed_shot",
]

# ---------------------------------------------------------------------------
# Default event probabilities (league-average per shot attempt)
# ---------------------------------------------------------------------------

DEFAULT_EVENT_PROBS: dict[str, float] = {
    "goal": 0.09,
    "save": 0.62,
    "blocked_shot": 0.16,
    "missed_shot": 0.13,
}

# Keyed with ``_probability`` suffix (used by game simulator).
DEFAULT_EVENT_PROBS_SUFFIXED: dict[str, float] = {
    "goal_probability": 0.09,
    "save_probability": 0.62,
    "blocked_shot_probability": 0.16,
    "missed_shot_probability": 0.13,
}

# ---------------------------------------------------------------------------
# League-average baselines
# ---------------------------------------------------------------------------

BASELINE_XGOALS_FOR = 2.80
BASELINE_XGOALS_AGAINST = 2.80
BASELINE_CORSI_PCT = 0.500
BASELINE_FENWICK_PCT = 0.500
BASELINE_SHOOTING_PCT = 0.090
BASELINE_SAVE_PCT = 0.910
BASELINE_PDO = 1.000
BASELINE_SHOTS_PER_GAME = 30.0
BASELINE_HIGH_DANGER_RATE = 0.25  # fraction of shots that are high-danger
BASELINE_HIGH_DANGER_GOAL_PCT = 0.15  # scoring rate on high-danger chances

# ---------------------------------------------------------------------------
# Feature-builder baselines (superset used for normalization)
# ---------------------------------------------------------------------------

FEATURE_BASELINES: dict[str, float] = {
    # Expected goals
    "xgoals_for": BASELINE_XGOALS_FOR,
    "xgoals_against": BASELINE_XGOALS_AGAINST,
    "xgoals_pct": 0.500,
    # Possession metrics
    "corsi_pct": BASELINE_CORSI_PCT,
    "fenwick_pct": BASELINE_FENWICK_PCT,
    # Shooting and goaltending
    "shooting_pct": BASELINE_SHOOTING_PCT,
    "save_pct": BASELINE_SAVE_PCT,
    "pdo": BASELINE_PDO,
    # Volume
    "shots_per_game": BASELINE_SHOTS_PER_GAME,
    "shots_against_per_game": BASELINE_SHOTS_PER_GAME,
    # High-danger chances
    "high_danger_rate": BASELINE_HIGH_DANGER_RATE,
    "high_danger_goal_pct": BASELINE_HIGH_DANGER_GOAL_PCT,
    "high_danger_goals_for": 0.75,
    "high_danger_goals_against": 0.75,
    # Player-level
    "goals": 0.30,
    "assists": 0.50,
    "shots": 3.0,
    "game_score": 0.50,
    "goals_per_60": 0.80,
    "shots_per_60": 8.0,
    # Game-state baselines
    "period": 2.0,
    "score_diff": 0.0,
}

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

PERIODS = 3
SHOTS_PER_PERIOD = 10  # ~30 shots/game / 3 periods per team
OT_SHOTS = 4  # ~5 min OT, fewer shots
MAX_OVERTIMES = 1  # NHL regular season: 1 OT then shootout
SHOOTOUT_ROUNDS = 5  # max shootout rounds before sudden death
SHOOTOUT_GOAL_PROB = 0.33  # ~33% success rate per attempt
