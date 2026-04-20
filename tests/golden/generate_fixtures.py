#!/usr/bin/env python3
"""Generate golden corpus fixture files for tests/golden/ (ISSUE-048).

Produces 4 sports × 13 shapes = 52 JSON fixtures organised under
tests/golden/{nfl,nba,mlb,nhl}/ with the enhanced schema required by
ISSUE-048: quality_score_floor, flow_source, expected_flow_skeleton,
forbidden_phrases.

Run from repo root:
    python tests/golden/generate_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Team / player definitions (all fictitious)
# ---------------------------------------------------------------------------

TEAM_PAIRS: dict[str, list[dict[str, Any]]] = {
    "NFL": [
        {
            "home": {"name": "Gridiron Griffins", "abbreviation": "GRG"},
            "away": {"name": "Oakdale Oaks", "abbreviation": "OAK"},
        },
        {
            "home": {"name": "Parkside Panthers", "abbreviation": "PKP"},
            "away": {"name": "Maplewood Marlins", "abbreviation": "MWM"},
        },
    ],
    "NBA": [
        {
            "home": {"name": "Riverside Rockets", "abbreviation": "RVR"},
            "away": {"name": "Hillcrest Hawks", "abbreviation": "HCH"},
        },
        {
            "home": {"name": "Lakewood Legends", "abbreviation": "LWL"},
            "away": {"name": "Bayside Bolts", "abbreviation": "BSB"},
        },
    ],
    "MLB": [
        {
            "home": {"name": "Riverside Runners", "abbreviation": "RVR"},
            "away": {"name": "Hillcrest Hitters", "abbreviation": "HCH"},
        },
        {
            "home": {"name": "Lakewood Lynx", "abbreviation": "LWL"},
            "away": {"name": "Bayside Bats", "abbreviation": "BSB"},
        },
    ],
    "NHL": [
        {
            "home": {"name": "Riverside Raiders", "abbreviation": "RVR"},
            "away": {"name": "Hillcrest Hunters", "abbreviation": "HCH"},
        },
        {
            "home": {"name": "Lakewood Lightning", "abbreviation": "LWL"},
            "away": {"name": "Bayside Blades", "abbreviation": "BSB"},
        },
    ],
}

PLAYERS: dict[str, list[str]] = {
    "GRG": ["Carter Reynolds", "Davis Morgan", "Nguyen Wells", "Harris Thompson", "Johnson Cruz"],
    "OAK": ["Reed Mitchell", "Adams Rivera", "Patel Stone", "Williams Ford", "Brown Kim"],
    "PKP": ["Sanchez Blake", "Turner Hayes", "Collins Grant", "Scott Bailey", "Evans Cole"],
    "MWM": ["Parker Ross", "Edwards Burke", "Murphy Hall", "Price Walsh", "Cook Ward"],
    "RVR": ["Marcus Dalton", "Tyler Vance", "Jamal Stone", "Andre Cooper", "Oscar Dunn"],
    "HCH": ["Devon Marsh", "Kevin Tran", "Elijah Ford", "Nathan Price", "Simon Webb"],
    "LWL": ["Reuben Clarke", "Omar Petrov", "Felix Ortiz", "Leo Huang", "Sam Reeves"],
    "BSB": ["Victor Nkosi", "Dmitri Park", "Anton Solis", "Kai Nguyen", "Ben Flores"],
}

GAME_DATES: dict[str, str] = {
    "NFL": "2025-10-05T13:00:00Z",
    "NBA": "2025-01-15T19:00:00Z",
    "MLB": "2025-05-12T14:05:00Z",
    "NHL": "2025-02-08T19:00:00Z",
}

# ---------------------------------------------------------------------------
# Score-event schema per sport × shape.
#
# Each event tuple: (period, h_score, a_score, play_type, player_slot)
# period  — quarter / inning / hockey period (OT = regulation_periods + 1 …)
# h_score / a_score — cumulative after this play
# play_type — sport-appropriate string
# player_slot — 0-4 index into PLAYERS[abbrev] for the scoring team
# ---------------------------------------------------------------------------

_NFL_SHAPES: dict[str, dict[str, Any]] = {
    "standard_win": {
        "events": [
            (1, 3, 0, "field_goal", 0),
            (1, 3, 7, "touchdown", 0),
            (2, 10, 7, "touchdown", 1),
            (2, 13, 7, "field_goal", 0),
            (3, 13, 14, "touchdown", 1),
            (3, 20, 14, "touchdown", 2),
            (4, 27, 14, "touchdown", 3),
            (4, 27, 17, "field_goal", 2),
        ],
        "final": {"home": 27, "away": 17},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "blowout": {
        "events": [
            (1, 7, 0, "touchdown", 0),
            (1, 14, 0, "touchdown", 1),
            (2, 14, 7, "touchdown", 0),
            (2, 21, 7, "touchdown", 2),
            (2, 24, 7, "field_goal", 0),
            (3, 31, 7, "touchdown", 3),
            (3, 38, 7, "touchdown", 4),
            (4, 38, 14, "touchdown", 1),
            (4, 45, 14, "touchdown", 0),
        ],
        "final": {"home": 45, "away": 14},
        "flow_source": "LLM",
        "quality_score_floor": 35,
        "has_overtime": False,
    },
    "comeback": {
        "events": [
            (1, 0, 7, "touchdown", 0),
            (2, 0, 14, "touchdown", 1),
            (3, 7, 14, "touchdown", 0),
            (3, 10, 14, "field_goal", 0),
            (4, 17, 14, "touchdown", 1),
            (4, 20, 14, "field_goal", 0),
            (4, 20, 17, "field_goal", 2),
            (4, 24, 17, "field_goal", 0),
        ],
        "final": {"home": 24, "away": 17},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "overtime": {
        "events": [
            (1, 7, 0, "touchdown", 0),
            (2, 7, 7, "touchdown", 0),
            (3, 14, 7, "touchdown", 1),
            (4, 14, 14, "touchdown", 1),
            (5, 17, 14, "field_goal", 0),  # OT
        ],
        "final": {"home": 17, "away": 14},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": True,
    },
    "double_overtime": {
        "events": [
            (1, 7, 0, "touchdown", 0),
            (2, 7, 7, "touchdown", 0),
            (3, 7, 14, "touchdown", 1),
            (4, 14, 14, "touchdown", 0),
            (5, 14, 17, "field_goal", 2),  # OT1 — away scores
            (6, 21, 17, "touchdown", 1),   # OT2 — home wins
        ],
        "final": {"home": 21, "away": 17},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": True,
    },
    "incomplete_pbp": {
        "events": [
            (1, 7, 0, "touchdown", 0),
            (2, 7, 7, "touchdown", 0),
            (3, 14, 7, "touchdown", 1),
        ],
        "final": None,
        "flow_source": "LLM",
        "quality_score_floor": 30,
        "has_overtime": False,
    },
    "postponement": {
        "events": [],
        "final": None,
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
        "postponement_reason": "weather",
    },
    "defensive_battle": {
        "events": [
            (1, 3, 0, "field_goal", 0),
            (2, 3, 3, "field_goal", 0),
            (3, 6, 3, "field_goal", 0),
            (4, 6, 6, "field_goal", 1),
            (4, 13, 6, "touchdown", 0),
        ],
        "final": {"home": 13, "away": 6},
        "flow_source": "LLM",
        "quality_score_floor": 38,
        "has_overtime": False,
    },
    "high_scorer": {
        "events": [
            (1, 7, 0, "touchdown", 0),
            (1, 7, 7, "touchdown", 0),
            (2, 14, 7, "touchdown", 1),
            (2, 14, 14, "touchdown", 1),
            (2, 21, 14, "touchdown", 2),
            (3, 21, 21, "touchdown", 2),
            (3, 28, 21, "touchdown", 3),
            (3, 28, 28, "touchdown", 3),
            (4, 35, 28, "touchdown", 4),
            (4, 35, 35, "touchdown", 4),
            (4, 42, 35, "touchdown", 0),
            (4, 42, 42, "touchdown", 0),
            (4, 49, 42, "touchdown", 1),
        ],
        "final": {"home": 49, "away": 42},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "playoff": {
        "events": [
            (1, 3, 0, "field_goal", 0),
            (2, 10, 0, "touchdown", 1),
            (2, 10, 7, "touchdown", 0),
            (3, 10, 10, "field_goal", 2),
            (3, 17, 10, "touchdown", 2),
            (4, 17, 17, "touchdown", 1),
            (4, 24, 17, "touchdown", 0),
        ],
        "final": {"home": 24, "away": 17},
        "flow_source": "LLM",
        "quality_score_floor": 43,
        "has_overtime": False,
    },
    "buzzer_beater": {
        "events": [
            (1, 7, 0, "touchdown", 0),
            (2, 7, 7, "touchdown", 0),
            (3, 7, 10, "field_goal", 1),
            (4, 10, 10, "field_goal", 0),
            (4, 13, 10, "field_goal", 0),  # last-second FG
        ],
        "final": {"home": 13, "away": 10},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "template_fallback": {
        "events": [
            (1, 7, 0, "touchdown", 0),
            (2, 7, 7, "touchdown", 0),
        ],
        "final": {"home": 14, "away": 7},
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
    },
    "tight_finish": {
        "events": [
            (1, 0, 7, "touchdown", 0),
            (2, 7, 7, "touchdown", 0),
            (3, 14, 7, "touchdown", 1),
            (3, 14, 14, "touchdown", 1),
            (4, 17, 14, "field_goal", 0),
            (4, 17, 17, "field_goal", 2),
            (4, 20, 17, "field_goal", 0),
        ],
        "final": {"home": 20, "away": 17},
        "flow_source": "LLM",
        "quality_score_floor": 41,
        "has_overtime": False,
    },
}

_NBA_SHAPES: dict[str, dict[str, Any]] = {
    "standard_win": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (1, 3, 2, "field_goal_2pt", 0),
            (1, 5, 2, "field_goal_2pt", 1),
            (1, 5, 5, "field_goal_3pt", 1),
            (2, 8, 5, "field_goal_3pt", 2),
            (2, 8, 7, "field_goal_2pt", 2),
            (2, 11, 7, "field_goal_3pt", 0),
            (2, 11, 9, "field_goal_2pt", 3),
            (3, 14, 9, "field_goal_3pt", 3),
            (3, 14, 11, "field_goal_2pt", 4),
            (3, 16, 11, "field_goal_2pt", 1),
            (3, 16, 14, "field_goal_3pt", 0),
            (4, 18, 14, "field_goal_2pt", 2),
            (4, 18, 16, "field_goal_2pt", 1),
            (4, 21, 16, "field_goal_3pt", 0),
            (4, 21, 18, "field_goal_2pt", 2),
            (4, 23, 18, "field_goal_2pt", 1),
            (4, 23, 19, "free_throw", 3),
            (4, 26, 19, "field_goal_3pt", 2),
        ],
        "final": {"home": 108, "away": 99},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "blowout": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (1, 6, 0, "field_goal_3pt", 1),
            (1, 8, 0, "field_goal_2pt", 2),
            (1, 8, 2, "field_goal_2pt", 0),
            (2, 11, 2, "field_goal_3pt", 0),
            (2, 14, 2, "field_goal_3pt", 3),
            (2, 14, 4, "field_goal_2pt", 1),
            (2, 17, 4, "field_goal_3pt", 1),
            (2, 20, 4, "field_goal_3pt", 2),
            (3, 23, 4, "field_goal_3pt", 0),
            (3, 23, 6, "field_goal_2pt", 2),
            (3, 26, 6, "field_goal_3pt", 4),
            (4, 28, 6, "field_goal_2pt", 0),
            (4, 28, 8, "field_goal_2pt", 3),
            (4, 31, 8, "field_goal_3pt", 1),
        ],
        "final": {"home": 119, "away": 85},
        "flow_source": "LLM",
        "quality_score_floor": 35,
        "has_overtime": False,
    },
    "comeback": {
        "events": [
            (1, 0, 3, "field_goal_3pt", 0),
            (1, 0, 6, "field_goal_3pt", 1),
            (2, 0, 8, "field_goal_2pt", 2),
            (2, 3, 8, "field_goal_3pt", 0),
            (2, 3, 11, "field_goal_3pt", 0),
            (3, 6, 11, "field_goal_3pt", 1),
            (3, 8, 11, "field_goal_2pt", 2),
            (3, 8, 13, "field_goal_2pt", 3),
            (4, 11, 13, "field_goal_3pt", 0),
            (4, 13, 13, "field_goal_2pt", 1),
            (4, 15, 13, "field_goal_2pt", 2),
            (4, 15, 14, "free_throw", 4),
            (4, 17, 14, "field_goal_2pt", 0),
            (4, 17, 16, "field_goal_2pt", 1),
            (4, 19, 16, "field_goal_2pt", 3),
        ],
        "final": {"home": 104, "away": 99},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "overtime": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (2, 3, 3, "field_goal_3pt", 0),
            (3, 6, 3, "field_goal_3pt", 1),
            (3, 6, 5, "field_goal_2pt", 1),
            (4, 8, 5, "field_goal_2pt", 2),
            (4, 8, 8, "field_goal_3pt", 2),
            (5, 11, 8, "field_goal_3pt", 0),  # OT
            (5, 11, 10, "field_goal_2pt", 3),
            (5, 13, 10, "field_goal_2pt", 1),
        ],
        "final": {"home": 108, "away": 103},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": True,
    },
    "double_overtime": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (2, 3, 3, "field_goal_3pt", 0),
            (3, 6, 3, "field_goal_3pt", 1),
            (4, 6, 6, "field_goal_3pt", 1),
            (5, 8, 6, "field_goal_2pt", 2),   # OT1
            (5, 8, 8, "field_goal_2pt", 2),
            (6, 11, 8, "field_goal_3pt", 0),  # OT2 — home wins
            (6, 11, 10, "field_goal_2pt", 3),
            (6, 13, 10, "field_goal_2pt", 1),
        ],
        "final": {"home": 113, "away": 110},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": True,
    },
    "incomplete_pbp": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (2, 3, 3, "field_goal_3pt", 0),
            (3, 6, 3, "field_goal_3pt", 1),
        ],
        "final": None,
        "flow_source": "LLM",
        "quality_score_floor": 30,
        "has_overtime": False,
    },
    "postponement": {
        "events": [],
        "final": None,
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
        "postponement_reason": "facility",
    },
    "defensive_battle": {
        "events": [
            (1, 2, 0, "field_goal_2pt", 0),
            (1, 2, 2, "field_goal_2pt", 0),
            (2, 4, 2, "field_goal_2pt", 1),
            (2, 4, 4, "field_goal_2pt", 1),
            (3, 7, 4, "field_goal_3pt", 2),
            (3, 7, 6, "field_goal_2pt", 2),
            (4, 9, 6, "field_goal_2pt", 0),
            (4, 9, 7, "free_throw", 3),
            (4, 11, 7, "field_goal_2pt", 1),
        ],
        "final": {"home": 87, "away": 82},
        "flow_source": "LLM",
        "quality_score_floor": 38,
        "has_overtime": False,
    },
    "high_scorer": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (1, 3, 3, "field_goal_3pt", 0),
            (1, 6, 3, "field_goal_3pt", 1),
            (1, 6, 6, "field_goal_3pt", 1),
            (2, 9, 6, "field_goal_3pt", 2),
            (2, 9, 9, "field_goal_3pt", 2),
            (2, 12, 9, "field_goal_3pt", 3),
            (2, 12, 12, "field_goal_3pt", 3),
            (3, 15, 12, "field_goal_3pt", 4),
            (3, 15, 15, "field_goal_3pt", 4),
            (3, 18, 15, "field_goal_3pt", 0),
            (3, 18, 18, "field_goal_3pt", 0),
            (4, 21, 18, "field_goal_3pt", 1),
            (4, 21, 21, "field_goal_3pt", 1),
            (4, 24, 21, "field_goal_3pt", 2),
        ],
        "final": {"home": 138, "away": 131},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "playoff": {
        "events": [
            (1, 2, 0, "field_goal_2pt", 0),
            (2, 2, 2, "field_goal_2pt", 0),
            (2, 5, 2, "field_goal_3pt", 1),
            (3, 5, 4, "field_goal_2pt", 1),
            (3, 7, 4, "field_goal_2pt", 2),
            (3, 7, 6, "field_goal_2pt", 2),
            (4, 9, 6, "field_goal_2pt", 0),
            (4, 9, 7, "free_throw", 3),
            (4, 11, 7, "field_goal_2pt", 1),
            (4, 11, 9, "field_goal_2pt", 4),
            (4, 13, 9, "field_goal_2pt", 2),
        ],
        "final": {"home": 102, "away": 98},
        "flow_source": "LLM",
        "quality_score_floor": 43,
        "has_overtime": False,
    },
    "buzzer_beater": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (2, 3, 3, "field_goal_3pt", 0),
            (3, 5, 3, "field_goal_2pt", 1),
            (3, 5, 5, "field_goal_2pt", 1),
            (4, 7, 5, "field_goal_2pt", 2),
            (4, 7, 7, "field_goal_2pt", 2),
            (4, 10, 7, "field_goal_3pt", 0),  # buzzer beater
        ],
        "final": {"home": 97, "away": 96},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "template_fallback": {
        "events": [
            (1, 3, 0, "field_goal_3pt", 0),
            (2, 3, 3, "field_goal_3pt", 0),
        ],
        "final": {"home": 88, "away": 74},
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
    },
    "tight_finish": {
        "events": [
            (1, 0, 3, "field_goal_3pt", 0),
            (2, 3, 3, "field_goal_3pt", 0),
            (2, 3, 5, "field_goal_2pt", 1),
            (3, 5, 5, "field_goal_2pt", 1),
            (3, 7, 5, "field_goal_2pt", 2),
            (4, 7, 7, "field_goal_2pt", 2),
            (4, 9, 7, "field_goal_2pt", 0),
            (4, 9, 8, "free_throw", 3),
            (4, 11, 8, "field_goal_2pt", 1),
        ],
        "final": {"home": 101, "away": 99},
        "flow_source": "LLM",
        "quality_score_floor": 41,
        "has_overtime": False,
    },
}

_MLB_SHAPES: dict[str, dict[str, Any]] = {
    "standard_win": {
        "events": [
            (1, 1, 0, "home_run", 0),
            (2, 1, 1, "single", 0),
            (3, 2, 1, "home_run", 1),
            (4, 2, 2, "double", 1),
            (5, 3, 2, "single", 2),
            (6, 3, 3, "home_run", 2),
            (7, 4, 3, "home_run", 3),
            (8, 4, 4, "single", 3),
            (9, 5, 4, "single", 4),
        ],
        "final": {"home": 5, "away": 4},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "blowout": {
        "events": [
            (1, 3, 0, "home_run", 0),  # 3-run HR
            (2, 4, 0, "single", 1),
            (3, 5, 0, "home_run", 2),
            (3, 7, 0, "home_run", 0),  # 2-run HR
            (4, 7, 1, "single", 0),
            (5, 9, 1, "home_run", 3),  # 2-run HR
            (5, 11, 1, "home_run", 4),
            (6, 11, 2, "double", 1),
            (7, 12, 2, "single", 0),
        ],
        "final": {"home": 12, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 35,
        "has_overtime": False,
    },
    "comeback": {
        "events": [
            (1, 0, 2, "home_run", 0),
            (3, 0, 3, "single", 1),
            (5, 1, 3, "home_run", 0),
            (6, 2, 3, "single", 1),
            (7, 3, 3, "double", 2),
            (8, 4, 3, "home_run", 0),
            (8, 4, 4, "single", 2),
            (9, 5, 4, "single", 3),
        ],
        "final": {"home": 5, "away": 4},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "overtime": {
        # Extra innings (inning 10 = overtime)
        "events": [
            (2, 1, 0, "home_run", 0),
            (4, 1, 1, "single", 0),
            (6, 2, 1, "double", 1),
            (8, 2, 2, "home_run", 1),
            (10, 3, 2, "single", 2),  # extra inning
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": True,
    },
    "double_overtime": {
        # Two extra innings (11 = OT2)
        "events": [
            (1, 1, 0, "single", 0),
            (4, 1, 1, "home_run", 0),
            (7, 2, 1, "double", 1),
            (9, 2, 2, "single", 1),
            (10, 2, 2, "strikeout", 2),  # OT1 scoreless (non-scoring play)
            (11, 3, 2, "single", 0),     # OT2 — home wins
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": True,
    },
    "incomplete_pbp": {
        "events": [
            (1, 1, 0, "home_run", 0),
            (2, 1, 1, "single", 0),
        ],
        "final": None,
        "flow_source": "LLM",
        "quality_score_floor": 30,
        "has_overtime": False,
    },
    "postponement": {
        "events": [],
        "final": None,
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
        "postponement_reason": "weather",
    },
    "defensive_battle": {
        "events": [
            (3, 1, 0, "single", 0),
            (6, 1, 1, "home_run", 0),
            (9, 2, 1, "single", 1),
        ],
        "final": {"home": 2, "away": 1},
        "flow_source": "LLM",
        "quality_score_floor": 38,
        "has_overtime": False,
    },
    "high_scorer": {
        "events": [
            (1, 3, 0, "home_run", 0),
            (1, 4, 0, "single", 1),
            (2, 4, 2, "home_run", 0),
            (3, 5, 2, "single", 2),
            (4, 5, 4, "home_run", 1),
            (4, 5, 5, "single", 2),
            (5, 7, 5, "home_run", 3),
            (6, 7, 6, "single", 3),
            (7, 9, 6, "home_run", 4),
            (8, 9, 7, "double", 4),
            (9, 10, 7, "home_run", 0),
        ],
        "final": {"home": 10, "away": 7},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "playoff": {
        "events": [
            (1, 1, 0, "home_run", 0),
            (3, 1, 1, "single", 0),
            (5, 2, 1, "double", 1),
            (7, 2, 2, "home_run", 1),
            (8, 3, 2, "single", 2),
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 43,
        "has_overtime": False,
    },
    "buzzer_beater": {
        # Walk-off hit in the bottom of the 9th
        "events": [
            (2, 0, 1, "single", 0),
            (5, 1, 1, "home_run", 0),
            (7, 1, 2, "home_run", 1),
            (9, 2, 2, "double", 2),   # tie
            (9, 3, 2, "single", 0),   # walk-off
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "template_fallback": {
        "events": [
            (1, 1, 0, "home_run", 0),
        ],
        "final": {"home": 7, "away": 2},
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
    },
    "tight_finish": {
        "events": [
            (1, 0, 1, "single", 0),
            (3, 1, 1, "home_run", 0),
            (5, 1, 2, "double", 1),
            (7, 2, 2, "single", 1),
            (8, 2, 2, "strikeout", 2),
            (9, 3, 2, "single", 2),
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 41,
        "has_overtime": False,
    },
}

_NHL_SHAPES: dict[str, dict[str, Any]] = {
    "standard_win": {
        "events": [
            (1, 1, 0, "goal", 0),
            (2, 1, 1, "goal", 0),
            (2, 2, 1, "goal", 1),
            (3, 2, 2, "goal", 1),
            (3, 3, 2, "goal", 2),
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "blowout": {
        "events": [
            (1, 1, 0, "goal", 0),
            (1, 2, 0, "power_play_goal", 1),
            (1, 3, 0, "goal", 2),
            (2, 3, 1, "goal", 0),
            (2, 4, 1, "goal", 3),
            (2, 5, 1, "power_play_goal", 4),
            (3, 6, 1, "goal", 0),
        ],
        "final": {"home": 6, "away": 1},
        "flow_source": "LLM",
        "quality_score_floor": 35,
        "has_overtime": False,
    },
    "comeback": {
        "events": [
            (1, 0, 1, "goal", 0),
            (1, 0, 2, "power_play_goal", 1),
            (2, 1, 2, "goal", 0),
            (2, 2, 2, "goal", 1),
            (3, 2, 2, "power_play_goal", 2),
            (3, 3, 2, "goal", 0),
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "overtime": {
        "events": [
            (1, 1, 0, "goal", 0),
            (2, 1, 1, "goal", 0),
            (3, 2, 1, "goal", 1),
            (3, 2, 2, "goal", 1),
            (4, 3, 2, "goal", 2),  # OT
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": True,
    },
    "double_overtime": {
        "events": [
            (1, 1, 0, "goal", 0),
            (2, 1, 1, "goal", 0),
            (3, 1, 1, "power_play_goal", 1),
            (3, 2, 1, "goal", 1),
            (4, 2, 2, "goal", 2),   # OT1 — away scores
            (5, 3, 2, "goal", 0),   # OT2 — home wins
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": True,
    },
    "incomplete_pbp": {
        "events": [
            (1, 1, 0, "goal", 0),
            (2, 1, 1, "goal", 0),
        ],
        "final": None,
        "flow_source": "LLM",
        "quality_score_floor": 30,
        "has_overtime": False,
    },
    "postponement": {
        "events": [],
        "final": None,
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
        "postponement_reason": "weather",
    },
    "defensive_battle": {
        "events": [
            (2, 1, 0, "goal", 0),
            (3, 1, 1, "goal", 0),
            (3, 2, 1, "power_play_goal", 1),
        ],
        "final": {"home": 2, "away": 1},
        "flow_source": "LLM",
        "quality_score_floor": 38,
        "has_overtime": False,
    },
    "high_scorer": {
        "events": [
            (1, 1, 0, "goal", 0),
            (1, 2, 0, "power_play_goal", 1),
            (1, 2, 1, "goal", 0),
            (2, 3, 1, "goal", 2),
            (2, 3, 2, "goal", 1),
            (2, 4, 2, "power_play_goal", 3),
            (3, 4, 3, "goal", 2),
            (3, 5, 3, "goal", 4),
            (3, 5, 4, "goal", 3),
            (3, 6, 4, "goal", 0),
        ],
        "final": {"home": 6, "away": 4},
        "flow_source": "LLM",
        "quality_score_floor": 40,
        "has_overtime": False,
    },
    "playoff": {
        "events": [
            (1, 1, 0, "goal", 0),
            (2, 1, 1, "goal", 0),
            (2, 2, 1, "power_play_goal", 1),
            (3, 2, 2, "goal", 1),
            (3, 3, 2, "goal", 2),
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 43,
        "has_overtime": False,
    },
    "buzzer_beater": {
        # Goal with < 1 minute left in the 3rd period
        "events": [
            (1, 1, 0, "goal", 0),
            (2, 1, 1, "goal", 0),
            (3, 2, 1, "goal", 1),
            (3, 2, 2, "goal", 1),
            (3, 3, 2, "goal", 2),   # late goal
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 42,
        "has_overtime": False,
    },
    "template_fallback": {
        "events": [
            (1, 1, 0, "goal", 0),
        ],
        "final": {"home": 4, "away": 1},
        "flow_source": "TEMPLATE",
        "quality_score_floor": 0,
        "has_overtime": False,
    },
    "tight_finish": {
        "events": [
            (1, 0, 1, "goal", 0),
            (2, 1, 1, "goal", 0),
            (3, 1, 2, "goal", 1),
            (3, 2, 2, "goal", 1),
            (3, 3, 2, "power_play_goal", 2),
        ],
        "final": {"home": 3, "away": 2},
        "flow_source": "LLM",
        "quality_score_floor": 41,
        "has_overtime": False,
    },
}

ALL_SHAPES: dict[str, dict[str, dict[str, Any]]] = {
    "NFL": _NFL_SHAPES,
    "NBA": _NBA_SHAPES,
    "MLB": _MLB_SHAPES,
    "NHL": _NHL_SHAPES,
}

# Expected block role sequences per game shape.
# Roles: SETUP (always first), MOMENTUM_SHIFT, RESPONSE, DECISION_POINT, RESOLUTION (always last).
# These represent the ideal LLM pipeline output for each narrative arc.
_EXPECTED_BLOCKS: dict[str, list[str]] = {
    "standard_win":     ["SETUP", "MOMENTUM_SHIFT", "RESPONSE", "RESOLUTION"],
    "blowout":          ["SETUP", "MOMENTUM_SHIFT", "RESOLUTION"],
    "comeback":         ["SETUP", "MOMENTUM_SHIFT", "RESPONSE", "DECISION_POINT", "RESOLUTION"],
    "overtime":         ["SETUP", "MOMENTUM_SHIFT", "DECISION_POINT", "RESOLUTION"],
    "double_overtime":  ["SETUP", "MOMENTUM_SHIFT", "RESPONSE", "DECISION_POINT", "RESOLUTION"],
    "incomplete_pbp":   ["SETUP", "RESPONSE", "RESOLUTION"],
    "postponement":     ["SETUP"],
    "defensive_battle": ["SETUP", "DECISION_POINT", "RESOLUTION"],
    "high_scorer":      ["SETUP", "MOMENTUM_SHIFT", "RESPONSE", "RESOLUTION"],
    "playoff":          ["SETUP", "MOMENTUM_SHIFT", "DECISION_POINT", "RESOLUTION"],
    "buzzer_beater":    ["SETUP", "MOMENTUM_SHIFT", "DECISION_POINT", "RESOLUTION"],
    "template_fallback":["SETUP", "MOMENTUM_SHIFT", "RESPONSE", "RESOLUTION"],
    "tight_finish":     ["SETUP", "MOMENTUM_SHIFT", "DECISION_POINT", "RESOLUTION"],
}

# ---------------------------------------------------------------------------
# Play description builders
# ---------------------------------------------------------------------------

def _player_name(sport: str, abbrev: str, slot: int) -> str:
    return PLAYERS.get(abbrev, [f"Player{i}" for i in range(5)])[slot % 5]


def _clock(sport: str, period: int, play_idx: int) -> str:
    if sport == "NFL":
        minutes = max(0, 14 - (play_idx * 3 % 15))
        return f"{minutes:02d}:{(30 if play_idx % 2 else 0):02d}"
    if sport == "NBA":
        minutes = max(0, 11 - (play_idx * 2 % 12))
        return f"{minutes:02d}:{(45 if play_idx % 2 else 0):02d}"
    if sport == "NHL":
        minutes = min(18, play_idx * 3 % 20)
        return f"{minutes:02d}:{(27 if play_idx % 2 else 0):02d}"
    return "00:00"  # MLB uses inning logic


def _description(sport: str, play_type: str, player: str, h: int, a: int) -> str:
    score = f"{h}-{a}"
    if sport == "NFL":
        if play_type == "touchdown":
            return f"{player} touchdown, PAT good ({score})"
        if play_type == "field_goal":
            return f"{player.split()[-1]} {35 + (h + a) % 15}-yd field goal ({score})"
        if play_type in ("rush", "pass"):
            return f"{player} {play_type} for 6 yards"
        return f"{player} {play_type}"
    if sport == "NBA":
        if play_type == "field_goal_3pt":
            return f"{player} 3-pt make ({score})"
        if play_type == "field_goal_2pt":
            return f"{player} 2-pt make ({score})"
        if play_type == "free_throw":
            return f"{player} free throw ({score})"
        if play_type == "turnover":
            return f"{player} turnover"
        return f"{player} {play_type}"
    if sport == "MLB":
        if play_type == "home_run":
            return f"{player} home run ({score})"
        if play_type == "single":
            return f"{player} single, run scores ({score})"
        if play_type == "double":
            return f"{player} double, run scores ({score})"
        if play_type in ("strikeout", "groundout", "flyout"):
            return f"{player} {play_type}"
        return f"{player} {play_type}"
    if sport == "NHL":
        if play_type in ("goal", "power_play_goal"):
            return f"{player} goal ({score})"
        if play_type == "save":
            return f"Save by {player.split()[-1]}"
        return f"{player} {play_type}"
    return f"{player} {play_type}"


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

def _build_plays(
    sport: str,
    events: list[tuple],
    home_abbrev: str,
    away_abbrev: str,
) -> list[dict[str, Any]]:
    """Convert score-event tuples into play dicts."""
    plays: list[dict[str, Any]] = []
    prev_h, prev_a = 0, 0

    for i, (period, h, a, play_type, slot) in enumerate(events, 1):
        # Determine which team is scoring (or neither for non-scoring plays)
        if h > prev_h:
            team_abbrev = home_abbrev
        elif a > prev_a:
            team_abbrev = away_abbrev
        else:
            team_abbrev = home_abbrev  # non-scoring play, attribute to home

        player = _player_name(sport, team_abbrev, slot)
        plays.append(
            {
                "play_index": i,
                "quarter": period,
                "game_clock": _clock(sport, period, i),
                "play_type": play_type,
                "team_abbreviation": team_abbrev,
                "player_id": f"{team_abbrev.lower()}-p{slot + 1}",
                "player_name": player,
                "description": _description(sport, play_type, player, h, a),
                "home_score": h,
                "away_score": a,
                "raw_data": {},
            }
        )
        prev_h, prev_a = h, a

    return plays


def _block_count_range(shape_data: dict[str, Any]) -> list[int]:
    if shape_data["flow_source"] == "TEMPLATE":
        return [4, 4]
    n_events = len(shape_data["events"])
    if n_events <= 3:
        return [1, 4]
    if n_events <= 6:
        return [2, 5]
    return [3, 7]


def _expected_block_type_counts(shape: str) -> dict[str, int]:
    """Return per-role counts derived from _EXPECTED_BLOCKS for the given shape."""
    roles = _EXPECTED_BLOCKS.get(shape, ["SETUP", "RESOLUTION"])
    counts: dict[str, int] = {}
    for role in roles:
        counts[role] = counts.get(role, 0) + 1
    return counts


def build_fixture(
    sport: str,
    shape: str,
    shape_data: dict[str, Any],
    team_pair_idx: int = 0,
) -> dict[str, Any]:
    pair = TEAM_PAIRS[sport][team_pair_idx % len(TEAM_PAIRS[sport])]
    home = pair["home"]
    away = pair["away"]
    home_abbrev = home["abbreviation"]
    away_abbrev = away["abbreviation"]

    corpus_id = f"{sport.lower()}_{shape}"
    plays = _build_plays(sport, shape_data["events"], home_abbrev, away_abbrev)
    expected_blocks = _EXPECTED_BLOCKS.get(shape, ["SETUP", "RESOLUTION"])

    fixture: dict[str, Any] = {
        "corpus_id": corpus_id,
        "sport": sport,
        "game_shape": shape,
        "flow_source": shape_data["flow_source"],
        "quality_score_floor": shape_data["quality_score_floor"],
        "forbidden_phrases": 0,
        "source_game_key": f"{sport.lower()}-golden-{shape}",
        "game_date": GAME_DATES[sport],
        "home_team": home,
        "away_team": away,
        "final_score": shape_data["final"],
        "expected_blocks": expected_blocks,
        "expected_block_type_counts": _expected_block_type_counts(shape),
        "expected_flow_skeleton": {
            "block_count_range": _block_count_range(shape_data),
            "roles_required": ["SETUP", "RESOLUTION"],
            "has_overtime": shape_data["has_overtime"],
        },
        "pbp": {
            "source_game_key": f"{sport.lower()}-golden-{shape}",
            "plays": plays,
        },
    }

    if "postponement_reason" in shape_data:
        fixture["postponement_reason"] = shape_data["postponement_reason"]
    else:
        fixture["postponement_reason"] = None

    return fixture


def generate_all() -> None:
    total = 0
    for sport, shapes in ALL_SHAPES.items():
        sport_dir = GOLDEN_DIR / sport.lower()
        sport_dir.mkdir(parents=True, exist_ok=True)

        # Alternate team pairs for variety across shapes
        for idx, (shape, shape_data) in enumerate(shapes.items()):
            fixture = build_fixture(sport, shape, shape_data, team_pair_idx=idx % 2)
            out_path = sport_dir / f"{sport.lower()}_{shape}.json"
            with open(out_path, "w") as f:
                json.dump(fixture, f, indent=2)
            total += 1

    print(f"Generated {total} fixtures under {GOLDEN_DIR}/")
    for sport in ALL_SHAPES:
        sport_dir = GOLDEN_DIR / sport.lower()
        count = len(list(sport_dir.glob("*.json")))
        template_count = sum(
            1
            for p in sport_dir.glob("*.json")
            if json.loads(p.read_text()).get("flow_source") == "TEMPLATE"
        )
        print(f"  {sport}: {count} fixtures ({template_count} TEMPLATE)")


if __name__ == "__main__":
    generate_all()
