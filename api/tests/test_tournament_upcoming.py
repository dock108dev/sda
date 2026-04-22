"""Integration tests for GET /api/golf/tournaments/upcoming.

Tests the field_available flag logic and the 90-day lookahead window using
mocked DB sessions — no live database required.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.golf.tournaments import list_upcoming_tournaments


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_tournament(
    tid: int,
    name: str,
    start_date: date,
    end_date: date | None = None,
) -> MagicMock:
    t = MagicMock()
    t.id = tid
    t.event_name = name
    t.start_date = start_date
    t.end_date = end_date
    return t


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _StubScalarsResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return self._items


class _StubDB:
    """DB stub that returns a fixed tournament list and configurable field counts."""

    def __init__(
        self,
        tournaments: list[Any],
        field_counts: dict[int, int] | None = None,
    ) -> None:
        self._tournaments = tournaments
        self._field_counts = field_counts or {}
        self._call_n = 0

    async def execute(self, stmt: Any) -> Any:
        self._call_n += 1
        if self._call_n == 1:
            # First call: tournament list query
            result = MagicMock()
            result.scalars.return_value = _StubScalarsResult(self._tournaments)
            return result
        else:
            # Second call: field count GROUP BY query
            result = MagicMock()
            result.__iter__ = MagicMock(
                return_value=iter(self._field_counts.items())
            )
            return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListUpcomingTournaments:
    def test_returns_tournaments_within_window(self) -> None:
        today = date.today()
        t = _make_tournament(1, "The Masters", today + timedelta(days=10))
        db = _StubDB([t], field_counts={1: 72})
        result = _run(list_upcoming_tournaments(days_ahead=90, db=db))
        assert result["count"] == 1
        assert result["tournaments"][0]["tournament_id"] == 1
        assert result["tournaments"][0]["name"] == "The Masters"

    def test_field_available_true_when_field_data_exists(self) -> None:
        today = date.today()
        t = _make_tournament(2, "US Open", today + timedelta(days=30))
        db = _StubDB([t], field_counts={2: 156})
        result = _run(list_upcoming_tournaments(days_ahead=90, db=db))
        assert result["tournaments"][0]["field_available"] is True

    def test_field_available_false_when_no_field_data(self) -> None:
        today = date.today()
        t = _make_tournament(3, "The Open Championship", today + timedelta(days=60))
        db = _StubDB([t], field_counts={})  # no field rows
        result = _run(list_upcoming_tournaments(days_ahead=90, db=db))
        assert result["tournaments"][0]["field_available"] is False

    def test_mixed_field_availability(self) -> None:
        today = date.today()
        t1 = _make_tournament(10, "Tournament A", today + timedelta(days=5))
        t2 = _make_tournament(11, "Tournament B", today + timedelta(days=45))
        db = _StubDB([t1, t2], field_counts={10: 120})  # only t1 has field data
        result = _run(list_upcoming_tournaments(days_ahead=90, db=db))
        by_id = {r["tournament_id"]: r for r in result["tournaments"]}
        assert by_id[10]["field_available"] is True
        assert by_id[11]["field_available"] is False

    def test_empty_result_when_no_upcoming_tournaments(self) -> None:
        db = _StubDB([], field_counts={})
        result = _run(list_upcoming_tournaments(days_ahead=90, db=db))
        assert result["count"] == 0
        assert result["tournaments"] == []

    def test_start_date_serialized_as_iso_string(self) -> None:
        today = date.today()
        start = today + timedelta(days=7)
        t = _make_tournament(4, "PGA Championship", start, end_date=today + timedelta(days=10))
        db = _StubDB([t], field_counts={4: 50})
        result = _run(list_upcoming_tournaments(days_ahead=90, db=db))
        entry = result["tournaments"][0]
        assert entry["start_date"] == start.isoformat()
        assert entry["end_date"] == (today + timedelta(days=10)).isoformat()

    def test_null_end_date_serialized_as_none(self) -> None:
        today = date.today()
        t = _make_tournament(5, "No End Date Tournament", today + timedelta(days=20), end_date=None)
        db = _StubDB([t], field_counts={5: 10})
        result = _run(list_upcoming_tournaments(days_ahead=90, db=db))
        assert result["tournaments"][0]["end_date"] is None
