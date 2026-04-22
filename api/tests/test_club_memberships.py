"""Tests for club membership endpoints — invite flow and RBAC.

Covers:
  - POST /api/v1/clubs/invites/{token}/accept
  - POST /api/v1/clubs/{club_id}/invites
  - GET  /api/v1/clubs/{club_id}/members
  - DELETE /api/v1/clubs/{club_id}/members/{user_id}

Integration cycle: invite → accept → list → remove (two-admin club).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from sqlalchemy.exc import IntegrityError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.club import Club
from app.db.club_membership import ClubMembership
from app.db.users import User
from app.dependencies.roles import create_access_token, create_invite_token
from app.routers.club_memberships import router


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLUB_UUID = "uuid-club-0001"
_OWNER_ID = 1
_ADMIN_ID = 2
_VIEWER_ID = 3
_OUTSIDER_ID = 99


# ---------------------------------------------------------------------------
# DB stub helpers
# ---------------------------------------------------------------------------


class _AsyncDB:
    """Async session stub: returns results from a FIFO queue."""

    def __init__(self, *results: Any) -> None:
        self._queue: list[Any] = list(results)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self._flush_raises: Exception | None = None

    def set_flush_raises(self, exc: Exception) -> None:
        self._flush_raises = exc

    async def execute(self, _stmt: Any) -> Any:
        return self._queue.pop(0)

    async def flush(self) -> None:
        if self._flush_raises is not None:
            raise self._flush_raises

    async def rollback(self) -> None:
        pass

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def close(self) -> None:
        pass


def _scalar(value: Any) -> Any:
    from unittest.mock import MagicMock

    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.scalar.return_value = value
    return r


def _scalars(*items: Any) -> Any:
    from unittest.mock import MagicMock

    r = MagicMock()
    rows_mock = MagicMock()
    rows_mock.all.return_value = list(items)
    r.all.return_value = list(items)
    return r


def _make_club(db_id: int = 10) -> Club:
    c = Club(
        club_id=_CLUB_UUID,
        slug="test-gc",
        name="Test GC",
        plan_id="price_pro",
        status="active",
    )
    c.id = db_id
    return c


def _make_membership(
    club_db_id: int = 10,
    user_id: int = _OWNER_ID,
    role: str = "owner",
    member_id: int = 1,
) -> ClubMembership:
    m = ClubMembership(
        club_id=club_db_id,
        user_id=user_id,
        role=role,
        invited_at=datetime.now(UTC),
        accepted_at=datetime.now(UTC),
    )
    m.id = member_id
    return m


def _make_user(user_id: int, email: str = "user@example.com") -> User:
    u = User(email=email, role="user", is_active=True)
    u.id = user_id
    return u


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _app(db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    return app


def _bearer(user_id: int, role: str = "user") -> dict[str, str]:
    token = create_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# accept_invite tests
# ---------------------------------------------------------------------------


def test_accept_invite_ok() -> None:
    invite_token = create_invite_token(
        club_id=10,
        invitee_email="new@example.com",
        role="admin",
        inviter_id=_OWNER_ID,
    )
    club = _make_club()
    db = _AsyncDB(_scalar(club))

    client = TestClient(_app(db))
    resp = client.post(
        f"/api/v1/clubs/invites/{invite_token}/accept",
        headers=_bearer(_ADMIN_ID),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["clubId"] == _CLUB_UUID
    assert body["name"] == "Test GC"
    assert body["slug"] == "test-gc"
    assert len(db.added) == 1
    assert db.added[0].role == "admin"
    assert db.added[0].user_id == _ADMIN_ID


def test_accept_invite_expired_token_returns_410() -> None:
    import jwt as _jwt
    from datetime import timedelta

    now = datetime.now(UTC)
    from app.config import settings

    expired_token = _jwt.encode(
        {
            "sub": "new@example.com",
            "purpose": "club_invite",
            "club_id": 10,
            "role": "admin",
            "inviter_id": _OWNER_ID,
            "iat": now - timedelta(hours=25),
            "exp": now - timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    db = _AsyncDB()
    client = TestClient(_app(db))
    resp = client.post(
        f"/api/v1/clubs/invites/{expired_token}/accept",
        headers=_bearer(_ADMIN_ID),
    )
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"].lower()


def test_accept_invite_invalid_token_returns_410() -> None:
    db = _AsyncDB()
    client = TestClient(_app(db))
    resp = client.post(
        "/api/v1/clubs/invites/not-a-jwt/accept",
        headers=_bearer(_ADMIN_ID),
    )
    assert resp.status_code == 410


def test_accept_invite_already_member_returns_409() -> None:
    invite_token = create_invite_token(
        club_id=10,
        invitee_email="existing@example.com",
        role="viewer",
        inviter_id=_OWNER_ID,
    )
    club = _make_club()
    db = _AsyncDB(_scalar(club))
    db.set_flush_raises(IntegrityError("duplicate", None, None))

    client = TestClient(_app(db))
    resp = client.post(
        f"/api/v1/clubs/invites/{invite_token}/accept",
        headers=_bearer(_ADMIN_ID),
    )
    assert resp.status_code == 409
    assert "already a member" in resp.json()["detail"].lower()


def test_accept_invite_unauthenticated_returns_4xx() -> None:
    invite_token = create_invite_token(
        club_id=10,
        invitee_email="new@example.com",
        role="viewer",
        inviter_id=_OWNER_ID,
    )
    db = _AsyncDB()
    client = TestClient(_app(db))
    resp = client.post(f"/api/v1/clubs/invites/{invite_token}/accept")
    # No token → resolve_role returns guest → require_user raises 403
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# send_invite tests
# ---------------------------------------------------------------------------


def test_send_invite_ok_viewer() -> None:
    club = _make_club()
    owner_membership = _make_membership(role="owner", user_id=_OWNER_ID)
    owner_user = _make_user(_OWNER_ID, "owner@example.com")
    # execute calls: get_club, get_membership, get_caller_user
    db = _AsyncDB(_scalar(club), _scalar(owner_membership), _scalar(owner_user))

    with patch("app.routers.club_memberships.send_club_invite_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = None
        client = TestClient(_app(db))
        resp = client.post(
            f"/api/v1/clubs/{_CLUB_UUID}/invites",
            json={"email": "viewer@example.com", "role": "viewer"},
            headers=_bearer(_OWNER_ID),
        )

    assert resp.status_code == 202
    assert resp.json()["detail"] == "Invite sent"
    mock_email.assert_called_once()
    call_kwargs = mock_email.call_args.kwargs
    assert call_kwargs["to"] == "viewer@example.com"
    assert call_kwargs["role"] == "viewer"
    assert call_kwargs["club_name"] == "Test GC"


def test_send_invite_admin_enforces_seat_limit() -> None:
    club = _make_club()
    owner_membership = _make_membership(role="owner", user_id=_OWNER_ID)
    # seat count = 3 (at the pro plan limit of 3)
    db = _AsyncDB(_scalar(club), _scalar(owner_membership), _scalar(club), _scalar(3))

    with patch("app.routers.club_memberships.send_club_invite_email", new_callable=AsyncMock):
        client = TestClient(_app(db))
        resp = client.post(
            f"/api/v1/clubs/{_CLUB_UUID}/invites",
            json={"email": "admin2@example.com", "role": "admin"},
            headers=_bearer(_OWNER_ID),
        )

    assert resp.status_code == 402


def test_send_invite_admin_below_seat_limit_ok() -> None:
    club = _make_club()
    owner_membership = _make_membership(role="owner", user_id=_OWNER_ID)
    # seat count = 1 (below pro plan limit of 3)
    owner_user = _make_user(_OWNER_ID, "owner@example.com")
    db = _AsyncDB(_scalar(club), _scalar(owner_membership), _scalar(club), _scalar(1), _scalar(owner_user))

    with patch("app.routers.club_memberships.send_club_invite_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = None
        client = TestClient(_app(db))
        resp = client.post(
            f"/api/v1/clubs/{_CLUB_UUID}/invites",
            json={"email": "admin2@example.com", "role": "admin"},
            headers=_bearer(_OWNER_ID),
        )

    assert resp.status_code == 202


def test_send_invite_non_member_returns_403() -> None:
    club = _make_club()
    db = _AsyncDB(_scalar(club), _scalar(None))  # membership = None

    client = TestClient(_app(db))
    resp = client.post(
        f"/api/v1/clubs/{_CLUB_UUID}/invites",
        json={"email": "x@example.com", "role": "viewer"},
        headers=_bearer(_OUTSIDER_ID),
    )
    assert resp.status_code == 403


def test_send_invite_viewer_caller_returns_403() -> None:
    club = _make_club()
    viewer_membership = _make_membership(role="viewer", user_id=_VIEWER_ID)
    db = _AsyncDB(_scalar(club), _scalar(viewer_membership))

    client = TestClient(_app(db))
    resp = client.post(
        f"/api/v1/clubs/{_CLUB_UUID}/invites",
        json={"email": "x@example.com", "role": "viewer"},
        headers=_bearer(_VIEWER_ID),
    )
    assert resp.status_code == 403


def test_send_invite_invalid_role_returns_422() -> None:
    club = _make_club()
    owner_membership = _make_membership(role="owner")
    db = _AsyncDB(_scalar(club), _scalar(owner_membership))

    client = TestClient(_app(db))
    resp = client.post(
        f"/api/v1/clubs/{_CLUB_UUID}/invites",
        json={"email": "x@example.com", "role": "superuser"},
        headers=_bearer(_OWNER_ID),
    )
    assert resp.status_code == 422


def test_send_invite_unknown_club_returns_404() -> None:
    db = _AsyncDB(_scalar(None))
    client = TestClient(_app(db))
    resp = client.post(
        "/api/v1/clubs/no-such-club/invites",
        json={"email": "x@example.com", "role": "viewer"},
        headers=_bearer(_OWNER_ID),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# list_members tests
# ---------------------------------------------------------------------------


def test_list_members_ok() -> None:
    club = _make_club()
    caller_membership = _make_membership(role="admin", user_id=_ADMIN_ID)

    now = datetime.now(UTC)
    m1 = _make_membership(role="owner", user_id=_OWNER_ID, member_id=1)
    m1.accepted_at = now
    u1 = _make_user(_OWNER_ID, "owner@example.com")

    m2 = _make_membership(role="admin", user_id=_ADMIN_ID, member_id=2)
    m2.accepted_at = now
    u2 = _make_user(_ADMIN_ID, "admin@example.com")

    from unittest.mock import MagicMock

    rows_result = MagicMock()
    rows_result.all.return_value = [(m1, u1), (m2, u2)]

    db = _AsyncDB(_scalar(club), _scalar(caller_membership), rows_result)
    client = TestClient(_app(db))
    resp = client.get(
        f"/api/v1/clubs/{_CLUB_UUID}/members",
        headers=_bearer(_ADMIN_ID),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    emails = {m["email"] for m in body}
    assert "owner@example.com" in emails
    assert "admin@example.com" in emails


def test_list_members_non_member_returns_403() -> None:
    club = _make_club()
    db = _AsyncDB(_scalar(club), _scalar(None))
    client = TestClient(_app(db))
    resp = client.get(
        f"/api/v1/clubs/{_CLUB_UUID}/members",
        headers=_bearer(_OUTSIDER_ID),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# remove_member tests
# ---------------------------------------------------------------------------


def test_remove_member_ok() -> None:
    club = _make_club()
    owner_membership = _make_membership(role="owner", user_id=_OWNER_ID, member_id=1)
    target_membership = _make_membership(role="admin", user_id=_ADMIN_ID, member_id=2)
    db = _AsyncDB(_scalar(club), _scalar(owner_membership), _scalar(target_membership))

    client = TestClient(_app(db))
    resp = client.delete(
        f"/api/v1/clubs/{_CLUB_UUID}/members/{_ADMIN_ID}",
        headers=_bearer(_OWNER_ID),
    )
    assert resp.status_code == 204
    assert db.deleted == [target_membership]


def test_remove_member_self_returns_409() -> None:
    club = _make_club()
    owner_membership = _make_membership(role="owner", user_id=_OWNER_ID, member_id=1)
    db = _AsyncDB(_scalar(club), _scalar(owner_membership))

    client = TestClient(_app(db))
    resp = client.delete(
        f"/api/v1/clubs/{_CLUB_UUID}/members/{_OWNER_ID}",
        headers=_bearer(_OWNER_ID),
    )
    assert resp.status_code == 409
    assert "themselves" in resp.json()["detail"].lower()


def test_remove_member_non_owner_returns_403() -> None:
    club = _make_club()
    admin_membership = _make_membership(role="admin", user_id=_ADMIN_ID, member_id=2)
    db = _AsyncDB(_scalar(club), _scalar(admin_membership))

    client = TestClient(_app(db))
    resp = client.delete(
        f"/api/v1/clubs/{_CLUB_UUID}/members/{_VIEWER_ID}",
        headers=_bearer(_ADMIN_ID),
    )
    assert resp.status_code == 403


def test_remove_member_not_found_returns_404() -> None:
    club = _make_club()
    owner_membership = _make_membership(role="owner", user_id=_OWNER_ID, member_id=1)
    db = _AsyncDB(_scalar(club), _scalar(owner_membership), _scalar(None))

    client = TestClient(_app(db))
    resp = client.delete(
        f"/api/v1/clubs/{_CLUB_UUID}/members/9999",
        headers=_bearer(_OWNER_ID),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Integration cycle: invite → accept → list → remove (two-admin club)
# ---------------------------------------------------------------------------


def test_full_invite_accept_list_remove_cycle() -> None:
    """Two-admin cycle: owner invites a second admin, they accept, list shows both,
    then owner removes the second admin."""
    club = _make_club()

    # --- 1. Owner sends invite ---
    now = datetime.now(UTC)
    owner_membership = _make_membership(role="owner", user_id=_OWNER_ID, member_id=1)
    owner_membership.accepted_at = now
    owner_user = _make_user(_OWNER_ID, "owner@gc.example")

    # DB calls for send_invite:
    #   _get_active_club, _get_membership (owner), check_admin_seat (club + count), get caller User
    invite_db = _AsyncDB(
        _scalar(club),           # _get_active_club
        _scalar(owner_membership),  # _get_membership
        _scalar(club),           # entitlement._get_limits
        _scalar(1),              # count of admin seats (1 owner → below pro limit of 3)
        _scalar(owner_user),     # caller User for inviter_email
    )
    captured_token: list[str] = []

    async def _capture_email(**kwargs: Any) -> None:
        captured_token.append(kwargs["token"])

    with patch("app.routers.club_memberships.send_club_invite_email", side_effect=_capture_email):
        client = TestClient(_app(invite_db))
        resp = client.post(
            f"/api/v1/clubs/{_CLUB_UUID}/invites",
            json={"email": "admin2@gc.example", "role": "admin"},
            headers=_bearer(_OWNER_ID),
        )
    assert resp.status_code == 202
    token = captured_token[0]

    # --- 2. New admin accepts the invite ---
    # DB calls for accept_invite: get Club by db id
    accept_db = _AsyncDB(_scalar(club))
    client2 = TestClient(_app(accept_db))
    resp2 = client2.post(
        f"/api/v1/clubs/invites/{token}/accept",
        headers=_bearer(_ADMIN_ID),
    )
    assert resp2.status_code == 200
    assert resp2.json()["clubId"] == _CLUB_UUID
    assert len(accept_db.added) == 1
    assert accept_db.added[0].role == "admin"

    # --- 3. List members shows both ---
    admin2_membership = _make_membership(role="admin", user_id=_ADMIN_ID, member_id=2)
    admin2_membership.accepted_at = now
    admin2_user = _make_user(_ADMIN_ID, "admin2@gc.example")

    from unittest.mock import MagicMock

    rows_result = MagicMock()
    rows_result.all.return_value = [(owner_membership, owner_user), (admin2_membership, admin2_user)]

    list_db = _AsyncDB(
        _scalar(club),
        _scalar(owner_membership),  # caller (owner) membership check
        rows_result,
    )
    client3 = TestClient(_app(list_db))
    resp3 = client3.get(
        f"/api/v1/clubs/{_CLUB_UUID}/members",
        headers=_bearer(_OWNER_ID),
    )
    assert resp3.status_code == 200
    members = resp3.json()
    assert len(members) == 2
    roles = {m["role"] for m in members}
    assert "owner" in roles
    assert "admin" in roles

    # --- 4. Owner removes the second admin ---
    remove_db = _AsyncDB(
        _scalar(club),
        _scalar(owner_membership),   # caller (owner) membership
        _scalar(admin2_membership),  # target membership
    )
    client4 = TestClient(_app(remove_db))
    resp4 = client4.delete(
        f"/api/v1/clubs/{_CLUB_UUID}/members/{_ADMIN_ID}",
        headers=_bearer(_OWNER_ID),
    )
    assert resp4.status_code == 204
    assert remove_db.deleted == [admin2_membership]
