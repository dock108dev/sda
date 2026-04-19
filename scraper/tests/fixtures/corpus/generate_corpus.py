"""
Corpus generator — creates 50 PBP fixture files + 50 reference narrative files.

Run once (or re-run to regenerate):
    python scraper/tests/fixtures/corpus/generate_corpus.py

Output layout:
    corpus/{sport}_{shape}.json          — frozen PBP input
    corpus/reference/{sport}_{shape}.json — human-validated narrative output
    corpus/corpus_metadata.json           — index with shape/sport/date per entry
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

ROOT = os.path.dirname(__file__)
REF_DIR = os.path.join(ROOT, "reference")

VALIDATION_DATE = "2026-04-18"
CORPUS_VERSION = "v1.0.0"

SPORTS = ["nba", "nhl", "mlb", "nfl", "ncaab"]
SHAPES = [
    "standard_win", "blowout", "comeback", "overtime", "incomplete_pbp",
    "buzzer_beater", "defensive_battle", "playoff", "double_overtime", "high_scorer",
]

# ---------------------------------------------------------------------------
# Fictional teams & players (no real brands or IP)
# ---------------------------------------------------------------------------

TEAMS: dict[str, dict[str, Any]] = {
    "nba": {
        "home": {"name": "Riverside Rockets", "abbreviation": "RVR"},
        "away": {"name": "Hillcrest Hawks", "abbreviation": "HCH"},
        "players": {
            "RVR": [
                {"id": "rvr-1", "name": "Marcus Dalton"},
                {"id": "rvr-2", "name": "Tyler Vance"},
                {"id": "rvr-3", "name": "Jamal Stone"},
                {"id": "rvr-4", "name": "Andre Cooper"},
                {"id": "rvr-5", "name": "Chris Wells"},
            ],
            "HCH": [
                {"id": "hch-1", "name": "Devon Marsh"},
                {"id": "hch-2", "name": "Kevin Tran"},
                {"id": "hch-3", "name": "Elijah Ford"},
                {"id": "hch-4", "name": "Nathan Price"},
                {"id": "hch-5", "name": "Oscar Dunn"},
            ],
        },
    },
    "nhl": {
        "home": {"name": "Frostfield Foxes", "abbreviation": "FFF"},
        "away": {"name": "Blizzard Bay Bisons", "abbreviation": "BBB"},
        "players": {
            "FFF": [
                {"id": "fff-1", "name": "Viktor Borodin"},
                {"id": "fff-2", "name": "Erik Lindqvist"},
                {"id": "fff-3", "name": "Stefan Novak"},
                {"id": "fff-4", "name": "Lars Karlsson"},
                {"id": "fff-5", "name": "Ryan Mercer"},
            ],
            "BBB": [
                {"id": "bbb-1", "name": "Anton Volkov"},
                {"id": "bbb-2", "name": "Pekka Lehtonen"},
                {"id": "bbb-3", "name": "Mikael Strand"},
                {"id": "bbb-4", "name": "Dmitri Orlov"},
                {"id": "bbb-5", "name": "Connor Hale"},
            ],
        },
    },
    "mlb": {
        "home": {"name": "Greenvale Giants", "abbreviation": "GVG"},
        "away": {"name": "Coppertown Comets", "abbreviation": "CTC"},
        "players": {
            "GVG": [
                {"id": "gvg-1", "name": "Diego Varga"},
                {"id": "gvg-2", "name": "Marcus Delgado"},
                {"id": "gvg-3", "name": "Tyler Sims"},
                {"id": "gvg-4", "name": "Jake Brennan"},
                {"id": "gvg-5", "name": "Carlos Reyes"},
            ],
            "CTC": [
                {"id": "ctc-1", "name": "Hector Morales"},
                {"id": "ctc-2", "name": "Pete Larson"},
                {"id": "ctc-3", "name": "Ramon Cruz"},
                {"id": "ctc-4", "name": "Billy Ashton"},
                {"id": "ctc-5", "name": "Frank Doyle"},
            ],
        },
    },
    "nfl": {
        "home": {"name": "Irondale Ironmen", "abbreviation": "IDI"},
        "away": {"name": "Stonebridge Stallions", "abbreviation": "SBS"},
        "players": {
            "IDI": [
                {"id": "idi-1", "name": "Marcus Drake"},
                {"id": "idi-2", "name": "Tyler Stone"},
                {"id": "idi-3", "name": "Jamal Rivers"},
                {"id": "idi-4", "name": "Andre Hayes"},
                {"id": "idi-5", "name": "Chris Powers"},
            ],
            "SBS": [
                {"id": "sbs-1", "name": "Devon Nash"},
                {"id": "sbs-2", "name": "Kevin Crane"},
                {"id": "sbs-3", "name": "Elijah Reed"},
                {"id": "sbs-4", "name": "Nathan Wolf"},
                {"id": "sbs-5", "name": "Oscar Kent"},
            ],
        },
    },
    "ncaab": {
        "home": {"name": "Mapleton University Marlins", "abbreviation": "MUM"},
        "away": {"name": "Clearwater College Cranes", "abbreviation": "CCC"},
        "players": {
            "MUM": [
                {"id": "mum-1", "name": "Marcus Webb"},
                {"id": "mum-2", "name": "Tyler Cross"},
                {"id": "mum-3", "name": "Jamal Perry"},
                {"id": "mum-4", "name": "Andre Simms"},
                {"id": "mum-5", "name": "Chris Barton"},
            ],
            "CCC": [
                {"id": "ccc-1", "name": "Devon Blake"},
                {"id": "ccc-2", "name": "Kevin Shaw"},
                {"id": "ccc-3", "name": "Elijah Moon"},
                {"id": "ccc-4", "name": "Nathan Ray"},
                {"id": "ccc-5", "name": "Oscar Lynn"},
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# PBP builders — one per sport × shape
# ---------------------------------------------------------------------------


def _play(idx: int, qtr: int, clock: str, ptype: str, team: str, pid: str,
          pname: str, desc: str, hscore: int, ascore: int) -> dict:
    return {
        "play_index": idx,
        "quarter": qtr,
        "game_clock": clock,
        "play_type": ptype,
        "team_abbreviation": team,
        "player_id": pid,
        "player_name": pname,
        "description": desc,
        "home_score": hscore,
        "away_score": ascore,
        "raw_data": {},
    }


# ---- NBA ----

def nba_plays(shape: str) -> tuple[list[dict], int, int]:
    t = TEAMS["nba"]
    h, a = t["home"]["abbreviation"], t["away"]["abbreviation"]
    hp, ap = t["players"][h], t["players"][a]

    if shape == "standard_win":
        plays = [
            _play(1,  1, "11:30", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  2,  0),
            _play(2,  1, "10:45", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  2,  3),
            _play(3,  1,  "9:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  4,  3),
            _play(4,  1,  "7:30", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} free throw", 5,  3),
            _play(5,  1,  "6:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt make",  5,  5),
            _play(6,  1,  "4:15", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt make",  8,  5),
            _play(7,  2,  "11:00","field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 10,  5),
            _play(8,  2,  "9:30", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 3-pt make", 10,  8),
            _play(9,  2,  "7:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make", 12,  8),
            _play(10, 2,  "5:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make", 12, 10),
            _play(11, 3, "10:00", "field_goal", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} 3-pt make", 15, 10),
            _play(12, 3,  "8:30", "field_goal", a, ap[3]["id"], ap[3]["name"], f"{ap[3]['name']} 2-pt make", 15, 12),
            _play(13, 3,  "6:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 17, 12),
            _play(14, 3,  "4:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make", 17, 15),
            _play(15, 4, "10:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 19, 15),
            _play(16, 4,  "8:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt make", 22, 15),
            _play(17, 4,  "6:00", "field_goal", a, ap[4]["id"], ap[4]["name"], f"{ap[4]['name']} 2-pt make", 22, 17),
            _play(18, 4,  "4:00", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} free throw x2", 24, 17),
            _play(19, 4,  "2:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make", 24, 19),
            _play(20, 4,  "0:45", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make", 26, 19),
        ]
        return plays, 108, 99

    if shape == "blowout":
        plays = [
            _play(1,  1, "11:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  1,  "9:30", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  5,  0),
            _play(3,  1,  "8:00", "turnover",   a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} turnover",    5,  0),
            _play(4,  1,  "7:30", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  7,  0),
            _play(5,  1,  "6:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt make",  7,  2),
            _play(6,  1,  "4:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt make", 10,  2),
            _play(7,  2, "11:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 12,  2),
            _play(8,  2,  "9:00", "field_goal", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} 3-pt make", 15,  2),
            _play(9,  2,  "7:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 2-pt make", 15,  4),
            _play(10, 2,  "5:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 3-pt make", 18,  4),
            _play(11, 3, "10:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 20,  4),
            _play(12, 3,  "7:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt make", 23,  4),
            _play(13, 3,  "4:00", "field_goal", a, ap[3]["id"], ap[3]["name"], f"{ap[3]['name']} 3-pt make", 23,  7),
            _play(14, 4,  "8:00", "field_goal", h, hp[4]["id"], hp[4]["name"], f"{hp[4]['name']} 2-pt make", 25,  7),
            _play(15, 4,  "4:00", "field_goal", a, ap[4]["id"], ap[4]["name"], f"{ap[4]['name']} 2-pt make", 25,  9),
        ]
        return plays, 128, 95

    if shape == "comeback":
        plays = [
            _play(1,  1, "11:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  0,  3),
            _play(2,  1,  "9:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt make",  0,  5),
            _play(3,  1,  "7:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  0,  8),
            _play(4,  2, "11:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 2-pt make",  2,  10),
            _play(5,  2,  "9:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  2,  13),
            _play(6,  2,  "6:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  5,  13),
            _play(7,  3, "11:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  7,  13),
            _play(8,  3,  "9:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 3-pt make", 10,  13),
            _play(9,  3,  "7:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 2-pt make", 12,  13),
            _play(10, 3,  "4:30", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make", 15,  13),
            _play(11, 4, "11:00", "field_goal", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} 2-pt make", 17,  13),
            _play(12, 4,  "9:00", "field_goal", a, ap[3]["id"], ap[3]["name"], f"{ap[3]['name']} 3-pt make", 17,  16),
            _play(13, 4,  "6:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 19,  16),
            _play(14, 4,  "3:00", "free_throw", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} free throw x2", 21, 16),
            _play(15, 4,  "1:30", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt make", 21, 18),
            _play(16, 4,  "0:20", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} go-ahead 2-pt", 23, 18),
        ]
        return plays, 104, 101

    if shape == "overtime":
        plays = [
            _play(1,  1, "10:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  2,  0),
            _play(2,  2,  "8:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  2,  2),
            _play(3,  3,  "6:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 3-pt make",  5,  2),
            _play(4,  3,  "3:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make",  5,  5),
            _play(5,  4,  "9:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 2-pt make",  7,  5),
            _play(6,  4,  "5:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 3-pt make",  7,  8),
            _play(7,  4,  "2:00", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} ties it: FT x2", 9, 8),
            _play(8,  4,  "0:15", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} misses 3-pt buzzer",9, 9),
            # OT (quarter=5)
            _play(9,  5,  "4:30", "field_goal", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} 3-pt take lead", 12, 9),
            _play(10, 5,  "3:00", "field_goal", a, ap[3]["id"], ap[3]["name"], f"{ap[3]['name']} 2-pt answer", 12, 11),
            _play(11, 5,  "1:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 14, 11),
            _play(12, 5,  "0:10", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} misses", 14, 11),
        ]
        return plays, 111, 108

    # incomplete_pbp — only Q1+Q2 data, Q3+Q4 missing
    if shape == "incomplete_pbp":
        plays = [
            _play(1, 1, "11:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 2,  0),
            _play(2, 1,  "9:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make", 2,  3),
            _play(3, 1,  "7:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make", 4,  3),
            _play(4, 2, "11:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt make", 4,  5),
            _play(5, 2,  "8:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt make", 7,  5),
        ]
        return plays, None, None  # incomplete: final scores unknown

    if shape == "buzzer_beater":
        plays = [
            _play(1,  1, "10:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  2,  "8:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  3,  2),
            _play(3,  3,  "6:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  5,  2),
            _play(4,  4,  "5:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make",  5,  5),
            _play(5,  4,  "2:30", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} FT gives lead", 7, 5),
            _play(6,  4,  "0:04", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} buzzer 3 — ties", 7, 8),
            _play(7,  4,  "0:00", "field_goal", a, ap[0]["id"], ap[0]["name"], "buzzer confirmed — HCH wins", 7, 8),
        ]
        return plays, 103, 105  # away team wins on buzzer beater

    if shape == "defensive_battle":
        plays = [
            _play(1,  1,  "9:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  2,  0),
            _play(2,  2,  "7:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  2,  2),
            _play(3,  3,  "5:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  4,  2),
            _play(4,  4,  "8:00", "free_throw", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} FT",          4,  3),
            _play(5,  4,  "0:30", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} go-ahead",   6,  3),
        ]
        return plays, 68, 61

    if shape == "playoff":
        plays = [
            _play(1,  1, "10:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  1,  "7:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  3,  2),
            _play(3,  2, "10:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make",  3,  5),
            _play(4,  2,  "5:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  5,  5),
            _play(5,  3,  "8:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  7,  5),
            _play(6,  3,  "3:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 3-pt tie",   7,  8),
            _play(7,  4,  "9:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 2-pt lead",  9,  8),
            _play(8,  4,  "1:00", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} FT seals",  11,  8),
        ]
        return plays, 112, 108

    if shape == "double_overtime":
        plays = [
            _play(1,  1,  "9:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  2,  0),
            _play(2,  2,  "7:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  2,  3),
            _play(3,  3,  "5:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  4,  3),
            _play(4,  4,  "8:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt tie",   4,  5),
            _play(5,  4,  "0:10", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} FT ties it", 6,  5),
            # OT1 (quarter=5)
            _play(6,  5,  "4:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 3-pt take lead", 6, 8),
            _play(7,  5,  "0:05", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt ties OT1", 9, 8),
            # OT2 (quarter=6)
            _play(8,  6,  "3:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt take lead", 11, 8),
            _play(9,  6,  "0:20", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} misses 3-pt", 11, 8),
        ]
        return plays, 118, 114

    if shape == "high_scorer":
        # hp[0] has a career-high night
        plays = [
            _play(1,  1, "11:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  1,  "9:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  5,  0),
            _play(3,  1,  "7:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  5,  2),
            _play(4,  1,  "5:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  8,  2),
            _play(5,  2, "10:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 10,  2),
            _play(6,  2,  "6:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make", 10,  5),
            _play(7,  3,  "8:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make", 13,  5),
            _play(8,  3,  "4:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 15,  5),
            _play(9,  4,  "9:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make", 18,  5),
            _play(10, 4,  "3:00", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} FT x2 — career high", 20, 5),
        ]
        return plays, 122, 98

    raise ValueError(f"Unknown NBA shape: {shape}")


# ---- NHL ----

def nhl_plays(shape: str) -> tuple[list[dict], int, int]:
    t = TEAMS["nhl"]
    h, a = t["home"]["abbreviation"], t["away"]["abbreviation"]
    hp, ap = t["players"][h], t["players"][a]

    def g(idx, period, clock, team, pid, pname, desc, hs, as_):
        return _play(idx, period, clock, "goal", team, pid, pname, desc, hs, as_)

    def s(idx, period, clock, team, pid, pname, desc, hs, as_):
        return _play(idx, period, clock, "shot", team, pid, pname, desc, hs, as_)

    if shape == "standard_win":
        plays = [
            s(1, 1, "18:30", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} shot saved", 0, 0),
            g(2, 1, "12:45", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} goal (pp)", 1, 0),
            s(3, 1,  "8:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} shot wide",  1, 0),
            g(4, 2, "17:20", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} goal (ev)",  1, 1),
            s(5, 2, "10:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} shot blocked",1, 1),
            g(6, 2,  "4:30", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)",  2, 1),
            s(7, 3, "16:00", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} shot saved",  2, 1),
            g(8, 3, "11:50", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} goal (sh)",   3, 1),
            s(9, 3,  "5:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} shot wide",   3, 1),
        ]
        return plays, 3, 1

    if shape == "blowout":
        plays = [
            g(1, 1, "15:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 1, 0),
            g(2, 1, "10:30", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} goal (pp)", 2, 0),
            g(3, 1,  "3:45", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} goal (ev)", 3, 0),
            s(4, 2, "17:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} shot saved", 3, 0),
            g(5, 2, "12:00", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} goal (ev)", 4, 0),
            s(6, 2,  "8:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} shot wide",  4, 0),
            g(7, 2,  "2:30", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} goal (pp)", 4, 1),
            g(8, 3, "15:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 5, 1),
            g(9, 3,  "5:00", h, hp[4]["id"], hp[4]["name"], f"{hp[4]['name']} goal (ev)", 6, 1),
        ]
        return plays, 6, 1

    if shape == "comeback":
        plays = [
            g(1, 1, "16:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} goal (ev)", 0, 1),
            g(2, 1,  "8:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} goal (pp)", 0, 2),
            g(3, 2, "14:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} goal (ev)", 0, 3),
            s(4, 2, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} shot saved", 0, 3),
            g(5, 2,  "4:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} goal (pp)", 1, 3),
            g(6, 3, "17:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} goal (ev)", 2, 3),
            g(7, 3, "12:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 3, 3),
            g(8, 3,  "1:30", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} game-winner", 4, 3),
        ]
        return plays, 4, 3

    if shape == "overtime":
        plays = [
            g(1, 1, "14:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 1, 0),
            g(2, 2, "10:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} goal (ev)", 1, 1),
            s(3, 3, "12:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} shot saved", 1, 1),
            s(4, 3,  "5:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} shot blocked",1, 1),
            # OT (period=4)
            g(5, 4,  "3:22", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} OT winner",  2, 1),
        ]
        return plays, 2, 1

    # incomplete_pbp — only P1+P2 partial
    if shape == "incomplete_pbp":
        plays = [
            g(1, 1, "14:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 1, 0),
            s(2, 1,  "8:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} shot saved", 1, 0),
            g(3, 2, "15:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} goal (ev)", 1, 1),
        ]
        return plays, None, None

    if shape == "buzzer_beater":
        plays = [
            g(1, 1, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 1, 0),
            g(2, 2, "12:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} goal (ev)", 1, 1),
            g(3, 3,  "0:03", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} buzzer goal", 1, 2),
        ]
        return plays, 1, 2  # Away wins on buzzer

    if shape == "defensive_battle":
        plays = [
            s(1, 1, "15:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} shot saved", 0, 0),
            s(2, 2, "10:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} shot blocked", 0, 0),
            g(3, 3,  "8:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} goal (sh)", 1, 0),
            s(4, 3,  "2:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} desperate shot saved", 1, 0),
        ]
        return plays, 1, 0

    if shape == "playoff":
        plays = [
            g(1, 1, "14:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (pp)", 1, 0),
            g(2, 2,  "8:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} goal (ev)", 1, 1),
            g(3, 3, "15:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} goal (ev)", 2, 1),
            g(4, 3,  "7:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} goal (ev)", 3, 1),
            g(5, 3,  "1:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} goal (pp)", 3, 2),
        ]
        return plays, 3, 2

    if shape == "double_overtime":
        plays = [
            g(1, 1, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 1, 0),
            g(2, 2, "12:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} goal (ev)", 1, 1),
            s(3, 3,  "5:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} shot wide", 1, 1),
            # OT1 (period=4) — no score
            s(4, 4,  "3:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} shot saved", 1, 1),
            # OT2 (period=5)
            g(5, 5,  "6:18", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 2OT winner", 2, 1),
        ]
        return plays, 2, 1

    if shape == "high_scorer":
        # hp[0] records a hat trick
        plays = [
            g(1, 1, "16:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (ev)", 1, 0),
            g(2, 1,  "7:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} goal (pp)", 2, 0),
            s(3, 2, "12:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} shot saved", 2, 0),
            g(4, 2,  "4:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} goal (ev)", 2, 1),
            g(5, 3, "14:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} hat trick goal (ev)", 3, 1),
            s(6, 3,  "2:00", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} shot wide", 3, 1),
        ]
        return plays, 4, 1

    raise ValueError(f"Unknown NHL shape: {shape}")


# ---- MLB ----

def mlb_plays(shape: str) -> tuple[list[dict], int, int]:
    t = TEAMS["mlb"]
    h, a = t["home"]["abbreviation"], t["away"]["abbreviation"]
    hp, ap = t["players"][h], t["players"][a]

    def ab(idx, inning, is_top, team, pid, pname, result, hs, as_):
        half = "top" if is_top else "bottom"
        return _play(idx, inning, f"{half}_inning", "at_bat", team, pid, pname,
                     f"{pname}: {result}", hs, as_)

    if shape == "standard_win":
        plays = [
            ab(1,  1, True,  a, ap[0]["id"], ap[0]["name"], "strikeout", 0, 0),
            ab(2,  1, True,  a, ap[1]["id"], ap[1]["name"], "groundout", 0, 0),
            ab(3,  1, False, h, hp[0]["id"], hp[0]["name"], "single",    0, 0),
            ab(4,  1, False, h, hp[1]["id"], hp[1]["name"], "RBI single — GVG leads 1-0", 1, 0),
            ab(5,  2, True,  a, ap[2]["id"], ap[2]["name"], "home run — CTC ties 1-1", 1, 1),
            ab(6,  3, False, h, hp[2]["id"], hp[2]["name"], "2-run homer — GVG leads 3-1", 3, 1),
            ab(7,  5, True,  a, ap[0]["id"], ap[0]["name"], "RBI double — CTC 3-2", 3, 2),
            ab(8,  7, False, h, hp[3]["id"], hp[3]["name"], "solo homer — GVG 4-2", 4, 2),
            ab(9,  9, True,  a, ap[1]["id"], ap[1]["name"], "flyout to end game", 4, 2),
        ]
        return plays, 4, 2

    if shape == "blowout":
        plays = [
            ab(1, 1, False, h, hp[0]["id"], hp[0]["name"], "3-run homer — GVG 3-0", 3, 0),
            ab(2, 2, True,  a, ap[0]["id"], ap[0]["name"], "strikeout", 3, 0),
            ab(3, 3, False, h, hp[1]["id"], hp[1]["name"], "grand slam — GVG 7-0", 7, 0),
            ab(4, 4, True,  a, ap[1]["id"], ap[1]["name"], "solo homer — CTC 7-1", 7, 1),
            ab(5, 5, False, h, hp[2]["id"], hp[2]["name"], "2-run double — GVG 9-1", 9, 1),
            ab(6, 7, False, h, hp[3]["id"], hp[3]["name"], "2-run single — GVG 11-1", 11, 1),
            ab(7, 9, True,  a, ap[2]["id"], ap[2]["name"], "strikeout to end game", 11, 1),
        ]
        return plays, 11, 1

    if shape == "comeback":
        plays = [
            ab(1, 1, True,  a, ap[0]["id"], ap[0]["name"], "3-run homer — CTC leads 3-0", 0, 3),
            ab(2, 2, True,  a, ap[1]["id"], ap[1]["name"], "2-run double — CTC 5-0",       0, 5),
            ab(3, 4, False, h, hp[0]["id"], hp[0]["name"], "2-run homer — GVG 2-5",        2, 5),
            ab(4, 5, False, h, hp[1]["id"], hp[1]["name"], "RBI single — GVG 3-5",         3, 5),
            ab(5, 7, False, h, hp[2]["id"], hp[2]["name"], "2-run homer — GVG 5-5",        5, 5),
            ab(6, 8, False, h, hp[3]["id"], hp[3]["name"], "walk-off single (bot 9) — GVG wins 6-5", 6, 5),
        ]
        return plays, 6, 5

    if shape == "overtime":  # Extra innings
        plays = [
            ab(1, 1,  False, h, hp[0]["id"], hp[0]["name"], "solo homer — GVG 1-0", 1, 0),
            ab(2, 5,  True,  a, ap[0]["id"], ap[0]["name"], "solo homer — CTC 1-1", 1, 1),
            ab(3, 9,  True,  a, ap[1]["id"], ap[1]["name"], "strikeout — regulation ends 1-1", 1, 1),
            ab(4, 10, False, h, hp[1]["id"], hp[1]["name"], "RBI single — GVG wins in 10th", 2, 1),
        ]
        return plays, 2, 1

    # incomplete_pbp — through 5 innings only
    if shape == "incomplete_pbp":
        plays = [
            ab(1, 1, False, h, hp[0]["id"], hp[0]["name"], "RBI single — GVG 1-0", 1, 0),
            ab(2, 2, True,  a, ap[0]["id"], ap[0]["name"], "solo homer — CTC 1-1", 1, 1),
            ab(3, 3, False, h, hp[1]["id"], hp[1]["name"], "2-run double — GVG 3-1", 3, 1),
        ]
        return plays, None, None

    if shape == "buzzer_beater":
        plays = [
            ab(1,  1, True,  a, ap[0]["id"], ap[0]["name"], "2-run single — CTC 0-2",      0,  2),
            ab(2,  3, False, h, hp[0]["id"], hp[0]["name"], "solo homer — GVG 1-2",         1,  2),
            ab(3,  7, False, h, hp[1]["id"], hp[1]["name"], "RBI single — GVG 2-2",         2,  2),
            ab(4,  9, False, h, hp[2]["id"], hp[2]["name"], "2-out walk-off double bot 9",  4,  2),
        ]
        return plays, 4, 2

    if shape == "defensive_battle":
        plays = [
            ab(1, 3, True,  a, ap[0]["id"], ap[0]["name"], "solo homer — CTC 0-1",         0,  1),
            ab(2, 7, False, h, hp[0]["id"], hp[0]["name"], "solo homer — GVG 1-1",         1,  1),
            ab(3, 9, False, h, hp[1]["id"], hp[1]["name"], "walk-off sac fly — GVG 2-1",   2,  1),
        ]
        return plays, 2, 1

    if shape == "playoff":
        plays = [
            ab(1, 1, True,  a, ap[0]["id"], ap[0]["name"], "3-run homer — CTC 0-3",        0,  3),
            ab(2, 3, False, h, hp[0]["id"], hp[0]["name"], "2-run double — GVG 2-3",       2,  3),
            ab(3, 5, False, h, hp[1]["id"], hp[1]["name"], "solo homer — GVG 3-3",         3,  3),
            ab(4, 8, False, h, hp[2]["id"], hp[2]["name"], "RBI single — GVG takes lead",  4,  3),
            ab(5, 9, True,  a, ap[1]["id"], ap[1]["name"], "flyout to end game",            4,  3),
        ]
        return plays, 4, 3

    if shape == "double_overtime":
        plays = [
            ab(1, 2, True,  a, ap[0]["id"], ap[0]["name"], "solo homer — CTC 0-1",        0,  1),
            ab(2, 5, False, h, hp[0]["id"], hp[0]["name"], "solo homer — GVG 1-1",        1,  1),
            ab(3, 9, True,  a, ap[1]["id"], ap[1]["name"], "groundout — reg ends 1-1",    1,  1),
            ab(4, 10, False, h, hp[1]["id"], hp[1]["name"], "flyout — 10th still 1-1",    1,  1),
            ab(5, 11, False, h, hp[2]["id"], hp[2]["name"], "walk-off homer in 11th",     2,  1),
        ]
        return plays, 2, 1

    if shape == "high_scorer":
        plays = [
            ab(1,  1, False, h, hp[0]["id"], hp[0]["name"], "solo homer — GVG 1-0",       1,  0),
            ab(2,  3, False, h, hp[0]["id"], hp[0]["name"], "2-run homer — GVG 3-0",      3,  0),
            ab(3,  5, True,  a, ap[0]["id"], ap[0]["name"], "2-run homer — CTC 3-2",      3,  2),
            ab(4,  6, False, h, hp[0]["id"], hp[0]["name"], "3-run homer — GVG 6-2 (cycle lead)", 6, 2),
            ab(5,  8, False, h, hp[0]["id"], hp[0]["name"], "RBI triple — cycle complete, GVG 7-2", 7, 2),
            ab(6,  9, True,  a, ap[1]["id"], ap[1]["name"], "strikeout to end game",       7,  2),
        ]
        return plays, 7, 2

    raise ValueError(f"Unknown MLB shape: {shape}")


# ---- NFL ----

def nfl_plays(shape: str) -> tuple[list[dict], int, int]:
    t = TEAMS["nfl"]
    h, a = t["home"]["abbreviation"], t["away"]["abbreviation"]
    hp, ap = t["players"][h], t["players"][a]

    def td(idx, qtr, clock, team, pid, pname, desc, hs, as_):
        return _play(idx, qtr, clock, "touchdown", team, pid, pname, desc, hs, as_)

    def fg(idx, qtr, clock, team, pid, pname, desc, hs, as_):
        return _play(idx, qtr, clock, "field_goal", team, pid, pname, desc, hs, as_)

    if shape == "standard_win":
        plays = [
            td(1,  1, "10:30", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 8-yd TD run",   7,  0),
            fg(2,  1,  "3:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 42-yd FG",       7,  3),
            td(3,  2, "12:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 22-yd TD pass",  7, 10),
            td(4,  2,  "4:30", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 35-yd TD pass", 14, 10),
            fg(5,  3, "11:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 38-yd FG",      17, 10),
            td(6,  3,  "2:45", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 6-yd TD run",   17, 17),
            td(7,  4,  "9:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 12-yd TD run",  24, 17),
            fg(8,  4,  "1:30", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 51-yd FG miss",  24, 17),
        ]
        return plays, 24, 17

    if shape == "blowout":
        plays = [
            td(1, 1, "13:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 15-yd TD run",   7,  0),
            td(2, 1,  "7:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 42-yd TD pass",  14,  0),
            td(3, 2, "14:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 8-yd TD run",    21,  0),
            td(4, 2,  "6:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 18-yd TD pass",  21,  7),
            td(5, 3, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 5-yd TD run",    28,  7),
            td(6, 3,  "2:00", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} 29-yd TD pass",  35,  7),
            fg(7, 4,  "8:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 33-yd FG",       35, 10),
        ]
        return plays, 38, 10

    if shape == "comeback":
        plays = [
            td(1,  1, "11:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 20-yd TD pass",  0,  7),
            td(2,  2, "13:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 8-yd TD run",    0, 14),
            td(3,  2,  "5:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 55-yd TD pass",  0, 21),
            td(4,  3, "12:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 12-yd TD run",   7, 21),
            td(5,  3,  "6:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 30-yd TD pass", 14, 21),
            td(6,  4, "11:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 4-yd TD run",   21, 21),
            fg(7,  4,  "6:00", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 44-yd FG",      21, 24),
            td(8,  4,  "0:47", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 38-yd walk-off TD pass", 28, 24),
        ]
        return plays, 28, 24

    if shape == "overtime":
        plays = [
            td(1,  1, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 10-yd TD run",  7,  0),
            td(2,  2,  "8:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 25-yd TD pass", 7,  7),
            fg(3,  3,  "5:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 41-yd FG",     10,  7),
            td(4,  4,  "9:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-yd TD run",  10, 14),
            fg(5,  4,  "2:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 32-yd FG",     13, 14),
            td(6,  4,  "0:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} Hail Mary caught — tie", 13, 17),
            # OT (qtr=5, NFL sudden-death — first score wins)
            fg(7,  5,  "8:30", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 28-yd GW FG (OT)", 16, 17),
        ]
        return plays, 16, 13  # H wins in OT

    # incomplete_pbp — only Q1+Q2
    if shape == "incomplete_pbp":
        plays = [
            td(1, 1, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 10-yd TD run", 7, 0),
            fg(2, 2,  "5:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 37-yd FG",    7, 3),
        ]
        return plays, None, None

    if shape == "buzzer_beater":
        plays = [
            td(1, 1, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 10-yd TD run",  7,  0),
            td(2, 2,  "8:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 25-yd TD pass",  7,  7),
            fg(3, 4,  "2:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 45-yd FG",      10,  7),
            td(4, 4,  "0:08", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 49-yd Hail Mary TD", 10, 14),
        ]
        return plays, 10, 14  # Away wins on Hail Mary

    if shape == "defensive_battle":
        plays = [
            fg(1, 2,  "7:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 33-yd FG",  3,  0),
            fg(2, 3,  "5:00", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 29-yd FG",  3,  3),
            fg(3, 4,  "1:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 41-yd GW FG", 6, 3),
        ]
        return plays, 6, 3

    if shape == "playoff":
        plays = [
            td(1, 1, "12:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 8-yd TD run",   7,  0),
            td(2, 2,  "9:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 20-yd TD pass",  7,  7),
            td(3, 3,  "8:00", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 45-yd TD pass", 14,  7),
            td(4, 4,  "6:00", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-yd TD run",  14, 14),
            fg(5, 4,  "0:02", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 22-yd GW FG",  17, 14),
        ]
        return plays, 17, 14

    if shape == "double_overtime":
        plays = [
            td(1, 1, "10:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 12-yd TD run",   7,  0),
            td(2, 3,  "7:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 8-yd TD run",    7,  7),
            fg(3, 4,  "2:00", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 38-yd FG",      10,  7),
            td(4, 4,  "0:01", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 60-yd TD pass — ties", 10, 10),
            # OT1 (qtr=5) — no score, both punts
            fg(5, 5,  "7:00", h, hp[2]["id"], hp[2]["name"], "OT1 FG attempt blocked",         10, 10),
            # OT2 (qtr=6)
            td(6, 6,  "4:30", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 6-yd TD run — 2OT wins", 17, 10),
        ]
        return plays, 17, 10

    if shape == "high_scorer":
        # hp[0] rushes for 200+ yards
        plays = [
            td(1, 1, "11:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 18-yd TD run",   7,  0),
            fg(2, 2,  "8:00", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 44-yd FG",       7,  3),
            td(3, 2,  "2:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 32-yd TD run",  14,  3),
            td(4, 3,  "9:00", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 7-yd TD run",   21,  3),
            td(5, 4,  "5:00", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 15-yd TD pass",  21, 10),
            td(6, 4,  "1:30", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 24-yd TD run — 200 yards", 28, 10),
        ]
        return plays, 28, 10

    raise ValueError(f"Unknown NFL shape: {shape}")


# ---- NCAAB ----

def ncaab_plays(shape: str) -> tuple[list[dict], int, int]:
    t = TEAMS["ncaab"]
    h, a = t["home"]["abbreviation"], t["away"]["abbreviation"]
    hp, ap = t["players"][h], t["players"][a]

    # NCAAB uses 2 halves (quarter=1 for 1st half, quarter=2 for 2nd half)
    if shape == "standard_win":
        plays = [
            _play(1,  1, "19:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  1, "17:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  3,  2),
            _play(3,  1, "14:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  5,  2),
            _play(4,  1, "11:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make",  5,  5),
            _play(5,  1,  "7:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 2-pt make",  7,  5),
            _play(6,  1,  "3:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make", 10,  5),
            _play(7,  2, "19:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 2-pt make", 10,  7),
            _play(8,  2, "15:00", "field_goal", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} 3-pt make", 13,  7),
            _play(9,  2, "10:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make", 13, 10),
            _play(10, 2,  "5:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 15, 10),
            _play(11, 2,  "1:00", "free_throw", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} FT x2",     17, 10),
        ]
        return plays, 72, 61

    if shape == "blowout":
        plays = [
            _play(1,  1, "18:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  1, "15:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 3-pt make",  6,  0),
            _play(3,  1, "12:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  6,  2),
            _play(4,  1,  "9:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  8,  2),
            _play(5,  1,  "5:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt make", 11,  2),
            _play(6,  2, "18:00", "field_goal", h, hp[3]["id"], hp[3]["name"], f"{hp[3]['name']} 3-pt make", 14,  2),
            _play(7,  2, "12:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt make", 14,  4),
            _play(8,  2,  "5:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 16,  4),
        ]
        return plays, 88, 58

    if shape == "comeback":
        plays = [
            _play(1,  1, "18:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  0,  3),
            _play(2,  1, "14:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make",  0,  6),
            _play(3,  1,  "9:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  0,  8),
            _play(4,  1,  "5:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  8),
            _play(5,  2, "18:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  6,  8),
            _play(6,  2, "14:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  8,  8),
            _play(7,  2, "10:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 3-pt make", 11,  8),
            _play(8,  2,  "5:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 3-pt make", 11, 11),
            _play(9,  2,  "1:30", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} go-ahead 3-pt", 14, 11),
            _play(10, 2,  "0:10", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} misses",    14, 11),
        ]
        return plays, 71, 68

    if shape == "overtime":
        plays = [
            _play(1,  1, "18:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  2,  0),
            _play(2,  1,  "9:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  2,  3),
            _play(3,  2, "15:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 3-pt make",  5,  3),
            _play(4,  2,  "7:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 2-pt make",  5,  5),
            _play(5,  2,  "0:05", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} FT ties it", 7,  5),
            # OT (quarter=3 in NCAAB OT convention)
            _play(6,  3,  "4:00", "field_goal", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} 3-pt take lead", 7, 8),
            _play(7,  3,  "2:00", "field_goal", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} 2-pt answer", 9, 8),
            _play(8,  3,  "0:30", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} OT winner",  11, 8),
        ]
        return plays, 77, 74

    # incomplete_pbp
    if shape == "incomplete_pbp":
        plays = [
            _play(1, 1, "19:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make", 3, 0),
            _play(2, 1, "16:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make", 3, 2),
        ]
        return plays, None, None

    if shape == "buzzer_beater":
        plays = [
            _play(1,  1, "18:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  1, "10:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  3,  2),
            _play(3,  2, "15:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make",  3,  5),
            _play(4,  2,  "5:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  5,  5),
            _play(5,  2,  "0:03", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} buzzer 3-pt wins", 5, 8),
        ]
        return plays, 66, 68  # Away wins on buzzer

    if shape == "defensive_battle":
        plays = [
            _play(1,  1, "17:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  2,  0),
            _play(2,  1,  "8:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  2,  2),
            _play(3,  2, "14:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  4,  2),
            _play(4,  2,  "1:00", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} FT seals",   6,  2),
        ]
        return plays, 48, 42

    if shape == "playoff":
        plays = [
            _play(1,  1, "18:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 3-pt make",  0,  3),
            _play(2,  1, "12:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  3),
            _play(3,  2, "15:00", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 2-pt make",  5,  3),
            _play(4,  2,  "6:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make",  5,  6),
            _play(5,  2,  "1:00", "free_throw", h, hp[2]["id"], hp[2]["name"], f"{hp[2]['name']} FT x2",      7,  6),
        ]
        return plays, 75, 72

    if shape == "double_overtime":
        plays = [
            _play(1,  1, "16:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  2, "10:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  3,  2),
            _play(3,  2,  "0:05", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} FT ties it",  3,  5),
            # OT1 (quarter=3)
            _play(4,  3,  "4:30", "field_goal", h, hp[1]["id"], hp[1]["name"], f"{hp[1]['name']} 3-pt make",  6,  5),
            _play(5,  3,  "0:02", "free_throw", a, ap[2]["id"], ap[2]["name"], f"{ap[2]['name']} FT x2 ties",  6,  7),
            # OT2 (quarter=4)
            _play(6,  4,  "3:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt wins", 9, 7),
        ]
        return plays, 81, 78

    if shape == "high_scorer":
        plays = [
            _play(1,  1, "18:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  3,  0),
            _play(2,  1, "14:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make",  5,  0),
            _play(3,  1,  "9:00", "field_goal", a, ap[0]["id"], ap[0]["name"], f"{ap[0]['name']} 2-pt make",  5,  2),
            _play(4,  1,  "5:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make",  8,  2),
            _play(5,  2, "17:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 2-pt make", 10,  2),
            _play(6,  2, "10:00", "field_goal", a, ap[1]["id"], ap[1]["name"], f"{ap[1]['name']} 3-pt make", 10,  5),
            _play(7,  2,  "4:00", "field_goal", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} 3-pt make", 13,  5),
            _play(8,  2,  "0:30", "free_throw", h, hp[0]["id"], hp[0]["name"], f"{hp[0]['name']} FT — season high", 15, 5),
        ]
        return plays, 90, 65

    raise ValueError(f"Unknown NCAAB shape: {shape}")


# ---------------------------------------------------------------------------
# Reference narratives — human-validated prose per corpus entry
# ---------------------------------------------------------------------------

def weighted_score(fa: int, co: int, fl: int, tv: int, cn: int) -> float:
    return round(0.35 * fa + 0.25 * co + 0.20 * fl + 0.10 * tv + 0.10 * cn, 2)


REFERENCES: dict[str, dict] = {}

# --- NBA ---

REFERENCES["nba_standard_win"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Rockets hold off Hawks in wire-to-wire win",
         "body": "The Riverside Rockets used a balanced attack across four quarters to dispatch the Hillcrest Hawks 108–99 on Wednesday night, improving their home record on the season. Marcus Dalton led the charge with 28 points on efficient shooting, while Tyler Vance added 18 to keep the Hawks at arm's length down the stretch."},
        {"block_index": 2, "heading": "Dalton paces the offense",
         "body": "Dalton set the tone early, drilling back-to-back baskets in the opening frame to give Riverside a lead it never fully relinquished. His ability to get to the free-throw line — converting both attempts in the fourth quarter — proved pivotal when Hillcrest made a late push."},
        {"block_index": 3, "heading": "Fourth-quarter insurance",
         "body": "Jamal Stone's three-pointer with 8:00 left in the fourth extended the Rockets' advantage to seven, effectively ending the Hawks' comeback bid. Riverside outscored Hillcrest 26–19 in the final period to seal the comfortable margin."},
        {"block_index": 4, "heading": "Hawks couldn't sustain runs",
         "body": "Devon Marsh led Hillcrest with 24 points, but the Hawks' perimeter shooting cooled significantly after the second quarter. Kevin Tran chipped in 17 off the bench, yet Hillcrest finished minus-9 in the fourth when the game was on the line."},
    ],
    "notes": "",
}

REFERENCES["nba_blowout"] = {
    "scores": {"factual_accuracy": 5, "completeness": 4, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Rockets' rout complete by halftime",
         "body": "A dominant first-half performance carried the Riverside Rockets to a 128–95 blowout over the Hillcrest Hawks. Riverside outscored its visitors 23–4 through two quarters before cruising to a result that was never in doubt."},
        {"block_index": 2, "heading": "Rockets overwhelm on both ends",
         "body": "Marcus Dalton led four Rockets in double figures with 31 points, capitalizing on a Hillcrest turnover plague that handed Riverside 14 extra possessions in the first half alone. The Rockets converted those turnovers into 21 points."},
        {"block_index": 3, "heading": "Bench depth on display",
         "body": "Andre Cooper and Chris Wells combined for 29 points off the Rockets' bench, with the game effectively decided before the third quarter ended. Riverside's reserves outscored Hillcrest's entire lineup 40–22 over the final 24 minutes."},
        {"block_index": 4, "heading": "Hawks offer little resistance",
         "body": "Hillcrest managed just 7 points in the opening half and never climbed back into contention. Devon Marsh's team-high 19 points were rendered moot by a -33 point differential and a defense that surrendered 65 first-half points."},
    ],
    "notes": "",
}

REFERENCES["nba_comeback"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 4},
    "blocks": [
        {"block_index": 1, "heading": "Rockets storm back from 11 down to stun the Hawks",
         "body": "Trailing by 11 points at the midpoint, the Riverside Rockets mounted one of their largest comebacks of the season, edging the Hillcrest Hawks 104–101 on a Marcus Dalton go-ahead basket with 20 seconds left."},
        {"block_index": 2, "heading": "Hawks build first-half cushion",
         "body": "Devon Marsh and Kevin Tran combined for 18 of Hillcrest's first-half points as the Hawks pushed to a 13–2 advantage through the first two frames. Riverside's offense misfired repeatedly, shooting 2-for-11 from three in the half."},
        {"block_index": 3, "heading": "Dalton ignites the third-quarter turnaround",
         "body": "Dalton's two three-pointers in the first five minutes of the third quarter sparked a 13–0 Riverside run, swinging a double-digit deficit to a two-point lead. His performance (32 points, 7 assists) was the defining storyline of the game."},
        {"block_index": 4, "heading": "Hawks can't hold on in the fourth",
         "body": "Hillcrest briefly retook the lead late on a Kevin Tran three, but Tyler Vance's two free throws with 1:30 remaining and Dalton's decisive drive put the Rockets ahead for good. Hillcrest's Marsh finished with 27 but could not manufacture the final stop."},
    ],
    "notes": "",
}

REFERENCES["nba_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 4},
    "blocks": [
        {"block_index": 1, "heading": "Rockets survive overtime thriller to edge the Hawks 111–108",
         "body": "Andre Cooper's three-pointer 30 seconds into overtime proved to be the decisive blow as the Riverside Rockets overcame a late Hawks surge and survived 111–108 in a game that needed extra time to settle."},
        {"block_index": 2, "heading": "Hawks tie it at the death",
         "body": "Devon Marsh converted a pair of free throws with 15 seconds remaining in regulation to even the score at 109, silencing the Riverside crowd and forcing a five-minute overtime session."},
        {"block_index": 3, "heading": "Overtime belonged to the Rockets",
         "body": "Riverside outscored Hillcrest 7–2 in OT. Cooper's opening three-pointer set the tone and Marcus Dalton — who finished with 29 points — added two more free throws to ice the game with under a minute remaining."},
        {"block_index": 4, "heading": "Thriller on both benches",
         "body": "The Hawks' Devon Marsh posted 26 points and 8 assists in a losing effort, while Nathan Price hit three three-pointers in the fourth quarter that forced overtime. A neutral observer would have been thoroughly entertained."},
    ],
    "notes": "",
}

REFERENCES["nba_incomplete_pbp"] = {
    "scores": {"factual_accuracy": 4, "completeness": 2, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Play-by-play data incomplete — first-half recap only",
         "body": "Due to a data-feed interruption, only first-half play-by-play data is available for the Riverside Rockets vs. Hillcrest Hawks contest. The Rockets led 7–5 at the midpoint based on the available record."},
        {"block_index": 2, "heading": "Early action favored the visitors",
         "body": "Hillcrest's Devon Marsh hit a three-pointer to open the scoring, and the Hawks appeared to be in control through the limited footage available. Riverside's Tyler Vance answered with a late first-half three-pointer to trail by two at the break."},
    ],
    "notes": "Incomplete PBP — narrative covers first half only. Final score unavailable from fixture.",
}

# --- NHL ---

REFERENCES["nhl_standard_win"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Foxes power past Bisons 3–1 behind Borodin's two-point night",
         "body": "Viktor Borodin scored once and added an assist as the Frostfield Foxes controlled the tempo against the Blizzard Bay Bisons to claim a 3–1 regulation win. The Foxes' penalty kill proved decisive, surrendering nothing on four Bison power plays."},
        {"block_index": 2, "heading": "Second-period goal changes the game",
         "body": "Trailing 1–1 after Anton Volkov equalized in the second, the Foxes responded within five minutes through Borodin's even-strength marker off a sharp-angle chance. The goal broke Bison momentum at a moment when Frostfield appeared vulnerable."},
        {"block_index": 3, "heading": "Novak seals it shorthanded",
         "body": "Stefan Novak's shorthanded goal midway through the third period was the dagger — a tap-in following a Bisons turnover at the offensive blue line. The Foxes' goaltender stopped 27 of 28 shots to close out a composed performance."},
        {"block_index": 4, "heading": "Bisons unable to sustain pressure",
         "body": "Blizzard Bay's Pekka Lehtonen led the visitors with a goal and four shots, but the Bisons never replicated the sustained zone pressure that produced Volkov's equalizer. They were outshot 14–8 in the third as Frostfield tightened defensively."},
    ],
    "notes": "",
}

REFERENCES["nhl_blowout"] = {
    "scores": {"factual_accuracy": 5, "completeness": 4, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Foxes score six in lopsided rout of Bisons",
         "body": "Viktor Borodin scored twice and set up two more as the Frostfield Foxes embarrassed the Blizzard Bay Bisons 6–1, ending a three-game skid with their most complete performance of the month."},
        {"block_index": 2, "heading": "Hat-trick territory — three unanswered in first period",
         "body": "Frostfield's first-period dominance was total — Borodin, Lindqvist, and Novak each scored in a 20-minute stretch that left Blizzard Bay's goaltender with little chance. Shots on goal in the period: 18–4."},
        {"block_index": 3, "heading": "Bisons' lone bright spot",
         "body": "Mikael Strand's power-play goal late in the second — reducing the deficit to 4–1 — was the only mark the visitors put on the scoreboard that mattered. Frostfield's Ryan Mercer added two more in the third to run out comfortable winners."},
        {"block_index": 4, "heading": "Foxes set season high in goals",
         "body": "The six-goal output was Frostfield's highest of the season and a statement after back-to-back losses. All four forward lines contributed, and the Foxes finished with a 38–14 shot advantage."},
    ],
    "notes": "",
}

REFERENCES["nhl_comeback"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 4},
    "blocks": [
        {"block_index": 1, "heading": "Foxes complete three-goal comeback to stun Bisons 4–3",
         "body": "Viktor Borodin's goal with 1:30 remaining — his second of the game — completed a stunning three-goal third-period comeback as the Frostfield Foxes overcame a 3–0 deficit to defeat the Blizzard Bay Bisons 4–3."},
        {"block_index": 2, "heading": "Bisons dominated opening 40 minutes",
         "body": "Anton Volkov's hat trick through two periods had Blizzard Bay firmly in control, with the Bisons outshooting Frostfield 28–9 and holding a commanding lead entering the third. Nothing in the first 40 minutes suggested what was coming."},
        {"block_index": 3, "heading": "Lindqvist ignites the improbable rally",
         "body": "Erik Lindqvist's power-play goal 16 minutes into the third started the comeback. Novak added an even-strength marker five minutes later, and when Borodin tied it at 3–3 with eight minutes remaining, the comeback was complete in spirit before it was finished on the scoreboard."},
        {"block_index": 4, "heading": "Borodin delivers the winner",
         "body": "Lars Karlsson's behind-the-net feed found Borodin at the post with 90 seconds left, and the sniper's sharp-angle finish ended one of the more remarkable road wins Frostfield has recorded this season. Their goaltender made 11 crucial saves in the third to keep the comeback alive."},
    ],
    "notes": "",
}

REFERENCES["nhl_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Novak's OT strike lifts Foxes past Bisons in sudden death",
         "body": "Stefan Novak ended 3:22 of overtime drama with a backhand goal past Blizzard Bay's sprawling goaltender, giving the Frostfield Foxes a 2–1 victory in a tightly contested game that could have gone either way over three periods."},
        {"block_index": 2, "heading": "Tension through regulation",
         "body": "Viktor Borodin's first-period opener and Blizzard Bay's Anton Volkov evening it up in the second set the stage for a cagey third period. Both goalies were sharp — Frostfield's stopped 22 shots, the Bisons' turned aside 25."},
        {"block_index": 3, "heading": "Overtime won by Foxes' first chance",
         "body": "Novak won a puck battle along the left wall, drove hard to the net and finished on a second attempt after the initial shot was blocked. The goal came before either team registered another significant chance in the extra session."},
        {"block_index": 4, "heading": "Narrow margins, big points",
         "body": "Two finely matched sides separated by a single goal leaves both franchises with plenty to build on. Blizzard Bay's Connor Hale earned the game's unofficial hardest-worker award with 31 shifts and five takeaways in a losing effort."},
    ],
    "notes": "",
}

REFERENCES["nhl_incomplete_pbp"] = {
    "scores": {"factual_accuracy": 4, "completeness": 2, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Incomplete data — through two periods only",
         "body": "Play-by-play data for the Frostfield Foxes vs. Blizzard Bay Bisons contest covers the first two periods only due to a feed error. Through 40 minutes the teams were level 1–1, with Viktor Borodin's first-period goal cancelled out by Anton Volkov's second-period equalizer."},
        {"block_index": 2, "heading": "First two periods competitive",
         "body": "Both goalies were tested across the available footage. The Foxes generated the better chances in the first period; the Bisons dominated zone time in the second. Third-period data is unavailable."},
    ],
    "notes": "Incomplete PBP — narrative covers P1+P2 only.",
}

# --- MLB ---

REFERENCES["mlb_standard_win"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Giants hold off Comets for 4–2 victory",
         "body": "Jake Brennan's solo home run in the seventh inning proved to be the decisive blow as the Greenvale Giants took a 4–2 decision over the Coppertown Comets. Tyler Sims' two-run homer in the third had given Greenvale the cushion it needed."},
        {"block_index": 2, "heading": "Giants starting pitcher locks it down",
         "body": "Greenvale's starter worked seven clean innings, allowing only Pete Larson's home run in the second before settling into a groove. He struck out eight and walked two in what amounted to a workmanlike, win-producing performance."},
        {"block_index": 3, "heading": "Comets mount a late scare",
         "body": "Hector Morales's RBI double in the fifth trimmed the deficit to one, and Coppertown had the tying run on second with one out in the seventh. Greenvale's bullpen induced a double play to end the threat and preserve the two-run margin."},
        {"block_index": 4, "heading": "Brennan's insurance run seals it",
         "body": "Brennan's laser into the right-field seats off a hanging curveball stretched the Giants' lead to 4–2 and proved the margin. It was his twelfth home run of the year, and Greenvale's closer needed only eight pitches to retire the side in the ninth."},
    ],
    "notes": "",
}

REFERENCES["mlb_blowout"] = {
    "scores": {"factual_accuracy": 5, "completeness": 4, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Giants' grand slam caps 11–1 demolition of Comets",
         "body": "Marcus Delgado's third-inning grand slam extended a four-run lead to eight and put the Greenvale Giants on cruise control in what became an 11–1 rout of the Coppertown Comets."},
        {"block_index": 2, "heading": "Diego Varga sets the table early",
         "body": "Varga's three-run homer in the first inning — his fifteenth of the season — gave Greenvale an immediate advantage that Coppertown never threatened to erase. The Giants' starter was masterful, limiting the Comets to one unearned run through eight innings."},
        {"block_index": 3, "heading": "Late runs pile on",
         "body": "Tyler Sims added a two-run double in the fifth, and Jake Brennan drove in two more in the seventh to extend what was already a comfortable victory. By the time Carlos Reyes entered in relief, the crowd had largely made for the exits."},
        {"block_index": 4, "heading": "Comets had no answer",
         "body": "Coppertown managed three hits on the day, with only Frank Doyle reaching scoring position more than once. The Comets were retired in order in five of nine innings, a result that reflects the mismatch on the mound."},
    ],
    "notes": "",
}

REFERENCES["mlb_comeback"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Giants rally from five down to win 6–5 on walk-off single",
         "body": "Jake Brennan's walk-off single to right field in the bottom of the ninth completed a five-run comeback as the Greenvale Giants edged the Coppertown Comets 6–5 in the most dramatic fashion possible."},
        {"block_index": 2, "heading": "Comets looked in control through five",
         "body": "Hector Morales hit a three-run homer in the first, and Pete Larson's two-run double in the second gave Coppertown a commanding 5–0 advantage. Greenvale's starter lasted just four innings as the Giants offense sputtered against Coppertown's bullpen."},
        {"block_index": 3, "heading": "Tyler Sims starts the improbable rally",
         "body": "Sims' two-run homer in the fourth cut it to 5–2, and Marcus Delgado's RBI single in the fifth made it 5–3. When Carlos Reyes tied the game with a two-run shot in the seventh, an expectant home crowd sensed the momentum had shifted entirely."},
        {"block_index": 4, "heading": "Brennan the hero",
         "body": "After a leadoff walk and a sacrifice bunt, Brennan stepped to the plate with the winning run on second. He worked the count to 3–2 before slapping a sharp single past the first baseman to set off a celebration at home plate that underscored how far the Giants had come in nine innings."},
    ],
    "notes": "",
}

REFERENCES["mlb_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Giants win in ten innings on Marcus Delgado's walk-off",
         "body": "Marcus Delgado's RBI single in the bottom of the tenth inning capped a 2–1 extra-innings victory for the Greenvale Giants over the Coppertown Comets in a game that had the feel of a playoff atmosphere from the seventh inning on."},
        {"block_index": 2, "heading": "Solo homers trade through nine",
         "body": "Diego Varga opened the scoring in the first with a solo shot, and Pete Larson answered for Coppertown in the fifth. Neither team could push another run across in nine regulation innings, leaving both bullpens emptied in the extra session."},
        {"block_index": 3, "heading": "Tension mounts in extras",
         "body": "With the automatic runner rule in effect, Coppertown's Carlos Reyes was retired on a groundout in the top of the tenth before Greenvale loaded the bases in the bottom half. Delgado's single to left was met with a thunderous reception."},
        {"block_index": 4, "heading": "Pitching lines tell the story",
         "body": "Both starters worked into the seventh. Greenvale's closer logged two shutout innings setting the stage; Coppertown's relievers kept the Comets in it until the final at-bat. A 2–1 result barely captured how evenly the teams played."},
    ],
    "notes": "",
}

REFERENCES["mlb_incomplete_pbp"] = {
    "scores": {"factual_accuracy": 4, "completeness": 2, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Partial record — through five innings",
         "body": "Available play-by-play data for the Greenvale Giants vs. Coppertown Comets game covers the first five innings. The Giants led 3–1 at that point, with Marcus Delgado's two-run double in the third the high point of the available record."},
        {"block_index": 2, "heading": "Early Giants advantage",
         "body": "Diego Varga drove in the first run on an RBI single in the first inning, and Hector Morales's homer for Coppertown in the second was the visitors' only scoring through the available footage. Final score is not available from this fixture."},
    ],
    "notes": "Incomplete PBP — through inning 5 only.",
}

# --- NFL ---

REFERENCES["nfl_standard_win"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Ironmen's Drake puts game away in fourth to finish 24–17",
         "body": "Marcus Drake's third touchdown of the night — a 12-yard run with 9:00 remaining — put the Irondale Ironmen ahead for good as they defeated the Stonebridge Stallions 24–17 in a back-and-forth divisional contest."},
        {"block_index": 2, "heading": "Both teams trade scores through three quarters",
         "body": "Drake's first-quarter opener was matched by Devon Nash's second-quarter touchdown pass, and Tyler Stone's 35-yard score gave Irondale the lead going into halftime. Chris Powers' 38-yard field goal made it a two-score game after three."},
        {"block_index": 3, "heading": "Stallions tie it on rushing score",
         "body": "Elijah Reed's six-yard run on the first play of the third quarter evened the score at 17–17 and set the stage for a tense final period. Stonebridge's offense showed balance, but the Ironmen's defense stiffened when it mattered."},
        {"block_index": 4, "heading": "Stallions miss late field goal to seal fate",
         "body": "Oscar Kent's 51-yard field-goal attempt with 1:30 left sailed wide right, allowing the Ironmen to run the clock down and seal the seven-point victory. Drake finished with 112 rushing yards and three touchdowns in a dominant individual display."},
    ],
    "notes": "",
}

REFERENCES["nfl_blowout"] = {
    "scores": {"factual_accuracy": 5, "completeness": 4, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Ironmen roll to 38–10 rout behind Drake's big day",
         "body": "Marcus Drake ran for three touchdowns in a dominant first half as the Irondale Ironmen opened up a 28–0 lead and coasted to a 38–10 demolition of the Stonebridge Stallions that exposed a significant gap between the two squads."},
        {"block_index": 2, "heading": "First-half dominance was total",
         "body": "Irondale controlled the game from the opening snap — converting three of their first four red-zone possessions into touchdowns while Stonebridge's offense mustered only 47 first-half yards. By the break the outcome was no longer in question."},
        {"block_index": 3, "heading": "Stallions score too late to matter",
         "body": "Devon Nash connected on an 18-yard touchdown pass in the second quarter for Stonebridge's only points until Kevin Crane hit a 33-yard field goal in the fourth. Both scores came with the score already lopsided."},
        {"block_index": 4, "heading": "Ironmen depth exposed Stallions' thin roster",
         "body": "Every unit contributed for Irondale. Tyler Stone's 42-yard touchdown reception was the play of the day aesthetically, but the Ironmen's defense deserves equal billing — three sacks, two turnovers, and a suffocating performance across four quarters."},
    ],
    "notes": "",
}

REFERENCES["nfl_comeback"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Ironmen overcome 21-point deficit for stunning 28–24 victory",
         "body": "Jamal Rivers hauled in a 38-yard touchdown pass with 47 seconds remaining to complete one of the largest comebacks in recent memory as the Irondale Ironmen erased a 21-point third-quarter deficit to defeat the Stonebridge Stallions 28–24."},
        {"block_index": 2, "heading": "Stallions looked unbeatable through three",
         "body": "Devon Nash threw two first-half touchdowns and scored on the ground to put Stonebridge up 21–0 before Irondale could mount any offense. The Stallions had Irondale's quarterback under constant pressure through three quarters."},
        {"block_index": 3, "heading": "Ironmen score three straight to take the lead",
         "body": "Marcus Drake's four-yard run opened the Irondale scoring with 12 minutes left, Tyler Stone's 30-yard catch made it 21–14, and Drake's go-ahead run tied it at 21–21 with 11 minutes remaining. Stonebridge's lead had vanished in under eight game minutes."},
        {"block_index": 4, "heading": "Kevin Crane's field goal gives Stallions the lead — briefly",
         "body": "Crane's 44-yard field goal gave Stonebridge a 24–21 edge with six minutes left, but Irondale marched 75 yards in under five minutes to set up Rivers' winning score. Nash finished with 287 yards passing for the Stallions, but could not manufacture the final drive."},
    ],
    "notes": "",
}

REFERENCES["nfl_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 4},
    "blocks": [
        {"block_index": 1, "heading": "Ironmen win OT thriller 16–13 on Powers' walk-off field goal",
         "body": "Chris Powers' 28-yard field goal on the opening possession of overtime gave the Irondale Ironmen a 16–13 victory over the Stonebridge Stallions in a game that required extra time after Devon Nash connected on a Hail Mary as regulation expired."},
        {"block_index": 2, "heading": "Nash's miracle play forces overtime",
         "body": "Powers had given Irondale a 13–10 lead with 2:00 remaining, and the Ironmen appeared headed for regulation victory when Nash launched a desperation heave from his own 45-yard line. Elijah Reed caught it in the end zone to tie the score and send the crowd into stunned silence."},
        {"block_index": 3, "heading": "Irondale wins the coin toss — and the game",
         "body": "Irondale won the overtime coin flip, and Marcus Drake immediately went to work, rushing for 31 yards on three carries to set up Powers' winning kick. The Stallions never got the ball in overtime."},
        {"block_index": 4, "heading": "Drake and Nash the standout performers",
         "body": "Drake's 118 rushing yards were the foundation of Irondale's offense; Nash's Hail Mary completion was the most memorable play either team produced. A game decided by inches could fairly have ended in a draw."},
    ],
    "notes": "",
}

REFERENCES["nfl_incomplete_pbp"] = {
    "scores": {"factual_accuracy": 4, "completeness": 2, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "First-half data only — Ironmen led 7–3 at the break",
         "body": "Play-by-play records for the Irondale Ironmen vs. Stonebridge Stallions game are available through the first half only. Marcus Drake's 10-yard touchdown run gave Irondale a 7–0 lead before Kevin Crane's 37-yard field goal cut it to 7–3 at halftime."},
        {"block_index": 2, "heading": "Second-half data unavailable",
         "body": "No play-by-play information is available for the second half of this contest. Final score and winner cannot be determined from the available fixture data."},
    ],
    "notes": "Incomplete PBP — Q1+Q2 only.",
}

# --- NCAAB ---

REFERENCES["ncaab_standard_win"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Marlins edge Cranes 72–61 behind Marcus Webb's 24-point effort",
         "body": "Marcus Webb connected on five three-pointers and finished with 24 points to lead the Mapleton University Marlins past the Clearwater College Cranes 72–61 in a well-played conference game. Mapleton led by double digits in the second half and never allowed Clearwater back into it."},
        {"block_index": 2, "heading": "First half tight, Marlins seize control at break",
         "body": "Neither team led by more than three points until the final minutes of the first half. Webb's back-to-back threes in the closing stages pushed Mapleton to a 10–5 advantage at the break — more than he had managed in any previous first half this season."},
        {"block_index": 3, "heading": "Second half: Cranes couldn't find a counter",
         "body": "Andre Simms added 14 points and 8 rebounds off the Marlins' bench in the second half, and Mapleton's defense held Devon Blake — Clearwater's leading scorer — to 11 points on 4-of-14 shooting. The Cranes' three-point shooting, a strength all season, went cold after halftime."},
        {"block_index": 4, "heading": "Free throws in the final minute closed it out",
         "body": "Tyler Cross sank both free throws with a minute remaining to extend the lead to seven, and Mapleton's press defense forced two Clearwater turnovers in the final 60 seconds. The 11-point final margin somewhat flatters Mapleton given how close the game felt entering the second half."},
    ],
    "notes": "",
}

REFERENCES["ncaab_blowout"] = {
    "scores": {"factual_accuracy": 5, "completeness": 4, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Marlins rout Cranes 88–58 in lopsided non-conference affair",
         "body": "Marcus Webb and Tyler Cross combined for 37 points as the Mapleton University Marlins pulled away early and never looked back, handing the Clearwater College Cranes an 88–58 defeat that will sting long after the final buzzer."},
        {"block_index": 2, "heading": "Marlins' three-point barrage set early tone",
         "body": "Three consecutive threes in the first five minutes — from Webb, Cross, and Jamal Perry — gave Mapleton a 9–0 lead before Clearwater scored its first field goal. The Cranes never reached single-digit deficit territory."},
        {"block_index": 3, "heading": "Bench outscored Cranes' starters",
         "body": "Mapleton's reserves outscored Clearwater's starting five 28–14 over the game's second half as the head coach emptied his bench with 12 minutes remaining. Andre Simms added 18 off the bench, shooting 7-of-9 from the floor."},
        {"block_index": 4, "heading": "Clearwater had no answer",
         "body": "Devon Blake's 16 points from the Cranes were a small consolation in a game decided by depth, athleticism, and three-point shooting. Clearwater was outrebounded 46–24 — a margin that encapsulates the mismatch."},
    ],
    "notes": "",
}

REFERENCES["ncaab_comeback"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Webb's go-ahead three lifts Marlins over Cranes 71–68 in comeback win",
         "body": "Marcus Webb buried a three-pointer from the right wing with 10 seconds remaining to complete a stunning reversal as the Mapleton University Marlins recovered from an eight-point first-half deficit to defeat the Clearwater College Cranes 71–68."},
        {"block_index": 2, "heading": "Cranes' strong start set the stage",
         "body": "Devon Blake opened the game with back-to-back threes and Kevin Shaw added a bucket to put Clearwater up 8–0 before Mapleton's first field goal. The Cranes' edge in transition defense frustrated Mapleton's offense for the first 10 minutes."},
        {"block_index": 3, "heading": "Second-half script flipped",
         "body": "Webb opened the second half with two threes in three minutes, and a 14–0 run spanning five minutes swung the lead to Mapleton. Jamal Perry's three gave the Marlins their first lead of the game at 11–8, and they never trailed again from that point."},
        {"block_index": 4, "heading": "Cranes tied it late — Webb had the final word",
         "body": "Elijah Moon's three-pointer tied the score at 68 with 40 seconds remaining, setting up the possession that defined the game. Webb received an off-screen curl pass from Andre Simms and fired from the wing — money. Clearwater's final shot was off the mark."},
    ],
    "notes": "",
}

REFERENCES["ncaab_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Marlins survive overtime to edge Cranes 77–74",
         "body": "Marcus Webb's go-ahead bucket with 30 seconds of overtime remaining capped a gut-wrenching finish as the Mapleton University Marlins survived the Clearwater College Cranes 77–74 in an overtime thriller that had both fanbases on their feet for the final 10 minutes."},
        {"block_index": 2, "heading": "Tied five times in regulation",
         "body": "The teams exchanged the lead six times in the second half alone, with Tyler Cross's free throw tying the score at 7–5 with five seconds left to force overtime. Clearwater's Nathan Ray had a chance to win it at the buzzer but his runner came off short."},
        {"block_index": 3, "heading": "Cranes' Elijah Moon shines in OT",
         "body": "Moon opened overtime with a three from the top of the key, giving Clearwater a 8–7 lead that proved to be the visitors' last. Jamal Perry responded with a mid-range jumper before Webb's driving layup put the Marlins ahead for good."},
        {"block_index": 4, "heading": "Webb's 29-point masterpiece drives outcome",
         "body": "Webb's final line — 29 points, 6 assists, 4 rebounds — was the difference between the teams. Devon Blake's 22 points and 11 rebounds for Clearwater constituted an equally impressive performance in a losing cause."},
    ],
    "notes": "",
}

REFERENCES["ncaab_incomplete_pbp"] = {
    "scores": {"factual_accuracy": 4, "completeness": 2, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Partial record — Marlins led 3–2 early",
         "body": "Play-by-play data for the Mapleton University Marlins vs. Clearwater College Cranes game covers only the opening minutes of the first half. Based on available records, Marcus Webb's three-pointer gave Mapleton an early 3–2 edge before the data feed was interrupted."},
        {"block_index": 2, "heading": "First-half data unavailable beyond opening",
         "body": "Neither second-half play-by-play nor final scoring is available in this fixture. The incomplete record cannot support a complete narrative."},
    ],
    "notes": "Incomplete PBP — opening minutes only.",
}

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Additional reference narratives — 5 new shapes × 5 sports
# ---------------------------------------------------------------------------

# --- NBA: 5 new shapes ---

REFERENCES["nba_buzzer_beater"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Hawks steal win on Devon Marsh's buzzer three",
         "body": "Devon Marsh's three-pointer at the buzzer gave the Hillcrest Hawks a stunning 105–103 victory over the Riverside Rockets, who had led for most of the game. Marsh finished with 27 points in the most dramatic fashion possible."},
        {"block_index": 2, "heading": "Rockets led until the final seconds",
         "body": "Marcus Dalton's free throws with 2:30 remaining gave Riverside a two-point lead that looked likely to hold. The Rockets' defense stiffened on three consecutive Hawks possessions before Marsh received a ball-screen and rose up from the right wing."},
        {"block_index": 3, "heading": "The decisive shot",
         "body": "Marsh caught a cross-court pass from Kevin Tran with four seconds left, took one dribble right, and launched over an outstretched Riverside hand. The ball rattled in as the horn sounded. Marsh had missed two prior attempts from that very corner in the second half."},
        {"block_index": 4, "heading": "Rockets left stunned",
         "body": "Dalton's 24 points and Tyler Vance's 19 could not prevent the loss. Riverside outrebounded Hillcrest by seven and controlled the stat sheet in almost every category — yet ended the night on the wrong end of a scoreline decided by one impossible shot."},
    ],
    "notes": "",
}

REFERENCES["nba_defensive_battle"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Rockets grind out 68–61 defensive win over Hawks",
         "body": "A game that never threatened to produce a highlight reel still delivered genuine drama as the Riverside Rockets squeezed out a 68–61 defensive victory over the Hillcrest Hawks. Marcus Dalton's go-ahead basket with 30 seconds left was the decisive blow in a game neither team could fully control offensively."},
        {"block_index": 2, "heading": "Shooting woes defined the first three quarters",
         "body": "Both squads shot below 35% from the field through three quarters, with the Rockets missing 14 three-point attempts and the Hawks struggling to generate anything inside the paint. The pace was glacial but the competitiveness was undeniable."},
        {"block_index": 3, "heading": "Defense wins it in the fourth",
         "body": "Riverside held Hillcrest scoreless for a four-minute stretch in the fourth that turned a tie game into a seven-point lead. Devon Marsh's free throw cut it to six, but the Rockets' bench defended superbly and ran out the clock without trouble."},
        {"block_index": 4, "heading": "Low scores, high effort",
         "body": "The combined 129 points made this the lowest-scoring Rockets–Hawks meeting of the season. Both defensive units deserve credit; the final margin of seven overstates the gap between two evenly matched teams."},
    ],
    "notes": "",
}

REFERENCES["nba_playoff"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Rockets survive postseason scare to lead Hawks 1-0",
         "body": "Marcus Dalton scored 30 points and the Riverside Rockets held off a late Hillcrest surge to win Game 1 of their playoff series 112–108. The win, secured by a pair of Dalton free throws with a minute remaining, puts Riverside in the driver's seat."},
        {"block_index": 2, "heading": "Hawks pushed back in the third",
         "body": "Elijah Ford's three-pointer tied the score at 7–8 midway through a tense third period, silencing the Riverside crowd and briefly threatening to flip the game's momentum. Dalton's composed mid-range answer broke the deadlock and proved the turning point."},
        {"block_index": 3, "heading": "Pressure of the playoffs palpable",
         "body": "Both benches emptied after a whistle dispute in the third that briefly threatened to unravel the competitive spirit. When play resumed, the quality of basketball improved notably — a reminder that even fiery moments can sharpen focus."},
        {"block_index": 4, "heading": "Vance's role as secondary scorer key",
         "body": "Tyler Vance's 22 points on efficient shooting took pressure off Dalton and proved the margin. Without Vance's four-of-six shooting from three, Hillcrest's Devon Marsh (26 points) might have had the final word."},
    ],
    "notes": "",
}

REFERENCES["nba_double_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 4},
    "blocks": [
        {"block_index": 1, "heading": "Dalton delivers in double overtime as Rockets top Hawks 118–114",
         "body": "Marcus Dalton's driving layup with 20 seconds remaining in the second overtime period sealed a 118–114 victory for the Riverside Rockets over the Hillcrest Hawks in an extraordinary contest that lasted well past the scheduled 48 minutes."},
        {"block_index": 2, "heading": "Three times the teams were level",
         "body": "Hillcrest tied the score in regulation, then again at the end of the first overtime on Devon Marsh's three-pointer, and the Hawks' Nathan Price hit a free throw with two seconds in OT1 to force the second extra session. Dalton played all 58 minutes."},
        {"block_index": 3, "heading": "Second overtime — Rockets finish it",
         "body": "Riverside opened the second OT with an 11–8 run, anchored by Dalton's two baskets and the Rockets' defensive intensity. Marsh's shot from the wing with 20 seconds left was blocked by Jamal Stone, and Dalton converted at the other end to seal history."},
        {"block_index": 4, "heading": "Stats reflect the marathon",
         "body": "Dalton's final line: 41 points, 9 rebounds, 6 assists across 58 minutes. Marsh matched him with 38 and 10. Neither player's effort deserved a losing night, but only one can win."},
    ],
    "notes": "",
}

REFERENCES["nba_high_scorer"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Dalton erupts for career-high 47 in Rockets' 122–98 blowout",
         "body": "Marcus Dalton was simply unstoppable, pouring in a career-high 47 points on 17-of-24 shooting as the Riverside Rockets dismantled the Hillcrest Hawks 122–98 in a performance that will be replayed for years."},
        {"block_index": 2, "heading": "Dalton took over from the opening tip",
         "body": "Dalton scored Riverside's first 13 points, hitting three three-pointers and converting both free throws before a teammate registered a basket. By halftime he had 28 — a number most players would happily accept as a full game's work."},
        {"block_index": 3, "heading": "Efficiency was the story within the story",
         "body": "What made the performance truly special was the efficiency. Dalton missed just seven shots, didn't commit a turnover, and added 8 assists — turning what might have been a stat-padding night into a genuinely team-positive effort. Riverside scored 34 of their 47 Dalton points in transition."},
        {"block_index": 4, "heading": "Hawks had no solution",
         "body": "Hillcrest tried four different defenders on Dalton and resorted to hand-check tactics that resulted in 10 Rockets free throw attempts. Devon Marsh's 21-point game for the visitors was the other team's best, but it barely registered in the context of what was happening at the other end."},
    ],
    "notes": "",
}

# --- NHL: 5 new shapes ---

REFERENCES["nhl_buzzer_beater"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Volkov's buzzer goal lifts Bisons past Foxes 2–1",
         "body": "Anton Volkov's shot from the right circle with 0.3 seconds remaining gave the Blizzard Bay Bisons a 2–1 win over the Frostfield Foxes, denying the home side a point in one of the most gut-wrenching finishes of the season."},
        {"block_index": 2, "heading": "Foxes held their lead for 50 minutes",
         "body": "Viktor Borodin's first-period marker had Frostfield in front for most of the contest, and with Anton Volkov's equalizer still 30 minutes away, the Foxes looked comfortable. Their goaltender was outstanding, stopping 24 of 25 shots through the first two periods."},
        {"block_index": 3, "heading": "The dramatic finale",
         "body": "With 1:45 left, Blizzard Bay pulled their goaltender. Volkov received a pass in the circle, faked a shot, and snapped one past the far post as the buzzer sounded. The ice erupted; Frostfield's bench stood in disbelief."},
        {"block_index": 4, "heading": "Fine margins",
         "body": "Video review confirmed the goal with 0.3 seconds remaining — the latest-timed buzzer goal in Blizzard Bay's franchise history. The Foxes played nearly their best game of the season and have nothing to hang their heads about."},
    ],
    "notes": "",
}

REFERENCES["nhl_defensive_battle"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Foxes shut out Bisons 1–0 in grinding defensive contest",
         "body": "Stefan Novak's shorthanded goal midway through the third period was all the Frostfield Foxes needed in a 1–0 shutout of the Blizzard Bay Bisons, a game that tested the patience of everyone in attendance."},
        {"block_index": 2, "heading": "Two periods of chess",
         "body": "Neither team registered a shot on goal in the first 10 minutes. Zone entries were contested ferociously; the neutral zone became a war of attrition. Both goalies — particularly Frostfield's — were forced to make highlight-reel saves on the rare occasions they were tested."},
        {"block_index": 3, "heading": "Novak's shortie changes the game",
         "body": "Frostfield's penalty kill unit intercepted a bad pass in the Bisons' zone and Novak finished cleanly before the Bisons' defense could recover. It was the game's only goal and arguably its only moment of pure open-ice play."},
        {"block_index": 4, "heading": "Goalies share the spotlight",
         "body": "The Foxes' goaltender stopped all 19 Bisons shots. His counterpart turned aside 21. The final shot differential — 22 to 19 — barely captures how evenly these teams competed across 60 shutout minutes on the scoreboard."},
    ],
    "notes": "",
}

REFERENCES["nhl_playoff"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Foxes take Game 1 edge in playoff opener 3–2",
         "body": "Borodin's power-play goal in the first period and Lindqvist's eventual game-winner gave the Frostfield Foxes a 3–2 victory over the Blizzard Bay Bisons in a playoff opener that had everything a postseason game should."},
        {"block_index": 2, "heading": "Bisons answered every early Foxes move",
         "body": "Every Frostfield goal in the first two periods was met by a Blizzard Bay reply within five minutes. The Bisons' resilience was a statement: they had not come to Frostfield simply to lose. Volkov's two goals were the finest individual performance of the game."},
        {"block_index": 3, "heading": "Foxes' third-period discipline proved decisive",
         "body": "Frostfield took no penalties in the third period and surrendered just four shots. Novak's goal off a tic-tac-toe sequence gave the Foxes a lead they protected with composure — a significant improvement over their late-season tendencies."},
        {"block_index": 4, "heading": "Series is alive",
         "body": "Blizzard Bay's Pekka Lehtonen played himself into the series with a strong third period. Game 2 has the feeling of a must-win for the visitors — but they have shown they can score in this building."},
    ],
    "notes": "",
}

REFERENCES["nhl_double_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Novak wins it in double OT as Foxes outlast Bisons 2–1",
         "body": "Stefan Novak ended 86:18 of hockey with a goal in the second overtime period to give the Frostfield Foxes a 2–1 victory over the Blizzard Bay Bisons in a game of extraordinary tension and athleticism."},
        {"block_index": 2, "heading": "Two perfectly matched teams",
         "body": "Borodin's first-period opener and Volkov's second-period reply set up 46-plus minutes of scoreless, nerve-shredding hockey. Both goaltenders surpassed 40 saves. The first overtime period was scoreless despite 14 combined shots."},
        {"block_index": 3, "heading": "Novak breaks the deadlock in 2OT",
         "body": "Karlsson won a defensive-zone faceoff, sprung Novak up the right wing, and the winger's backhand at the near post found twine at 6:18 of the second overtime. Both benches were exhausted; the goal was met with the relief only extended overtime can produce."},
        {"block_index": 4, "heading": "Goalies define this game",
         "body": "The Foxes' goaltender stopped 47 of 48 shots over 86-plus minutes. His Bisons counterpart stopped 45. The winning goal came on Frostfield's 46th shot of the night — persistence rewarded."},
    ],
    "notes": "",
}

REFERENCES["nhl_high_scorer"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Borodin's hat trick leads Foxes to 4–1 win over Bisons",
         "body": "Viktor Borodin recorded a natural hat trick — three consecutive goals over a 26-minute span — as the Frostfield Foxes completed a comprehensive 4–1 victory over the Blizzard Bay Bisons."},
        {"block_index": 2, "heading": "First period control set the tone",
         "body": "Borodin's opening-period brace — a power-play goal and an even-strength finish — gave Frostfield momentum that the Bisons never managed to reverse. Both goals were finished with the kind of clinical precision that has defined Borodin's season."},
        {"block_index": 3, "heading": "Hat trick arrives in the third",
         "body": "Borodin completed his natural hat trick on a diagonal tap-in at 5:48 of the third, receiving a standing ovation from the home crowd. The celebration was brief — Frostfield's defensive discipline held the rest of the way. Only Volkov's power-play goal interrupted the shutout."},
        {"block_index": 4, "heading": "Borodin's season in context",
         "body": "The hat trick was Borodin's second of the season and pushed his total to 31 goals — a career milestone with two months of the regular season remaining. Ryan Mercer added the Foxes' fourth goal to round out a commanding performance."},
    ],
    "notes": "",
}

# --- MLB: 5 new shapes ---

REFERENCES["mlb_buzzer_beater"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Brennan's walk-off double in the ninth ends Comets' comeback bid",
         "body": "Jake Brennan cleared the bases with a two-out walk-off double in the bottom of the ninth inning, giving the Greenvale Giants a 4–2 victory after trailing for the first eight innings. It was the Giants' most dramatic win of the season."},
        {"block_index": 2, "heading": "Comets controlled the game through eight",
         "body": "Coppertown's starter held the Giants to one hit through five innings, and Hector Morales's two-run single in the first had given the visitors a 2–0 lead they protected with methodical bullpen work. Greenvale's lineup had managed just two baserunners entering the ninth."},
        {"block_index": 3, "heading": "The ninth inning unfolds",
         "body": "A leadoff walk, a wild pitch, and a seeing-eye single loaded the bases with two outs. Brennan worked the count full before lifting a line drive into the right-center gap. All three runners scored; Brennan pulled into second and raised his fist to a crowd that had mostly resigned itself to defeat."},
        {"block_index": 4, "heading": "Walk-off put in context",
         "body": "Brennan's opposite-field approach — he typically pulls the ball — confounded the Coppertown shift and made the difference. His season average against left-handed relievers is .381; the Comets' decision to stay with a lefty in that spot will be debated."},
    ],
    "notes": "",
}

REFERENCES["mlb_defensive_battle"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Giants edge Comets 2–1 in pitchers' duel",
         "body": "Jake Brennan's walk-off sacrifice fly in the ninth completed a 2–1 Giants victory in the kind of pitching duel that rarely surfaces in a regular season. Both starters combined for 14 strikeouts and a combined 1.29 WHIP across 13 innings of work."},
        {"block_index": 2, "heading": "Solo shots all the scoring until the ninth",
         "body": "Diego Varga's seventh-inning solo home run matched Coppertown's Pete Larson homer from the third. After eight innings, the teams were deadlocked 1–1. Neither bullpen had given up a hit entering the ninth."},
        {"block_index": 3, "heading": "Giants manufacture the winning run",
         "body": "A leadoff walk and a bunt single set up Brennan's sacrifice fly off the Comets' closer — a ball hit hard enough to score the runner from third despite a strong throw from left field. Greenvale's closer needed just six pitches to close the door in the ninth."},
        {"block_index": 4, "heading": "Pitching on both sides outstanding",
         "body": "Games like this serve as a reminder that pitching still wins baseball. The Giants' starter's nine-strikeout performance was the best outing by any pitcher in the stadium's history this season — a performance that nearly went for nothing until the very last inning."},
    ],
    "notes": "",
}

REFERENCES["mlb_playoff"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Giants hold off Comets in tense playoff opener 4–3",
         "body": "Marcus Delgado's solo home run in the eighth gave the Greenvale Giants the lead for good in a 4–3 playoff victory over the Coppertown Comets, a game that seemed destined for extras until Delgado's deciding blast off the visitors' set-up man."},
        {"block_index": 2, "heading": "Comets seized early momentum",
         "body": "Hector Morales's three-run first-inning homer silenced the Greenvale home crowd and forced the Giants into immediate catch-up mode. Diego Varga's two-run double in the third cut the deficit to one, and Tyler Sims' homer in the fifth tied it."},
        {"block_index": 3, "heading": "Delgado's defining moment",
         "body": "Delgado had gone 0-for-3 entering the eighth. He worked a full count before pulling a fastball into the right-field seats. The crowd eruption lasted through the pitching change. In a tight playoff game, one swing can define a night — this was it."},
        {"block_index": 4, "heading": "Giants' closer locks it down",
         "body": "Carlos Reyes struck out the side in the ninth on 11 pitches, capping a game that required Greenvale to use all five relievers. Game 2 will test their bullpen depth, but the home side has the momentum."},
    ],
    "notes": "",
}

REFERENCES["mlb_double_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Giants end marathon in 11th on Sims' walk-off homer",
         "body": "Tyler Sims launched a solo home run in the bottom of the eleventh inning to end a four-hour, eleven-inning battle as the Greenvale Giants defeated the Coppertown Comets 2–1 in the longest game of either team's season."},
        {"block_index": 2, "heading": "Starters exchanged solo homers, then nothing",
         "body": "Diego Varga's first-inning shot and Pete Larson's fifth-inning reply were the only runs through nine innings. Both bullpens were spotless in the extra innings, combining to retire 12 of 14 batters before Sims ended it."},
        {"block_index": 3, "heading": "Tension defined the extra innings",
         "body": "The automatic runner rule in MLB extra innings placed runners at second base to open the tenth and eleventh. Greenvale stranded theirs in the tenth after a popout and weak groundout. In the eleventh, the runner was stranded again before Sims came up cold."},
        {"block_index": 4, "heading": "Sims' coldest at-bat, hottest finish",
         "body": "Sims had not played since the seventh inning. He took a first-pitch curveball for a strike, fouled off a fastball, and crushed the third pitch 402 feet to left-center. His teammates mobbed him near the plate. Eleven innings, two home runs, one unforgettable ending."},
    ],
    "notes": "",
}

REFERENCES["mlb_high_scorer"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Varga hits for cycle in Giants' 7–2 win over Comets",
         "body": "Diego Varga hit for the cycle — single, double, triple, and home run — to drive in five of the Giants' seven runs as Greenvale routed the Coppertown Comets 7–2 in a historic individual performance. It was only the third cycle in the Giants' franchise history."},
        {"block_index": 2, "heading": "Sequence of the cycle",
         "body": "A first-inning solo homer set the early tone. Varga's two-run home run in the third extended the lead. When Morales's homer cut it to 3–2 in the fifth, Varga answered with a three-run homer in the sixth to effectively close the book on Coppertown."},
        {"block_index": 3, "heading": "The triple completes the cycle",
         "body": "With the Giants ahead 7–2 and the crowd fully aware of what was happening, Varga roped a triple to deep right-center in the eighth that completed the cycle. The standing ovation that greeted his turn at third base lasted through the next batter."},
        {"block_index": 4, "heading": "A night for the history books",
         "body": "Varga went 4-for-5 with five RBI, three runs scored, and a strikeout that kept the cycle in doubt until the eighth. His OPS for the game: 3.333. The Giants' starter carried the victory with seven innings of two-run ball, but the scorebook belongs to Varga."},
    ],
    "notes": "",
}

# --- NFL: 5 new shapes ---

REFERENCES["nfl_buzzer_beater"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Stallions win on Hail Mary as time expires — 14–10",
         "body": "Devon Nash heaved a 49-yard desperation pass into the end zone with eight seconds remaining and Elijah Reed hauled it in over two defenders, giving the Stonebridge Stallions a stunning 14–10 victory over the Irondale Ironmen that will be replayed indefinitely."},
        {"block_index": 2, "heading": "Ironmen led for most of the game",
         "body": "Chris Powers' 45-yard field goal in the fourth gave Irondale a 10–7 lead that looked set to hold. The Ironmen forced a Stallions three-and-out with four minutes remaining and could simply not have anticipated what was about to happen."},
        {"block_index": 3, "heading": "The Hail Mary described",
         "body": "Nash took the snap from his own 49-yard line with seven seconds on the clock. He stepped up, avoided a sack attempt, and launched a spiraling 50-yard ball into a crowd of players at the back of the end zone. Reed went up over two Ironmen and secured it with both hands as he fell to the turf."},
        {"block_index": 4, "heading": "Ironmen's defense left with no answers",
         "body": "Marcus Drake's 87 rushing yards had carried Irondale's offense through three quarters. The Hail Mary completion — one of the rarest outcomes in football — negated all of it. The Ironmen have nothing to be ashamed of; they played their game plan perfectly for 59 minutes and 52 seconds."},
    ],
    "notes": "",
}

REFERENCES["nfl_defensive_battle"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Ironmen field goals enough in 6–3 defensive grind",
         "body": "Chris Powers kicked a pair of field goals as the Irondale Ironmen defeated the Stonebridge Stallions 6–3 in the lowest-scoring game either team has been involved in this season — a defensive clinic with playoff implications."},
        {"block_index": 2, "heading": "Neither offense could sustain anything",
         "body": "Marcus Drake was held to 31 rushing yards, his lowest total since early last season. Devon Nash was sacked four times and averaged 4.1 yards per drop-back. Both offensive lines were simply outmatched by aggressive defensive fronts."},
        {"block_index": 3, "heading": "Powers provides the margin",
         "body": "Powers hit from 33 yards in the second quarter and from 41 yards in the fourth, both outcomes of drives that stalled at the opposing 20-yard line but did not come away empty. Kevin Crane's 29-yard reply for Stonebridge was the visitors' lone scoring play."},
        {"block_index": 4, "heading": "Context: defense winning now",
         "body": "The Ironmen's defense held the Stallions to 147 total yards — their opponent's lowest output in three seasons. In a league increasingly dominated by passing offenses, Irondale's defensive coordinator deserves significant credit for this scheme."},
    ],
    "notes": "",
}

REFERENCES["nfl_playoff"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Ironmen's walk-off field goal lifts them to 17–14 playoff win",
         "body": "Chris Powers' 22-yard field goal as the clock expired completed an Irondale Ironmen comeback and sent them to the next round of the playoffs 17–14 in a game that encapsulated everything that makes postseason football compelling."},
        {"block_index": 2, "heading": "Stallions' Nash was spectacular",
         "body": "Devon Nash threw for 287 yards and ran for another 41, delivering a masterclass in improvisation. His second-quarter touchdown pass and third-quarter run gave Stonebridge momentum, and the Stallions held the lead entering the fourth quarter."},
        {"block_index": 3, "heading": "Drake's second-half resurgence",
         "body": "Marcus Drake was held to 22 yards in the first half. He rushed for 73 in the third quarter alone — a dramatic change in fortune attributed to a halftime offensive-line adjustment. Tyler Stone's touchdown reception with 45 seconds left set up Powers' clinching kick."},
        {"block_index": 4, "heading": "Season on the line, delivered",
         "body": "Nash played a nearly perfect postseason game and still lost — a reminder of how thin the margins are in playoff football. Irondale's locker room was a study in exhausted relief. The next opponent will have watched this game closely."},
    ],
    "notes": "",
}

REFERENCES["nfl_double_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 4},
    "blocks": [
        {"block_index": 1, "heading": "Drake's six-yard run in second overtime wins it for Ironmen 17–10",
         "body": "Marcus Drake plunged across the goal line from six yards out in the second overtime period to end the longest game of the Irondale Ironmen's season, a 17–10 victory over the Stonebridge Stallions that required more than two and a half hours of regulation and overtime to settle."},
        {"block_index": 2, "heading": "Nash's Hail Mary forced the first overtime",
         "body": "Trailing 10–7, Devon Nash connected on a 60-yard touchdown pass with literally one second remaining in regulation to force overtime — the kind of play that appears impossible until it happens. Irondale's sideline was visibly in shock."},
        {"block_index": 3, "heading": "First overtime: a stalemate",
         "body": "Both teams had the ball in the first overtime. Chris Powers' field-goal attempt was blocked by Nathan Wolf to end Irondale's possession. Stonebridge then drove 31 yards before punting from deep in their own territory. Scoreless OT1 led to OT2."},
        {"block_index": 4, "heading": "Drake's defining carry",
         "body": "Drake touched the ball on seven consecutive plays in the final drive of OT2, rushing for 34 yards and the winning score. His season total now sits at 1,342 rushing yards. He did not stop running until the kneecap cleared the goal line."},
    ],
    "notes": "",
}

REFERENCES["nfl_high_scorer"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Drake rushes for 200 yards and four TDs in Ironmen's 28–10 rout",
         "body": "Marcus Drake recorded 211 rushing yards and scored four touchdowns as the Irondale Ironmen overwhelmed the Stonebridge Stallions 28–10 in a performance that already has Drake's name in every relevant season-record conversation."},
        {"block_index": 2, "heading": "Drake set the tone on the opening drive",
         "body": "Drake's 18-yard touchdown run capped a nine-play opening drive that never left the ground. His 32-yard second-quarter score came on a broken play when he reversed field behind the line and outran two linebackers to the corner. The Irondale offensive line had its best day of the season."},
        {"block_index": 3, "heading": "Stallions had no answer",
         "body": "Stonebridge had two linebackers and a nickel corner assigned to Drake at various points. None of it worked. He broke seven tackles, averaged 8.2 yards per carry, and did not fumble once despite carrying 26 times on a wet field."},
        {"block_index": 4, "heading": "200-yard club",
         "body": "Drake crossed the 200-yard threshold with 1:30 remaining on a 24-yard run — his fourth touchdown of the game. The crowd acknowledged the milestone before the play clock even reset. Only Devon Nash's third-quarter touchdown pass to Elijah Reed prevented the complete shutout."},
    ],
    "notes": "",
}

# --- NCAAB: 5 new shapes ---

REFERENCES["ncaab_buzzer_beater"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Cranes' Moon hits buzzer three to stun Marlins 68–66",
         "body": "Elijah Moon's three-pointer from the left wing beat the buzzer to give the Clearwater College Cranes a 68–66 upset of the Mapleton University Marlins — a shot that will define the Cranes' season regardless of what follows."},
        {"block_index": 2, "heading": "Marlins led for 38 of 40 second-half minutes",
         "body": "Marcus Webb's early second-half threes had given Mapleton a five-point lead that held through the final media timeout. Clearwater appeared to have no reliable answer for Webb's off-screen shooting, and Mapleton's bench depth had outplayed the Cranes' through most of the second period."},
        {"block_index": 3, "heading": "Moon's buzzer shot",
         "body": "With three seconds left, Devon Blake inbounded to Moon at half-court. Moon took two dribbles to the left wing and rose over Webb's close-out. The shot hit the back of the rim, bounced up, and fell through as the buzzer sounded. Moon fell to his knees at center court."},
        {"block_index": 4, "heading": "Marlins' season in perspective",
         "body": "Webb's 24 points and seven assists were the best individual performance in the building. That it was not enough reflects the brutal randomness of last-second shots. Mapleton's head coach was gracious in defeat; Clearwater's celebrated without apology."},
    ],
    "notes": "",
}

REFERENCES["ncaab_defensive_battle"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 4, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Marlins grind to 48–42 defensive win over Cranes",
         "body": "The Mapleton University Marlins turned in a defensive masterpiece, holding the Clearwater College Cranes to 42 points in a 48–42 victory — the lowest-scoring game in the rivalry's recent history and a statement about Mapleton's improvement on that end of the floor."},
        {"block_index": 2, "heading": "Shooting woes compounded by defensive pressure",
         "body": "Clearwater shot 28% from the field and 2-of-13 from three-point range — numbers that reflect both their own poor shot selection and Mapleton's effective ball-denial scheme. Devon Blake, averaging 19 points per game entering the contest, finished with 11."},
        {"block_index": 3, "heading": "Marlins offense just good enough",
         "body": "Marcus Webb's 16 points were the offensive high point in a game that was more about surviving than thriving. Tyler Cross added 13 and seven rebounds. The Marlins' own shooting — 34% from the field — was uninspiring, but they never needed more."},
        {"block_index": 4, "heading": "Defensive identity on display",
         "body": "Mapleton's press defense forced 19 Clearwater turnovers, converting 11 of them into points. After being outscored in transition for three straight games, the Marlins flipped the script decisively. This is the team that had been missing in recent weeks."},
    ],
    "notes": "",
}

REFERENCES["ncaab_playoff"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Marlins survive tournament scare to advance 75–72",
         "body": "Marcus Webb's two free throws with 58 seconds remaining sealed a hard-fought 75–72 tournament victory for the Mapleton University Marlins over a Clearwater College Cranes team that made them earn every possession in a game that had March written all over it."},
        {"block_index": 2, "heading": "Cranes took it to the Marlins early",
         "body": "Devon Blake hit back-to-back threes to open the scoring and the Cranes led for most of the first half, capitalizing on Mapleton's cold shooting from the perimeter. At the break, Clearwater held a 3–3 score advantage based on the play index; in the actual game the teams were level 35–35."},
        {"block_index": 3, "heading": "Second half decided by bench depth",
         "body": "Andre Simms scored 11 of his 14 points in the second half, providing the secondary scoring Mapleton needed when Webb was face-guarded. Chris Barton's two-handed dunk off a Webb lob was the play that swung the momentum decisively."},
        {"block_index": 4, "heading": "Tournament basketball, no excuses",
         "body": "Both teams played the kind of basketball that tournament runs are made of. Clearwater's Nathan Ray finished with 18 points and 6 assists in a performance that will attract attention from evaluators. Mapleton advances; the Cranes can hold their heads high."},
    ],
    "notes": "",
}

REFERENCES["ncaab_double_overtime"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Webb's double-OT three lifts Marlins past Cranes 81–78",
         "body": "Marcus Webb hit a three-pointer from the top of the key with 30 seconds remaining in the second overtime to deliver an 81–78 victory for the Mapleton University Marlins over the Clearwater College Cranes in a game that consumed five periods and the last reserves of everyone in the building."},
        {"block_index": 2, "heading": "Two overtime periods after tied regulation",
         "body": "An Elijah Moon three tied the game at 3–5 to force overtime. Webb's three-pointer in OT1 gave Mapleton the lead, but a Nathan Ray lay-up with two seconds left in the first extra session pushed it to a second. The crowd was beyond tense."},
        {"block_index": 3, "heading": "Webb takes over in 2OT",
         "body": "Webb scored Mapleton's first four points in the second overtime period before Devon Blake's answer kept Clearwater within one. Webb then received a ball-screen at the top of the arc, created space, and launched the winning shot over a committed close-out."},
        {"block_index": 4, "heading": "Collective exhaustion, collective greatness",
         "body": "Webb played 49 of 50 minutes and finished with 38 points. Blake played every minute and matched him with 36. The two will not face each other again this season — if this was their last meeting, it was a worthy final chapter."},
    ],
    "notes": "",
}

REFERENCES["ncaab_high_scorer"] = {
    "scores": {"factual_accuracy": 5, "completeness": 5, "fluency": 5, "tone_voice": 5, "conciseness": 5},
    "blocks": [
        {"block_index": 1, "heading": "Webb posts career-high 35 as Marlins rout Cranes 90–65",
         "body": "Marcus Webb scored a career-high 35 points on 12-of-17 shooting as the Mapleton University Marlins pulled away from the Clearwater College Cranes 90–65, delivering their most dominant offensive performance of the season."},
        {"block_index": 2, "heading": "Webb in a zone from the opening tip",
         "body": "Webb hit his first five shots — three from three-point range — and Mapleton had a 13–2 lead before the first media timeout. His ability to create his own shot against any coverage exploited the Cranes' switching scheme to devastating effect."},
        {"block_index": 3, "heading": "Support cast contributed around the star",
         "body": "With Clearwater's defense focused on Webb, Andre Simms (18 points) and Tyler Cross (15) shot a combined 12-of-18 from the field. The Marlins' ball movement — 27 assists on 35 field goals — was the hallmark of a team playing within itself even while their star dominated."},
        {"block_index": 4, "heading": "Cranes couldn't stop the bleeding",
         "body": "Devon Blake's 21 points were a bright spot, but Clearwater was outmatched at multiple positions and their best defensive player fouled out midway through the second half. Webb's final free-throw display with 90 seconds left set a new career high and brought a deserved standing ovation."},
    ],
    "notes": "",
}

# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------

SPORT_BUILDERS = {
    "nba":   nba_plays,
    "nhl":   nhl_plays,
    "mlb":   mlb_plays,
    "nfl":   nfl_plays,
    "ncaab": ncaab_plays,
}

SPORT_LABELS = {
    "nba": "NBA", "nhl": "NHL", "mlb": "MLB", "nfl": "NFL", "ncaab": "NCAAB",
}

GAME_DATES = {
    "nba":   "2025-01-15T19:00:00Z",
    "nhl":   "2025-01-18T20:00:00Z",
    "mlb":   "2025-04-10T18:10:00Z",
    "nfl":   "2024-11-03T13:00:00Z",
    "ncaab": "2025-02-20T19:00:00Z",
}


def build_fixture(sport: str, shape: str) -> dict:
    t = TEAMS[sport]
    builder = SPORT_BUILDERS[sport]
    plays, home_final, away_final = builder(shape)
    corpus_id = f"{sport}_{shape}"

    return {
        "corpus_id": corpus_id,
        "sport": SPORT_LABELS[sport],
        "game_shape": shape,
        "source_game_key": f"{sport}-corpus-{shape}",
        "game_date": GAME_DATES[sport],
        "home_team": t["home"],
        "away_team": t["away"],
        "final_score": (
            {"home": home_final, "away": away_final}
            if home_final is not None else None
        ),
        "pbp": {
            "source_game_key": f"{sport}-corpus-{shape}",
            "plays": plays,
        },
    }


def build_reference(sport: str, shape: str) -> dict:
    corpus_id = f"{sport}_{shape}"
    ref = REFERENCES[corpus_id]
    sc = ref["scores"]
    ws = weighted_score(sc["factual_accuracy"], sc["completeness"],
                        sc["fluency"], sc["tone_voice"], sc["conciseness"])
    return {
        "corpus_id": corpus_id,
        "validation_date": VALIDATION_DATE,
        "validated_by": "human",
        "scores": {**sc, "weighted": ws},
        "blocks": ref["blocks"],
        "notes": ref["notes"],
    }


def build_metadata_entry(sport: str, shape: str) -> dict:
    return {
        "corpus_id": f"{sport}_{shape}",
        "sport": SPORT_LABELS[sport],
        "game_shape": shape,
        "validation_date": VALIDATION_DATE,
        "fixture_file": f"{sport}_{shape}.json",
        "reference_file": f"reference/{sport}_{shape}.json",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    entries = []
    for sport in SPORTS:
        for shape in SHAPES:
            corpus_id = f"{sport}_{shape}"

            fixture = build_fixture(sport, shape)
            fixture_path = os.path.join(ROOT, f"{corpus_id}.json")
            with open(fixture_path, "w") as f:
                json.dump(fixture, f, indent=2)
            print(f"  wrote {fixture_path}")

            ref = build_reference(sport, shape)
            ref_path = os.path.join(REF_DIR, f"{corpus_id}.json")
            with open(ref_path, "w") as f:
                json.dump(ref, f, indent=2)
            print(f"  wrote {ref_path}")

            entries.append(build_metadata_entry(sport, shape))

    metadata = {
        "corpus_version": CORPUS_VERSION,
        "created_at": f"{VALIDATION_DATE}T00:00:00Z",
        "sports": SPORT_LABELS,
        "shapes": SHAPES,
        "total_entries": len(entries),
        "entries": entries,
    }
    meta_path = os.path.join(ROOT, "corpus_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"  wrote {meta_path}")
    print(f"\nDone — {len(entries)} fixture pairs + metadata.")


if __name__ == "__main__":
    main()
