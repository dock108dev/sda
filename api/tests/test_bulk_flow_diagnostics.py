"""Tests for bulk flow generation per-game diagnostics.

Covers ``_count_pbp_and_goals``, the helper that powers the
``goals_found``/``pbp_exists`` fields in bulk flow log entries — the
observability hook that lets ops see when an NHL (or any) game is skipped
because PBP is missing or contains no scoring plays.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks.bulk_flow_generation import _count_pbp_and_goals


def _session_with_rows(rows: list[tuple[int | None, int | None]]) -> AsyncMock:
    """AsyncMock session whose execute(...) returns the given (home, away) rows.

    Mirrors the SQLAlchemy result API used by ``_count_pbp_and_goals``:
    ``result.all()`` returns an iterable of row tuples.
    """
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_count_pbp_and_goals_no_plays():
    session = _session_with_rows([])
    pbp_count, goals_found = await _count_pbp_and_goals(session, game_id=1)
    assert pbp_count == 0
    assert goals_found == 0


@pytest.mark.asyncio
async def test_count_pbp_and_goals_nhl_goals_detected():
    """NHL: each goal flips home or away score — count exactly one per goal."""
    rows = [
        (0, 0),  # opening faceoff, no score
        (0, 0),  # shot, no goal
        (1, 0),  # home goal #1
        (1, 0),  # face-off
        (1, 1),  # away goal
        (2, 1),  # home goal #2
        (2, 1),  # penalty, no score change
    ]
    session = _session_with_rows(rows)
    pbp_count, goals_found = await _count_pbp_and_goals(session, game_id=42)
    assert pbp_count == 7
    assert goals_found == 3


@pytest.mark.asyncio
async def test_count_pbp_and_goals_first_play_with_score_counts():
    """If the first play already shows a non-zero score, count it as scoring."""
    rows = [(1, 0), (1, 0)]
    session = _session_with_rows(rows)
    _, goals_found = await _count_pbp_and_goals(session, game_id=7)
    assert goals_found == 1


@pytest.mark.asyncio
async def test_count_pbp_and_goals_handles_null_scores():
    """Null scores are treated as 0 — must not crash and must not count."""
    rows = [(None, None), (None, None), (1, None), (1, 1)]
    session = _session_with_rows(rows)
    pbp_count, goals_found = await _count_pbp_and_goals(session, game_id=9)
    assert pbp_count == 4
    # Transitions: None→None (0), None→1 (count), 1→1+1 (count)
    assert goals_found == 2


@pytest.mark.asyncio
async def test_count_pbp_and_goals_zero_scoring_game():
    """Game with PBP but no scoring (e.g., scoreless tie) returns goals_found=0."""
    rows = [(0, 0)] * 50
    session = _session_with_rows(rows)
    pbp_count, goals_found = await _count_pbp_and_goals(session, game_id=11)
    assert pbp_count == 50
    assert goals_found == 0
