"""Focused tests for cursor/snapshot guardrails in FairBet odds endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.routers.fairbet import odds as odds_router


class _Result:
    def __init__(self, scalar_value=None):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


def _base_kwargs(session: AsyncMock) -> dict:
    return {
        "request": None,
        "session": session,
        "league": None,
        "market_category": None,
        "exclude_categories": None,
        "game_id": None,
        "book": None,
        "player_name": None,
        "min_ev": None,
        "has_fair": None,
        "sort_by": "game_time",
        "limit": 100,
        "offset": 0,
        "cursor": None,
        "snapshot_id": None,
        "include_meta": False,
    }


@pytest.mark.asyncio
async def test_ev_snapshot_missing_returns_410(monkeypatch):
    session = AsyncMock()
    session.execute.return_value = _Result(None)  # max(updated_at)
    monkeypatch.setattr(odds_router, "get_snapshot", lambda _: None)

    with pytest.raises(HTTPException) as exc:
        kwargs = _base_kwargs(session)
        kwargs["sort_by"] = "ev"
        kwargs["snapshot_id"] = "dead-snapshot"
        await odds_router.get_fairbet_odds(**kwargs)
    assert exc.value.status_code == 410
    assert exc.value.detail == "Snapshot expired or not found."


@pytest.mark.asyncio
async def test_cursor_sort_mismatch_returns_400():
    session = AsyncMock()
    session.execute.return_value = _Result(None)  # max(updated_at)
    bad_cursor = odds_router.encode_cursor({"sort": "market", "v": ["spreads", "team:a", "2026-01-01T00:00:00+00:00", 1, -3.5]})

    with pytest.raises(HTTPException) as exc:
        kwargs = _base_kwargs(session)
        kwargs["sort_by"] = "game_time"
        kwargs["cursor"] = bad_cursor
        await odds_router.get_fairbet_odds(**kwargs)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Cursor sort does not match sort_by."


@pytest.mark.asyncio
async def test_invalid_cursor_returns_400():
    session = AsyncMock()
    session.execute.return_value = _Result(None)  # max(updated_at)

    with pytest.raises(HTTPException) as exc:
        kwargs = _base_kwargs(session)
        kwargs["sort_by"] = "game_time"
        kwargs["cursor"] = "%%%not-a-valid-cursor%%%"
        await odds_router.get_fairbet_odds(**kwargs)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid cursor."


@pytest.mark.asyncio
async def test_invalid_ev_snapshot_cursor_returns_400(monkeypatch):
    session = AsyncMock()
    session.execute.return_value = _Result(None)  # max(updated_at)
    monkeypatch.setattr(odds_router, "build_query_hash", lambda _: "q")
    monkeypatch.setattr(
        odds_router,
        "get_snapshot",
        lambda _: {
            "query_hash": "q",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "items": [],
            "total": 0,
        },
    )

    with pytest.raises(HTTPException) as exc:
        kwargs = _base_kwargs(session)
        kwargs["sort_by"] = "ev"
        kwargs["snapshot_id"] = "snap-1"
        kwargs["cursor"] = "%%%not-a-valid-cursor%%%"
        await odds_router.get_fairbet_odds(**kwargs)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid cursor for EV snapshot."


@pytest.mark.asyncio
async def test_has_fair_requires_ev_sort():
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        kwargs = _base_kwargs(session)
        kwargs["sort_by"] = "game_time"
        kwargs["has_fair"] = True
        await odds_router.get_fairbet_odds(**kwargs)
    assert exc.value.status_code == 400
    assert exc.value.detail == "has_fair/min_ev require sort_by=ev snapshot mode."


@pytest.mark.asyncio
async def test_min_ev_requires_ev_sort():
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        kwargs = _base_kwargs(session)
        kwargs["sort_by"] = "market"
        kwargs["min_ev"] = 1.5
        await odds_router.get_fairbet_odds(**kwargs)
    assert exc.value.status_code == 400
    assert exc.value.detail == "has_fair/min_ev require sort_by=ev snapshot mode."
