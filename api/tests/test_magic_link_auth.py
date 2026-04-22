"""Tests for magic-link authentication endpoints and onboarding user creation.

Covers:
  POST /auth/magic-link          — request a login email
  GET  /auth/magic-link/verify   — exchange token for JWT
  POST /auth/magic-link/verify   — same exchange via JSON body
  POST /api/onboarding/claim     — creates club_admin User row on first claim
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.magic_link import MagicLinkToken
from app.db.onboarding import ClubClaim, OnboardingSession
from app.db.users import User
from app.routers.auth import router as auth_router
from app.routers.onboarding import router as onboarding_router

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
_FUTURE = datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC)  # never expires in tests
_PAST = _NOW - timedelta(minutes=1)


# ---------------------------------------------------------------------------
# Fake DB for auth endpoints
# ---------------------------------------------------------------------------


class _AuthFakeDB:
    """Async session stub covering User and MagicLinkToken queries."""

    def __init__(
        self,
        users: list[User] | None = None,
        ml_tokens: list[MagicLinkToken] | None = None,
    ) -> None:
        self._users: dict[str, User] = {u.email: u for u in (users or [])}
        self._tokens: dict[str, MagicLinkToken] = {t.token_hash: t for t in (ml_tokens or [])}
        self.added: list[Any] = []
        self.flushed: bool = False
        self.invalidated_emails: list[str] = []

    async def execute(self, stmt: Any) -> Any:
        from sqlalchemy.sql.dml import Update as SAUpdate

        result = MagicMock()

        if isinstance(stmt, SAUpdate):
            # Simulate invalidating active tokens for an email.
            email_val = self._extract_email_from_and_clause(getattr(stmt, "whereclause", None))
            if email_val:
                self.invalidated_emails.append(email_val)
                for tok in self._tokens.values():
                    if tok.email == email_val and tok.used_at is None:
                        tok.used_at = _NOW
            return result

        where = getattr(stmt, "whereclause", None)
        if where is None:
            result.scalar_one_or_none.return_value = None
            return result

        col_name = getattr(getattr(where, "left", None), "key", None)
        value = getattr(getattr(where, "right", None), "value", None)

        if col_name == "email":
            result.scalar_one_or_none.return_value = self._users.get(value)
        elif col_name == "token_hash":
            result.scalar_one_or_none.return_value = self._tokens.get(value)
        else:
            result.scalar_one_or_none.return_value = None

        return result

    def _extract_email_from_and_clause(self, where: Any) -> str | None:
        if where is None:
            return None
        # AND clause exposes its children via .clauses
        if hasattr(where, "clauses"):
            for clause in where.clauses:
                col_name = getattr(getattr(clause, "left", None), "key", None)
                if col_name == "email":
                    return getattr(getattr(clause, "right", None), "value", None)
        col_name = getattr(getattr(where, "left", None), "key", None)
        if col_name == "email":
            return getattr(getattr(where, "right", None), "value", None)
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, MagicLinkToken):
            self._tokens[obj.token_hash] = obj
        elif isinstance(obj, User):
            self._users[obj.email] = obj

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _make_user(email: str = "alice@example.com", role: str = "user") -> User:
    u = User(email=email, password_hash="$2b$12$hashed", role=role, is_active=True)
    u.id = 42
    return u


def _make_ml_token(
    email: str,
    raw_token: str,
    expires_at: datetime = _FUTURE,
    used_at: datetime | None = None,
) -> MagicLinkToken:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return MagicLinkToken(
        email=email,
        token_hash=token_hash,
        expires_at=expires_at,
        used_at=used_at,
    )


def _make_auth_app(
    users: list[User] | None = None,
    ml_tokens: list[MagicLinkToken] | None = None,
) -> tuple[TestClient, _AuthFakeDB]:
    db = _AuthFakeDB(users=users, ml_tokens=ml_tokens)

    async def _override() -> Any:
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override
    app.include_router(auth_router)
    return TestClient(app), db


# ---------------------------------------------------------------------------
# POST /auth/magic-link — request
# ---------------------------------------------------------------------------


class TestRequestMagicLink:

    def test_200_for_known_active_user(self) -> None:
        user = _make_user()
        client, db = _make_auth_app(users=[user])
        with patch("app.routers.auth.send_magic_link_email", new_callable=AsyncMock):
            resp = client.post("/auth/magic-link", json={"email": "alice@example.com"})
        assert resp.status_code == 200
        assert "sign-in link" in resp.json()["detail"]

    def test_200_for_unknown_email_no_enumeration(self) -> None:
        client, _ = _make_auth_app(users=[])
        with patch("app.routers.auth.send_magic_link_email", new_callable=AsyncMock) as mock_email:
            resp = client.post("/auth/magic-link", json={"email": "ghost@example.com"})
        assert resp.status_code == 200
        mock_email.assert_not_called()

    def test_send_magic_link_email_called_exactly_once(self) -> None:
        user = _make_user()
        client, _ = _make_auth_app(users=[user])
        with patch("app.routers.auth.send_magic_link_email", new_callable=AsyncMock) as mock_email:
            client.post("/auth/magic-link", json={"email": "alice@example.com"})
        mock_email.assert_called_once()

    def test_token_stored_in_db(self) -> None:
        user = _make_user()
        client, db = _make_auth_app(users=[user])
        with patch("app.routers.auth.send_magic_link_email", new_callable=AsyncMock):
            client.post("/auth/magic-link", json={"email": "alice@example.com"})
        added_tokens = [x for x in db.added if isinstance(x, MagicLinkToken)]
        assert len(added_tokens) == 1
        assert added_tokens[0].email == "alice@example.com"
        assert added_tokens[0].used_at is None

    def test_second_request_invalidates_previous_token(self) -> None:
        user = _make_user()
        captured_tokens: list[str] = []

        async def _capture_email(*, to: str, token: str, base_url: str | None = None) -> None:
            captured_tokens.append(token)

        client, db = _make_auth_app(users=[user])
        with patch("app.routers.auth.send_magic_link_email", side_effect=_capture_email):
            client.post("/auth/magic-link", json={"email": "alice@example.com"})
            client.post("/auth/magic-link", json={"email": "alice@example.com"})

        assert len(captured_tokens) == 2
        # First token should be invalidated
        first_hash = hashlib.sha256(captured_tokens[0].encode()).hexdigest()
        first_token_row = db._tokens[first_hash]
        assert first_token_row.used_at is not None

        # Second token should still be active
        second_hash = hashlib.sha256(captured_tokens[1].encode()).hexdigest()
        second_token_row = db._tokens[second_hash]
        assert second_token_row.used_at is None

    def test_inactive_user_gets_no_email(self) -> None:
        user = _make_user()
        user.is_active = False
        client, _ = _make_auth_app(users=[user])
        with patch("app.routers.auth.send_magic_link_email", new_callable=AsyncMock) as mock_email:
            resp = client.post("/auth/magic-link", json={"email": "alice@example.com"})
        assert resp.status_code == 200
        mock_email.assert_not_called()

    def test_integration_email_sent_via_mocked_smtp(self) -> None:
        """Confirm the email pipeline is exercised (mocked at the SMTP layer)."""
        user = _make_user()
        client, _ = _make_auth_app(users=[user])
        with (
            patch("app.services.email.settings") as mock_cfg,
            patch("app.services.email._send_smtp", new_callable=AsyncMock) as mock_smtp,
        ):
            mock_cfg.email_backend = "smtp"
            mock_cfg.frontend_url = "http://localhost:3000"
            mock_cfg.mail_from = "noreply@test.com"
            client.post("/auth/magic-link", json={"email": "alice@example.com"})
        mock_smtp.assert_called_once()


# ---------------------------------------------------------------------------
# GET /auth/magic-link/verify — exchange token for JWT
# ---------------------------------------------------------------------------


class TestVerifyMagicLinkGet:

    def test_200_valid_token_returns_jwt(self) -> None:
        user = _make_user()
        ml = _make_ml_token(email=user.email, raw_token="good_token")
        client, _ = _make_auth_app(users=[user], ml_tokens=[ml])
        resp = client.get("/auth/magic-link/verify", params={"token": "good_token"})
        assert resp.status_code == 200
        body = resp.json()
        assert "accessToken" in body
        assert body["role"] == user.role

    def test_jwt_contains_correct_user_id_and_role(self) -> None:
        import jwt as pyjwt
        from app.config import settings

        user = _make_user(role="club_admin")
        ml = _make_ml_token(email=user.email, raw_token="tok_role")
        client, _ = _make_auth_app(users=[user], ml_tokens=[ml])
        resp = client.get("/auth/magic-link/verify", params={"token": "tok_role"})
        assert resp.status_code == 200
        raw_jwt = resp.json()["accessToken"]
        payload = pyjwt.decode(raw_jwt, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert int(payload["sub"]) == user.id
        assert payload["role"] == "club_admin"

    def test_401_for_unknown_token(self) -> None:
        client, _ = _make_auth_app()
        resp = client.get("/auth/magic-link/verify", params={"token": "nonexistent"})
        assert resp.status_code == 401

    def test_401_for_already_used_token(self) -> None:
        user = _make_user()
        ml = _make_ml_token(email=user.email, raw_token="used_tok", used_at=_NOW)
        client, _ = _make_auth_app(users=[user], ml_tokens=[ml])
        resp = client.get("/auth/magic-link/verify", params={"token": "used_tok"})
        assert resp.status_code == 401

    def test_401_for_expired_token(self) -> None:
        user = _make_user()
        ml = _make_ml_token(email=user.email, raw_token="exp_tok", expires_at=_PAST)
        client, _ = _make_auth_app(users=[user], ml_tokens=[ml])
        resp = client.get("/auth/magic-link/verify", params={"token": "exp_tok"})
        assert resp.status_code == 401

    def test_token_marked_used_after_exchange(self) -> None:
        user = _make_user()
        ml = _make_ml_token(email=user.email, raw_token="mark_tok")
        client, db = _make_auth_app(users=[user], ml_tokens=[ml])
        client.get("/auth/magic-link/verify", params={"token": "mark_tok"})
        token_hash = hashlib.sha256(b"mark_tok").hexdigest()
        assert db._tokens[token_hash].used_at is not None

    def test_second_verify_with_same_token_returns_401(self) -> None:
        user = _make_user()
        ml = _make_ml_token(email=user.email, raw_token="once_tok")
        client, _ = _make_auth_app(users=[user], ml_tokens=[ml])
        resp1 = client.get("/auth/magic-link/verify", params={"token": "once_tok"})
        assert resp1.status_code == 200
        resp2 = client.get("/auth/magic-link/verify", params={"token": "once_tok"})
        assert resp2.status_code == 401

    def test_second_request_old_token_returns_401(self) -> None:
        """Old token (invalidated by second magic-link request) returns 401."""
        user = _make_user()
        captured: list[str] = []

        async def _capture(*, to: str, token: str, base_url: str | None = None) -> None:
            captured.append(token)

        client, _ = _make_auth_app(users=[user])
        with patch("app.routers.auth.send_magic_link_email", side_effect=_capture):
            client.post("/auth/magic-link", json={"email": user.email})
            client.post("/auth/magic-link", json={"email": user.email})

        old_token = captured[0]
        resp = client.get("/auth/magic-link/verify", params={"token": old_token})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/magic-link/verify — JSON body (backwards-compat)
# ---------------------------------------------------------------------------


class TestVerifyMagicLinkPost:

    def test_200_valid_token_returns_jwt(self) -> None:
        user = _make_user()
        ml = _make_ml_token(email=user.email, raw_token="post_tok")
        client, _ = _make_auth_app(users=[user], ml_tokens=[ml])
        resp = client.post("/auth/magic-link/verify", json={"token": "post_tok"})
        assert resp.status_code == 200
        assert "accessToken" in resp.json()

    def test_401_for_expired_token(self) -> None:
        user = _make_user()
        ml = _make_ml_token(email=user.email, raw_token="exp_post", expires_at=_PAST)
        client, _ = _make_auth_app(users=[user], ml_tokens=[ml])
        resp = client.post("/auth/magic-link/verify", json={"token": "exp_post"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/onboarding/claim — creates club_admin User
# ---------------------------------------------------------------------------


class _ClaimFakeDB:
    """FakeDB that handles OnboardingSession, ClubClaim, and User lookups."""

    def __init__(
        self,
        sessions: list[OnboardingSession] | None = None,
        claims: list[ClubClaim] | None = None,
        users: list[User] | None = None,
    ) -> None:
        self._sessions: dict[str, OnboardingSession] = {
            s.claim_token: s for s in (sessions or []) if s.claim_token
        }
        self._claims: dict[str, ClubClaim] = {
            c.claim_id: c for c in (claims or [])
        }
        self._users: dict[str, User] = {u.email: u for u in (users or [])}
        self.added: list[Any] = []
        self.flushed: bool = False

    async def execute(self, stmt: Any) -> Any:
        result = MagicMock()
        where = getattr(stmt, "whereclause", None)

        if where is None:
            result.scalar_one_or_none.return_value = None
            return result

        col_name = getattr(getattr(where, "left", None), "key", None)
        value = getattr(getattr(where, "right", None), "value", None)

        if col_name == "claim_token":
            result.scalar_one_or_none.return_value = self._sessions.get(value)
        elif col_name == "claim_id":
            result.scalar_one_or_none.return_value = self._claims.get(value)
        elif col_name == "email":
            result.scalar_one_or_none.return_value = self._users.get(value)
        else:
            result.scalar_one_or_none.return_value = None

        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, User):
            self._users[obj.email] = obj

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _make_paid_session(claim_id: str = "claim_001") -> OnboardingSession:
    return OnboardingSession(
        session_token="sess_paid",
        claim_token="clm_paid",
        claim_id=claim_id,
        stripe_checkout_session_id="cs_test_paid",
        plan_id="price_pro",
        status="paid",
        expires_at=_FUTURE,
    )


def _make_club_claim(claim_id: str = "claim_001", email: str = "pro@club.example") -> ClubClaim:
    return ClubClaim(
        claim_id=claim_id,
        club_name="Pebble Beach GC",
        contact_email=email,
    )


class TestClaimCreatesUser:

    def test_claim_creates_club_admin_user(self) -> None:
        session = _make_paid_session()
        claim = _make_club_claim()
        db = _ClaimFakeDB(sessions=[session], claims=[claim])

        async def _override() -> Any:
            yield db

        app = FastAPI()
        app.dependency_overrides[get_db] = _override
        app.include_router(onboarding_router)
        client = TestClient(app)

        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_paid"})
        assert resp.status_code == 200

        added_users = [x for x in db.added if isinstance(x, User)]
        assert len(added_users) == 1
        user = added_users[0]
        assert user.email == "pro@club.example"
        assert user.role == "club_admin"
        assert user.is_active is True
        assert user.password_hash is None

    def test_claim_skips_user_creation_if_email_already_registered(self) -> None:
        session = _make_paid_session()
        claim = _make_club_claim(email="existing@club.example")
        existing_user = _make_user(email="existing@club.example")
        db = _ClaimFakeDB(sessions=[session], claims=[claim], users=[existing_user])

        async def _override() -> Any:
            yield db

        app = FastAPI()
        app.dependency_overrides[get_db] = _override
        app.include_router(onboarding_router)
        client = TestClient(app)

        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_paid"})
        assert resp.status_code == 200

        added_users = [x for x in db.added if isinstance(x, User)]
        assert len(added_users) == 0

    def test_claim_succeeds_even_if_no_club_claim_found(self) -> None:
        """Session without a matching ClubClaim still transitions to claimed."""
        session = _make_paid_session(claim_id="claim_missing")
        db = _ClaimFakeDB(sessions=[session], claims=[])

        async def _override() -> Any:
            yield db

        app = FastAPI()
        app.dependency_overrides[get_db] = _override
        app.include_router(onboarding_router)
        client = TestClient(app)

        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_paid"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "claimed"
