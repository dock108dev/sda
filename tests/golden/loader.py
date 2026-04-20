"""Typed fixture loader for the golden corpus (ISSUE-003).

Public API
----------
GoldenFixture     — TypedDict representing a single fixture file.
load_fixture()    — Load one fixture by path, returning a GoldenFixture.
load_sport_fixtures() — Load all fixtures for a given sport.
load_all_fixtures()   — Load every fixture across all sports.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typing_extensions import NotRequired, TypedDict

# ---------------------------------------------------------------------------
# TypedDict schema
# ---------------------------------------------------------------------------

GOLDEN_DIR = Path(__file__).parent
SPORTS = ("NFL", "NBA", "MLB", "NHL")

# Valid semantic roles (mirrors SemanticRole in api/app/services/pipeline/stages/block_types.py)
VALID_ROLES = frozenset({"SETUP", "MOMENTUM_SHIFT", "RESPONSE", "DECISION_POINT", "RESOLUTION"})


class _Team(TypedDict):
    name: str
    abbreviation: str


class _Play(TypedDict):
    play_index: int
    quarter: int
    game_clock: str
    play_type: str
    team_abbreviation: str
    player_name: str
    description: str
    home_score: int
    away_score: int
    player_id: NotRequired[str]
    raw_data: NotRequired[dict[str, Any]]


class _Pbp(TypedDict):
    source_game_key: str
    plays: list[_Play]


class _FinalScore(TypedDict):
    home: int
    away: int


class _FlowSkeleton(TypedDict):
    block_count_range: list[int]   # [min, max]
    roles_required: list[str]
    has_overtime: bool


class GoldenFixture(TypedDict):
    """A single golden corpus fixture."""

    corpus_id: str
    sport: str
    game_shape: str
    flow_source: str                       # "LLM" | "TEMPLATE"
    quality_score_floor: float
    forbidden_phrases: int                 # always 0 in stored fixtures
    source_game_key: str
    game_date: str
    home_team: _Team
    away_team: _Team
    final_score: _FinalScore | None        # null for incomplete_pbp / postponement
    expected_blocks: list[str]             # ordered block role sequence
    expected_block_type_counts: dict[str, int]  # role → count
    expected_flow_skeleton: _FlowSkeleton
    pbp: _Pbp
    postponement_reason: NotRequired[str | None]


# ---------------------------------------------------------------------------
# Loader functions
# ---------------------------------------------------------------------------


def load_fixture(path: Path) -> GoldenFixture:
    """Load and return a single fixture file as a GoldenFixture.

    Does not perform deep validation — use the test runner for that.
    """
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[return-value]


def load_sport_fixtures(sport: str) -> list[GoldenFixture]:
    """Return all fixtures for *sport* (case-insensitive), sorted by corpus_id."""
    sport_dir = GOLDEN_DIR / sport.lower()
    if not sport_dir.is_dir():
        return []
    return [
        load_fixture(p)
        for p in sorted(sport_dir.glob("*.json"))
    ]


def load_all_fixtures() -> list[GoldenFixture]:
    """Return every fixture across all sports, sorted by (sport, corpus_id)."""
    fixtures: list[GoldenFixture] = []
    for sport in SPORTS:
        fixtures.extend(load_sport_fixtures(sport))
    return fixtures
