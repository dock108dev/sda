"""Integration tests for POST /api/golf/pools/:id/duplicate (ISSUE-018)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies.roles import require_admin
from app.routers.golf import router


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

def _make_client(
    *,
    pool: Any | None = None,
    new_pool_id: int = 999,
) -> TestClient:
    """Build a TestClient wired to a fake AsyncSession."""

    db = AsyncMock()

    async def _get(model, pk):
        if model.__name__ == "GolfPool" and pool is not None and pk == pool.id:
            return pool
        return None

    db.get.side_effect = _get

    async def _refresh(obj):
        obj.id = new_pool_id
        obj.created_at = datetime(2026, 4, 22, tzinfo=timezone.utc)
        obj.updated_at = datetime(2026, 4, 22, tzinfo=timezone.utc)

    db.refresh.side_effect = _refresh

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_admin] = lambda: "admin"

    return TestClient(app, raise_server_exceptions=True)


def _pool_obj(**overrides):
    from types import SimpleNamespace

    defaults = dict(
        id=1,
        code="open2026",
        name="Masters 2026",
        club_code="rvcc",
        club_id=10,
        tournament_id=5,
        status="open",
        rules_json={"variant": "rvcc", "pick_count": 7},
        entry_open_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        entry_deadline=datetime(2026, 4, 10, tzinfo=timezone.utc),
        scoring_enabled=True,
        max_entries_per_email=3,
        require_upload=False,
        allow_self_service_entry=True,
        notes="Test pool notes",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDuplicatePool:
    def test_duplicate_returns_201_with_location(self):
        pool = _pool_obj()
        client = _make_client(pool=pool, new_pool_id=999)

        resp = client.post("/api/golf/pools/1/duplicate?club_code=rvcc")

        assert resp.status_code == 201
        assert resp.headers["location"] == "/pools/999/setup"

    def test_duplicate_clones_structural_fields(self):
        pool = _pool_obj()
        client = _make_client(pool=pool, new_pool_id=999)

        resp = client.post("/api/golf/pools/1/duplicate?club_code=rvcc")
        body = resp.json()

        assert body["result"] == "created"
        assert body["name"] == "Masters 2026 (Copy)"
        assert body["club_code"] == "rvcc"
        assert body["rules_json"] == {"variant": "rvcc", "pick_count": 7}
        assert body["max_entries_per_email"] == 3
        assert body["scoring_enabled"] is True
        assert body["require_upload"] is False
        assert body["allow_self_service_entry"] is True
        assert body["notes"] == "Test pool notes"

    def test_duplicate_resets_temporal_fields(self):
        pool = _pool_obj()
        client = _make_client(pool=pool, new_pool_id=999)

        resp = client.post("/api/golf/pools/1/duplicate?club_code=rvcc")
        body = resp.json()

        assert body.get("tournament_id") is None
        assert body.get("entry_open_at") is None
        assert body.get("entry_deadline") is None
        assert body["status"] == "draft"

    def test_duplicate_generates_new_code(self):
        pool = _pool_obj()
        client = _make_client(pool=pool, new_pool_id=999)

        resp = client.post("/api/golf/pools/1/duplicate?club_code=rvcc")
        body = resp.json()

        new_code = body.get("code")
        assert new_code is not None
        assert new_code != pool.code

    def test_duplicate_wrong_club_returns_403(self):
        pool = _pool_obj(club_code="rvcc")
        client = _make_client(pool=pool)

        resp = client.post("/api/golf/pools/1/duplicate?club_code=crestmont")

        assert resp.status_code == 403

    def test_duplicate_unknown_pool_returns_404(self):
        client = _make_client(pool=None)

        resp = client.post("/api/golf/pools/42/duplicate?club_code=rvcc")

        assert resp.status_code == 404

    def test_duplicate_pool_with_entries_creates_empty_pool(self):
        """Duplicate a pool that conceptually has 10 entries; new pool gets none."""
        pool = _pool_obj()
        client = _make_client(pool=pool, new_pool_id=999)

        resp = client.post("/api/golf/pools/1/duplicate?club_code=rvcc")

        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == 999
        assert body["result"] == "created"
        assert body["status"] == "draft"
        # Verify no entry-level keys were included — the new pool starts empty.
        assert "entries" not in body
        assert "picks" not in body
