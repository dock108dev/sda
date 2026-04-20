"""Contract tests: isLive/isFinal/isPregame computed predicates on GameSummary + GameMeta.

One assertion per predicate per GameStatus variant to satisfy ISSUE-008 criteria.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.routers.sports.schemas.games import GameMeta, GameSummary

# ---------------------------------------------------------------------------
# Minimal fixture helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_summary(status: str | None) -> GameSummary:
    return GameSummary(
        id=1,
        league_code="NBA",
        game_date=_NOW,
        home_team="TeamA",
        away_team="TeamB",
        status=status,
        has_boxscore=False,
        has_player_stats=False,
        has_odds=False,
        has_social=False,
        has_pbp=False,
        has_flow=False,
        play_count=0,
        social_post_count=0,
    )


def _make_meta(status: str) -> GameMeta:
    return GameMeta(
        id=1,
        league_code="NBA",
        season=2026,
        game_date=_NOW,
        home_team="TeamA",
        away_team="TeamB",
        status=status,
        has_boxscore=False,
        has_player_stats=False,
        has_odds=False,
        has_social=False,
        has_pbp=False,
        has_flow=False,
        play_count=0,
        social_post_count=0,
    )


# ---------------------------------------------------------------------------
# Expected predicate values per status
# Format: (status, is_live, is_final, is_pregame)
# ---------------------------------------------------------------------------

_STATUS_EXPECTATIONS: list[tuple[str, bool, bool, bool]] = [
    ("scheduled",     False, False, True),
    ("pregame",       False, False, True),
    ("live",          True,  False, False),
    ("in_progress",   True,  False, False),
    ("halftime",      True,  False, False),
    ("final",         False, True,  False),
    ("completed",     False, True,  False),
    ("official",      False, True,  False),
    ("archived",      False, False, False),
    ("postponed",     False, False, False),
    ("cancelled",     False, False, False),
    ("recap_pending", False, False, False),
    ("recap_ready",   False, False, False),
    ("recap_failed",  False, False, False),
]

_PREDICATE_INDEX = {"is_live": 1, "is_final": 2, "is_pregame": 3}


# ---------------------------------------------------------------------------
# Parametrized: one test per predicate per status
# ---------------------------------------------------------------------------

def _expand() -> list[tuple[str, str, bool]]:
    rows = []
    for status, live, final, pregame in _STATUS_EXPECTATIONS:
        rows.append((status, "is_live", live))
        rows.append((status, "is_final", final))
        rows.append((status, "is_pregame", pregame))
    return rows


@pytest.mark.parametrize("status,predicate,expected", _expand())
def test_game_summary_predicate(status: str, predicate: str, expected: bool) -> None:
    """GameSummary serialized JSON has correct non-nullable boolean for each status."""
    summary = _make_summary(status)
    data = summary.model_dump(by_alias=True)

    alias = {"is_live": "isLive", "is_final": "isFinal", "is_pregame": "isPregame"}[predicate]
    value = data[alias]

    assert isinstance(value, bool), f"{alias} must be bool, got {type(value)}"
    assert value is expected, f"status={status!r}: expected {alias}={expected}, got {value}"


@pytest.mark.parametrize("status,predicate,expected", _expand())
def test_game_meta_predicate(status: str, predicate: str, expected: bool) -> None:
    """GameMeta serialized JSON has correct non-nullable boolean for each status."""
    meta = _make_meta(status)
    data = meta.model_dump(by_alias=True)

    alias = {"is_live": "isLive", "is_final": "isFinal", "is_pregame": "isPregame"}[predicate]
    value = data[alias]

    assert isinstance(value, bool), f"{alias} must be bool, got {type(value)}"
    assert value is expected, f"status={status!r}: expected {alias}={expected}, got {value}"


# ---------------------------------------------------------------------------
# None-status edge case (GameSummary only — GameMeta.status is non-nullable)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("predicate", ["isLive", "isFinal", "isPregame"])
def test_game_summary_none_status_all_false(predicate: str) -> None:
    summary = _make_summary(None)
    data = summary.model_dump(by_alias=True)
    assert data[predicate] is False


# ---------------------------------------------------------------------------
# Non-nullable guarantee: value must never be None in serialized JSON
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,_l,_f,_p", _STATUS_EXPECTATIONS)
def test_summary_predicates_never_null(status: str, _l: bool, _f: bool, _p: bool) -> None:
    data = _make_summary(status).model_dump(by_alias=True)
    for key in ("isLive", "isFinal", "isPregame"):
        assert data[key] is not None, f"{key} must not be None for status={status!r}"


@pytest.mark.parametrize("status,_l,_f,_p", _STATUS_EXPECTATIONS)
def test_meta_predicates_never_null(status: str, _l: bool, _f: bool, _p: bool) -> None:
    data = _make_meta(status).model_dump(by_alias=True)
    for key in ("isLive", "isFinal", "isPregame"):
        assert data[key] is not None, f"{key} must not be None for status={status!r}"
