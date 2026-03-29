"""Centralized MLB constants.

Single source of truth for league-average baselines, default event
probabilities, and simulation parameters. Import from here instead
of defining local copies.

All baseline values are 2024 MLB season approximations.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Plate-appearance event types (canonical order)
# ---------------------------------------------------------------------------

PA_EVENTS: list[str] = [
    "strikeout",
    "ball_in_play_out",
    "walk_or_hbp",
    "single",
    "double",
    "triple",
    "home_run",
]

# ---------------------------------------------------------------------------
# Default event probabilities (league-average)
# ---------------------------------------------------------------------------

DEFAULT_EVENT_PROBS: dict[str, float] = {
    "strikeout": 0.22,
    "ball_in_play_out": 0.46,
    "walk_or_hbp": 0.08,
    "single": 0.15,
    "double": 0.05,
    "triple": 0.01,
    "home_run": 0.03,
}

# Keyed with ``_probability`` suffix (used by game simulator).
DEFAULT_EVENT_PROBS_SUFFIXED: dict[str, float] = {
    "strikeout_probability": 0.22,
    "walk_or_hbp_probability": 0.08,
    "single_probability": 0.15,
    "double_probability": 0.05,
    "triple_probability": 0.01,
    "home_run_probability": 0.03,
}

# ---------------------------------------------------------------------------
# League-average baselines (batting / pitching / contact)
# ---------------------------------------------------------------------------

BASELINE_CONTACT_RATE = 0.77
BASELINE_WHIFF_RATE = 0.23
BASELINE_SWING_RATE = 0.50
BASELINE_POWER_INDEX = 1.0
BASELINE_BARREL_RATE = 0.07
BASELINE_STRIKEOUT_RATE = 0.22
BASELINE_WALK_RATE = 0.08
BASELINE_AVG_EXIT_VELOCITY = 88.0
BASELINE_HARD_HIT_RATE = 0.35
BASELINE_CONTACT_SUPPRESSION = 0.0
BASELINE_POWER_SUPPRESSION = 0.0

# Fraction of barrelled balls that become home runs.
# Calibrated for player-level barrel rates (~0.09 for lineup starters)
# so that league-average matchups produce ~3% HR/PA:
#   0.09 * 1.0 * 0.33 ≈ 0.030 (3.0%)
# Previously 0.43, which was correct for team-level barrel rates (0.07)
# but inflated HRs when using per-batter profiles.
BARREL_HR_CONVERSION = 0.33

# BABIP — batting average on balls in play.  ~30% of batted balls in
# play become hits; the rest are fielded outs.  This is the critical
# factor that converts "contact" into a realistic mix of hits vs outs.
BASELINE_BABIP = 0.315

# Hit-type distribution fractions (of non-HR hits, i.e. balls in play
# that fall for a hit).  Must sum to ~1.0.
#   Real MLB split of non-HR hits: singles ~73%, doubles ~22%, triples ~5%.
SINGLE_FRACTION = 0.73
DOUBLE_FRACTION = 0.22
TRIPLE_FRACTION = 0.05

# ---------------------------------------------------------------------------
# Home field advantage
# ---------------------------------------------------------------------------

# Relative boost applied to home team offensive probabilities (walk, single).
# MLB home teams win ~54% of games historically; a 2.5% relative boost on
# contact/walk events produces roughly +0.04 WP shift to match this.
MLB_HFA_BOOST = 0.025

# ---------------------------------------------------------------------------
# Feature-builder baselines (superset used for normalization)
# ---------------------------------------------------------------------------

FEATURE_BASELINES: dict[str, float] = {
    # Derived composites
    "contact_rate": BASELINE_CONTACT_RATE,
    "power_index": BASELINE_POWER_INDEX,
    "barrel_rate": BASELINE_BARREL_RATE,
    "hard_hit_rate": BASELINE_HARD_HIT_RATE,
    "swing_rate": BASELINE_SWING_RATE,
    "whiff_rate": BASELINE_WHIFF_RATE,
    "avg_exit_velocity": BASELINE_AVG_EXIT_VELOCITY,
    "expected_slug": 0.77,
    # Raw plate discipline percentages
    "z_swing_pct": 0.68,
    "o_swing_pct": 0.32,
    "z_contact_pct": 0.84,
    "o_contact_pct": 0.60,
    # Raw quality of contact
    "avg_exit_velo": BASELINE_AVG_EXIT_VELOCITY,
    "hard_hit_pct": BASELINE_HARD_HIT_RATE,
    "barrel_pct": BASELINE_BARREL_RATE,
    # Raw counts (absolute — normalized as ratio to baseline)
    "total_pitches": 145.0,
    "balls_in_play": 30.0,
    "hard_hit_count": 10.0,
    "barrel_count": 2.0,
    "zone_pitches": 65.0,
    "zone_swings": 44.0,
    "zone_contact": 37.0,
    "outside_pitches": 80.0,
    "outside_swings": 26.0,
    "outside_contact": 16.0,
    # Additional derived ratios
    "zone_swing_rate": 0.68,
    "chase_rate": 0.32,
    "zone_contact_rate": 0.84,
    "outside_contact_rate": 0.60,
    "plate_discipline_index": 0.52,
    # Pitcher-specific baselines (from pitcher perspective)
    "k_rate": 0.22,
    "bb_rate": 0.08,
    "hr_rate": 0.03,
    "avg_exit_velo_against": 88.0,
    "hard_hit_pct_against": 0.35,
    "barrel_pct_against": 0.07,
    "contact_suppression": 0.0,
    "power_suppression": 0.0,
    "strikeout_rate": 0.22,
    "walk_rate": 0.08,
    # Standard batting baselines (from boxscore raw_stats)
    "box_avg": 0.250,
    "box_obp": 0.320,
    "box_slg": 0.400,
    "box_iso": 0.150,
    "box_ops": 0.720,
    "box_k_rate": 0.22,
    "box_bb_rate": 0.08,
    "box_hr_rate": 0.03,
    # Traditional pitcher rate baselines (per-9 and ratio stats)
    "era": 4.50,
    "whip": 1.30,
    "k_per_9": 8.5,
    "bb_per_9": 3.2,
    "hr_per_9": 1.2,
    "h_per_9": 9.0,
    # Matchup baselines
    "batter_hand_code": 0.5,
    "pitcher_hand_code": 0.5,
    # Game-state baselines (midpoint approximations)
    "inning": 5.0,
    "outs": 1.0,
    "score_diff": 0.0,
    # Fielding baselines
    "team_oaa": 0.0,
    "team_drs": 0.0,
    "team_defensive_value": 0.0,
}

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

MAX_EXTRA_INNINGS = 10

# ---------------------------------------------------------------------------
# Canonical MLB team abbreviations
# ---------------------------------------------------------------------------

# Excludes All-Star, minor league, and spring training teams that may
# exist in the DB under the MLB league.
MLB_TEAM_ABBRS: frozenset[str] = frozenset({
    "ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET",
    "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SD", "SF", "SEA", "STL", "TB", "TEX", "TOR", "WSH",
})
