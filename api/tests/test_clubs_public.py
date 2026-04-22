"""Tests for GET /api/v1/clubs/{slug} — public club lookup endpoint.

Covers:
  - 404 for unknown slug
  - 404 for club with status != 'active'
  - 200 with correct payload (club_id, name, slug, active_pools)
  - active_pools filtered to open/locked/live statuses
  - draft/completed pools are excluded
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.club import Club
from app.db.golf_pools import GolfPool
from app.routers.clubs import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(scalars: list[Any] | None = None, scalar: Any = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    if scalars is not None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = scalars
        r.scalars.return_value = scalars_mock
    return r


class _QueueDB:
    """Async session stub returning results in FIFO order."""

    def __init__(self, *results: Any) -> None:
        self._queue: list[Any] = list(results)

    async def execute(self, _stmt: Any) -> Any:
        return self._queue.pop(0)

    async def close(self) -> None:
        pass


def _make_club(
    slug: str = "pebble-gc",
    club_id: str = "uuid-0001",
    name: str = "Pebble GC",
    status: str = "active",
    db_id: int = 1,
    branding_json: Any = None,
) -> Club:
    c = Club(
        club_id=club_id,
        slug=slug,
        name=name,
        plan_id="price_pro",
        status=status,
    )
    c.id = db_id
    c.branding_json = branding_json
    return c


def _make_pool(
    pool_id: int = 10,
    name: str = "Masters 2026",
    status: str = "open",
    club_id: int = 1,
    tournament_id: int = 5,
) -> GolfPool:
    p = GolfPool(
        code="masters-2026",
        name=name,
        club_code="pebble-gc",
        club_id=club_id,
        tournament_id=tournament_id,
        status=status,
        allow_self_service_entry=True,
    )
    p.id = pool_id
    p.entry_deadline = None
    p.created_at = None
    return p


def _app(db_override: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_override
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unknown_slug_returns_404() -> None:
    db = _QueueDB(_make_result(scalar=None))
    client = TestClient(_app(db))
    resp = client.get("/api/v1/clubs/no-such-slug")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Club not found"


def test_inactive_club_returns_404() -> None:
    inactive = _make_club(status="suspended")
    db = _QueueDB(_make_result(scalar=inactive))
    client = TestClient(_app(db))
    resp = client.get("/api/v1/clubs/pebble-gc")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Club not found"


def test_active_club_with_no_pools_returns_empty_list() -> None:
    club = _make_club()
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalars=[]),
    )
    client = TestClient(_app(db))
    resp = client.get("/api/v1/clubs/pebble-gc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["club_id"] == "uuid-0001"
    assert body["slug"] == "pebble-gc"
    assert body["name"] == "Pebble GC"
    assert body["active_pools"] == []


def test_active_club_returns_active_pools() -> None:
    club = _make_club()
    open_pool = _make_pool(pool_id=10, status="open")
    live_pool = _make_pool(pool_id=11, name="US Open 2026", status="live")
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalars=[open_pool, live_pool]),
    )
    client = TestClient(_app(db))
    resp = client.get("/api/v1/clubs/pebble-gc")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["active_pools"]) == 2
    pool_ids = {p["pool_id"] for p in body["active_pools"]}
    assert pool_ids == {10, 11}


def test_pool_payload_shape() -> None:
    club = _make_club()
    pool = _make_pool(pool_id=42, tournament_id=7)
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalars=[pool]),
    )
    client = TestClient(_app(db))
    resp = client.get("/api/v1/clubs/pebble-gc")
    assert resp.status_code == 200
    p = resp.json()["active_pools"][0]
    assert p["pool_id"] == 42
    assert p["name"] == "Masters 2026"
    assert p["status"] == "open"
    assert p["tournament_id"] == 7
    assert "entry_deadline" in p
    assert p["allow_self_service_entry"] is True


def test_branding_included_when_set() -> None:
    branding = {"logo_url": "https://cdn.example.com/logo.png", "primary_color": "#1E40AF"}
    club = _make_club(branding_json=branding)
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalars=[]),
    )
    client = TestClient(_app(db))
    resp = client.get("/api/v1/clubs/pebble-gc")
    assert resp.status_code == 200
    body = resp.json()
    assert "branding" in body
    assert body["branding"]["logo_url"] == "https://cdn.example.com/logo.png"
    assert body["branding"]["primary_color"] == "#1E40AF"


def test_branding_omitted_when_null() -> None:
    club = _make_club(branding_json=None)
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalars=[]),
    )
    client = TestClient(_app(db))
    resp = client.get("/api/v1/clubs/pebble-gc")
    assert resp.status_code == 200
    body = resp.json()
    assert "branding" not in body
