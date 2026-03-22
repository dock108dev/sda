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
        "period_noun": "inning",
        "score_noun": "run",
        "extra_period_label": "extra innings",
    },
    "NHL": {
        **_NBA_DEFAULTS,
        "regulation_periods": 3,
        "late_game_period": 3,
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
