"""Tests for PUT /api/v1/clubs/{club_id}/branding — ISSUE-022.

Covers:
  - 401 when no user_id on request state
  - 403 when caller has viewer or no membership (not owner)
  - 402 when club plan lacks custom_branding entitlement
  - 422 on invalid hex color format
  - 422 on non-HTTPS logo_url
  - 200 happy path: owner on enterprise plan sets branding, response reflects it
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.club import Club
from app.db.club_membership import ClubMembership
from app.dependencies.roles import require_user
from app.routers.club_branding import router
from app.services.entitlement import EntitlementError, EntitlementService


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _make_result(scalar: Any = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalar.return_value = scalar
    return r


class _QueueDB:
    def __init__(self, *results: Any) -> None:
        self._queue: list[Any] = list(results)
        self.flushed = False

    async def execute(self, _stmt: Any) -> Any:
        return self._queue.pop(0)

    async def flush(self) -> None:
        self.flushed = True

    async def close(self) -> None:
        pass


def _make_club(
    club_id: str = "uuid-1111",
    plan_id: str = "price_enterprise",
    status: str = "active",
    db_id: int = 1,
) -> Club:
    c = Club(
        club_id=club_id,
        slug="test-club",
        name="Test Club",
        plan_id=plan_id,
        status=status,
    )
    c.id = db_id
    c.branding_json = None
    return c


def _make_membership(user_id: int = 42, role: str = "owner", club_id: int = 1) -> ClubMembership:
    m = ClubMembership(club_id=club_id, user_id=user_id, role=role)
    m.id = 99
    return m


# ---------------------------------------------------------------------------
# App factory helpers
# ---------------------------------------------------------------------------


def _app(db_override: Any, *, user_id: int | None = 42) -> FastAPI:
    """Build a minimal app with the branding router and optional user injection."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_override
    # Bypass require_user; set user_id on state manually via middleware
    app.dependency_overrides[require_user] = lambda: "user"

    @app.middleware("http")
    async def _inject_user(request: Request, call_next: Any) -> Any:
        if user_id is not None:
            request.state.user_id = user_id
        return await call_next(request)

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_user_id_on_state_returns_401() -> None:
    """If require_user passes but no user_id on state, return 401."""
    db = _QueueDB(_make_result(scalar=_make_club()))
    client = TestClient(_app(db, user_id=None))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={})
    assert resp.status_code == 401


def test_club_not_found_returns_404() -> None:
    db = _QueueDB(_make_result(scalar=None))
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/no-such-id/branding", json={})
    assert resp.status_code == 404


def test_viewer_membership_returns_403() -> None:
    club = _make_club()
    viewer = _make_membership(role="viewer")
    db = _QueueDB(_make_result(scalar=club), _make_result(scalar=viewer))
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={"primary_color": "#AABBCC"})
    assert resp.status_code == 403


def test_no_membership_returns_403() -> None:
    club = _make_club()
    db = _QueueDB(_make_result(scalar=club), _make_result(scalar=None))
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={})
    assert resp.status_code == 403


def test_free_tier_owner_returns_402() -> None:
    """Owner on starter plan lacks custom_branding — must return 402."""
    club = _make_club(plan_id="price_starter")
    owner = _make_membership(role="owner")
    # assert_feature needs one more DB query for _get_limits
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalar=owner),
        _make_result(scalar=club),  # consumed by _get_limits inside assert_feature
    )
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={"primary_color": "#112233"})
    assert resp.status_code == 402


def test_pro_tier_owner_returns_402() -> None:
    """Owner on pro plan also lacks custom_branding — must return 402."""
    club = _make_club(plan_id="price_pro")
    owner = _make_membership(role="owner")
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalar=owner),
        _make_result(scalar=club),
    )
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={"primary_color": "#112233"})
    assert resp.status_code == 402


def test_invalid_hex_returns_422() -> None:
    """primary_color with invalid hex format must return 422."""
    club = _make_club()
    owner = _make_membership(role="owner")
    # Validation fails before DB query for entitlement
    db = _QueueDB(_make_result(scalar=club), _make_result(scalar=owner))
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={"primary_color": "red"})
    assert resp.status_code == 422


def test_accent_color_invalid_hex_returns_422() -> None:
    club = _make_club()
    owner = _make_membership(role="owner")
    db = _QueueDB(_make_result(scalar=club), _make_result(scalar=owner))
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={"accent_color": "#GGH"})
    assert resp.status_code == 422


def test_non_https_logo_url_returns_422() -> None:
    """HTTP logo_url must be rejected with 422."""
    club = _make_club()
    owner = _make_membership(role="owner")
    db = _QueueDB(_make_result(scalar=club), _make_result(scalar=owner))
    client = TestClient(_app(db))
    resp = client.put(
        "/api/v1/clubs/uuid-1111/branding",
        json={"logo_url": "http://example.com/logo.png"},
    )
    assert resp.status_code == 422


def test_enterprise_owner_sets_branding_successfully() -> None:
    """Owner on enterprise plan with valid payload — 200 with branding response."""
    club = _make_club(plan_id="price_enterprise")
    owner = _make_membership(role="owner")
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalar=owner),
        _make_result(scalar=club),  # _get_limits query inside assert_feature
    )
    client = TestClient(_app(db))
    payload = {
        "logo_url": "https://cdn.example.com/logo.png",
        "primary_color": "#1e40af",
        "accent_color": "#93c5fd",
    }
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["clubId"] == "uuid-1111"
    assert body["branding"]["logo_url"] == "https://cdn.example.com/logo.png"
    assert body["branding"]["primary_color"] == "#1E40AF"
    assert body["branding"]["accent_color"] == "#93C5FD"
    assert db.flushed


def test_null_fields_omitted_from_branding() -> None:
    """Fields that are null are not persisted in branding_json."""
    club = _make_club(plan_id="price_enterprise")
    owner = _make_membership(role="owner")
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalar=owner),
        _make_result(scalar=club),
    )
    client = TestClient(_app(db))
    resp = client.put(
        "/api/v1/clubs/uuid-1111/branding",
        json={"primary_color": "#AABBCC", "logo_url": None, "accent_color": None},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "logo_url" not in body["branding"]
    assert body["branding"]["primary_color"] == "#AABBCC"


def test_empty_payload_clears_branding() -> None:
    """All-null payload results in branding_json set to None (no keys in response)."""
    club = _make_club(plan_id="price_enterprise")
    owner = _make_membership(role="owner")
    db = _QueueDB(
        _make_result(scalar=club),
        _make_result(scalar=owner),
        _make_result(scalar=club),
    )
    client = TestClient(_app(db))
    resp = client.put("/api/v1/clubs/uuid-1111/branding", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["branding"] == {}
