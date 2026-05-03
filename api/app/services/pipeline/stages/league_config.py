"""League-specific configuration for gameflow pipeline.

Centralizes sport-aware thresholds so every downstream file can import
from one place instead of hardcoding NBA defaults.
"""

from __future__ import annotations

from typing import Any

# NBA defaults serve as the baseline; other leagues override specific keys.
_NBA_DEFAULTS: dict[str, Any] = {
    "regulation_periods": 4,
    "momentum_swing": 8,
    "deficit_overcome": 6,
    "close_game_margin": 7,
    "close_game_swing": 4,
    "close_game_deficit": 2,
    "late_game_period": 4,
    "blowout_margin": 15,
    "garbage_time_margin": 15,
    "garbage_time_period": 3,
    "scoring_run_min": 8,
    "meaningful_lead": 10,
    "period_noun": "quarter",
    "score_noun": "point",
    "extra_period_label": "overtime",
}

LEAGUE_CONFIG: dict[str, dict[str, Any]] = {
    "NBA": {**_NBA_DEFAULTS},
    "MLB": {
        **_NBA_DEFAULTS,
        "regulation_periods": 9,
        "momentum_swing": 3,
        "deficit_overcome": 3,
        "close_game_margin": 3,
        "close_game_swing": 2,
        "close_game_deficit": 1,
        "late_game_period": 7,
        "blowout_margin": 8,
        "garbage_time_margin": 10,
        "garbage_time_period": 7,
        "scoring_run_min": 3,
        "meaningful_lead": 3,
        "period_noun": "inning",
        "score_noun": "run",
        "extra_period_label": "extra innings",
    },
    "NHL": {
        **_NBA_DEFAULTS,
        "regulation_periods": 3,
        "late_game_period": 3,
        "meaningful_lead": 2,
        "period_noun": "period",
        "extra_period_label": "overtime",
    },
    "NCAAB": {
        **_NBA_DEFAULTS,
        "regulation_periods": 2,
        "late_game_period": 2,
        "period_noun": "half",
        "extra_period_label": "overtime",
    },
    "NFL": {
        **_NBA_DEFAULTS,
        "regulation_periods": 4,
        "momentum_swing": 14,
        "deficit_overcome": 10,
        "close_game_margin": 7,
        "close_game_swing": 7,
        "close_game_deficit": 3,
        "late_game_period": 4,
        "blowout_margin": 21,
        "garbage_time_margin": 21,
        "garbage_time_period": 3,
        "scoring_run_min": 10,
        "meaningful_lead": 10,
        "period_noun": "quarter",
        "score_noun": "point",
        "extra_period_label": "overtime",
    },
}


def get_config(league_code: str) -> dict[str, Any]:
    """Return league config. Raises KeyError for unconfigured leagues."""
    code = league_code.upper()
    if code not in LEAGUE_CONFIG:
        raise KeyError(
            f"No pipeline config for league '{code}'. "
            f"Valid: {', '.join(LEAGUE_CONFIG.keys())}"
        )
    return LEAGUE_CONFIG[code]


# Sport-specific flow thresholds consumed by archetype classification,
# boundary selection, evidence selection, and prompt generation.
#
# Keys are intentionally descriptive rather than reusing names from
# LEAGUE_CONFIG so downstream code can opt into the new vocabulary
# without disrupting existing call sites.
_NBA_FLOW_THRESHOLDS: dict[str, Any] = {
    # Lead size milestones (point margin).
    "lead_created": 6,
    "meaningful_lead": 10,
    "large_lead": 15,
    # Comeback: deficit reduced by this many points within a stretch.
    "comeback_pressure": 7,
    # Clutch window: within `clutch_window_pts` points inside the final
    # `clutch_window_minutes` of regulation.
    "clutch_window_pts": 5,
    "clutch_window_minutes": 5,
    # Game considered out of reach when lead >= game_out_of_reach_lead
    # with fewer than game_out_of_reach_minutes remaining.
    "game_out_of_reach_lead": 15,
    "game_out_of_reach_minutes": 2,
    # Scoring run: scoring_run_pts for one team while opponent scores
    # at most scoring_run_opp_pts.
    "scoring_run_pts": 8,
    "scoring_run_opp_pts": 0,
}

# NCAAB shares NBA scoring dynamics; flow thresholds mirror NBA values.
# Period-structure differences (2 halves vs 4 quarters) are handled by
# LEAGUE_CONFIG (regulation_periods, period_noun) rather than here.
_NCAAB_FLOW_THRESHOLDS: dict[str, Any] = {**_NBA_FLOW_THRESHOLDS}

_MLB_FLOW_THRESHOLDS: dict[str, Any] = {
    "multi_run_inning": 2,
    "major_inning": 4,
    # 7+ run margin once the game has reached `blowout_after_inning`.
    "blowout_run_margin": 7,
    "blowout_after_inning": 5,
    # Late leverage begins this inning onward.
    "late_leverage_inning": 7,
    # Combined runs at or below this threshold flag a low-scoring game.
    "low_scoring_combined": 4,
    # Losing team run total that qualifies as a shutout.
    "shutout": 0,
    # 4+ runs across the first 2 innings.
    "early_avalanche_runs": 4,
    "early_avalanche_innings": 2,
}

_NHL_FLOW_THRESHOLDS: dict[str, Any] = {
    # Goal margin entering the third period.
    "close_game_entering_third": 1,
    "safe_entering_third": 2,
    # Tying goal scored inside the final N minutes of regulation.
    "late_tying_goal_window_minutes": 5,
    # Boolean rule: power-play goal counts as a swing only when it
    # changes lead/tie state or creates separation.
    "power_play_swing_requires_state_change": True,
}

FLOW_THRESHOLDS: dict[str, dict[str, Any]] = {
    "NBA": _NBA_FLOW_THRESHOLDS,
    "MLB": _MLB_FLOW_THRESHOLDS,
    "NHL": _NHL_FLOW_THRESHOLDS,
    "NCAAB": _NCAAB_FLOW_THRESHOLDS,
}


def get_flow_thresholds(league_code: str | None) -> dict[str, Any]:
    """Return sport-specific flow thresholds for the given league.

    Unknown or missing league codes fall back to NBA thresholds, matching
    the documented league_config fallback policy. Returned dict is a copy
    so callers cannot mutate the module-level configuration.
    """
    code = (league_code or "").upper()
    return dict(FLOW_THRESHOLDS.get(code, _NBA_FLOW_THRESHOLDS))
