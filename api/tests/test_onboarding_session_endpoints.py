"""Tests for GET /api/onboarding/session/{session_token} and POST /api/onboarding/claim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.onboarding import OnboardingSession
from app.routers.onboarding import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)
_FUTURE = _NOW + timedelta(hours=23)
_PAST = _NOW - timedelta(seconds=1)


def _make_session(
    session_token: str = "sess_abc",
    claim_token: str = "clm_xyz",
    status: str = "pending",
    expires_at: datetime | None = None,
) -> OnboardingSession:
    s = OnboardingSession(
        session_token=session_token,
        claim_token=claim_token,
        claim_id="claim_001",
        stripe_checkout_session_id="cs_test_001",
        plan_id="price_pro",
        status=status,
        expires_at=expires_at if expires_at is not None else _FUTURE,
    )
    return s


class _FakeDB:
    """Minimal async session stub."""

    def __init__(self, sessions: list[OnboardingSession] | None = None) -> None:
        self._by_session_token: dict[str, OnboardingSession] = {}
        self._by_claim_token: dict[str, OnboardingSession] = {}
        self.flushed = False
        for s in sessions or []:
            if s.session_token:
                self._by_session_token[s.session_token] = s
            if s.claim_token:
                self._by_claim_token[s.claim_token] = s

    async def execute(self, stmt: Any) -> Any:
        # Inspect the WHERE clause to find which column/value is being queried.
        where = getattr(stmt, "whereclause", None)
        result = MagicMock()
        if where is not None:
            col_name = getattr(getattr(where, "left", None), "key", None)
            value = getattr(getattr(where, "right", None), "value", None)
            if col_name == "session_token":
                result.scalar_one_or_none.return_value = self._by_session_token.get(value)
            elif col_name == "claim_token":
                result.scalar_one_or_none.return_value = self._by_claim_token.get(value)
            else:
                result.scalar_one_or_none.return_value = None
        else:
            result.scalar_one_or_none.return_value = None
        return result

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _make_app(sessions: list[OnboardingSession] | None = None) -> tuple[TestClient, _FakeDB]:
    db = _FakeDB(sessions=sessions)

    async def _override() -> Any:
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override
    app.include_router(router)
    return TestClient(app), db


# ---------------------------------------------------------------------------
# GET /api/onboarding/session/{session_token}
# ---------------------------------------------------------------------------


class TestGetSessionStatus:

    def test_200_returns_status_for_pending_session(self) -> None:
        sess = _make_session(status="pending")
        client, _ = _make_app([sess])
        resp = client.get("/api/onboarding/session/sess_abc")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert body["sessionToken"] == "sess_abc"

    def test_200_returns_status_for_paid_session(self) -> None:
        sess = _make_session(status="paid")
        client, _ = _make_app([sess])
        resp = client.get("/api/onboarding/session/sess_abc")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paid"

    def test_404_for_unknown_token(self) -> None:
        client, _ = _make_app([])
        resp = client.get("/api/onboarding/session/sess_unknown")
        assert resp.status_code == 404

    def test_410_for_explicitly_expired_session(self) -> None:
        sess = _make_session(status="expired")
        client, _ = _make_app([sess])
        resp = client.get("/api/onboarding/session/sess_abc")
        assert resp.status_code == 410

    def test_410_for_ttl_expired_session(self) -> None:
        sess = _make_session(status="pending", expires_at=_PAST)
        client, _ = _make_app([sess])
        resp = client.get("/api/onboarding/session/sess_abc")
        assert resp.status_code == 410

    def test_200_for_claimed_session_within_ttl(self) -> None:
        sess = _make_session(status="claimed")
        client, _ = _make_app([sess])
        resp = client.get("/api/onboarding/session/sess_abc")
        assert resp.status_code == 200
        assert resp.json()["status"] == "claimed"


# ---------------------------------------------------------------------------
# POST /api/onboarding/claim
# ---------------------------------------------------------------------------


class TestClaimSession:

    def test_200_transitions_paid_to_claimed(self) -> None:
        sess = _make_session(status="paid")
        client, db = _make_app([sess])
        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_xyz"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "claimed"
        assert body["sessionToken"] == "sess_abc"
        assert db.flushed is True
        assert sess.status == "claimed"

    def test_404_for_unknown_claim_token(self) -> None:
        client, _ = _make_app([])
        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_notfound"})
        assert resp.status_code == 404

    def test_409_for_already_claimed_session(self) -> None:
        sess = _make_session(status="claimed")
        client, _ = _make_app([sess])
        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_xyz"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "already_claimed"

    def test_409_second_concurrent_claim(self) -> None:
        """Simulate what the second concurrent caller sees after first has claimed."""
        sess = _make_session(status="paid")
        client, db = _make_app([sess])

        # First claim
        resp1 = client.post("/api/onboarding/claim", json={"claimToken": "clm_xyz"})
        assert resp1.status_code == 200

        # Second claim with same token — session.status is now 'claimed' in memory
        resp2 = client.post("/api/onboarding/claim", json={"claimToken": "clm_xyz"})
        assert resp2.status_code == 409

    def test_410_for_expired_session(self) -> None:
        sess = _make_session(status="paid", expires_at=_PAST)
        client, _ = _make_app([sess])
        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_xyz"})
        assert resp.status_code == 410

    def test_422_for_pending_session(self) -> None:
        sess = _make_session(status="pending")
        client, _ = _make_app([sess])
        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_xyz"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["error"] == "invalid_transition"

    def test_422_missing_claim_token_body(self) -> None:
        client, _ = _make_app([])
        resp = client.post("/api/onboarding/claim", json={})
        assert resp.status_code == 422

    def test_410_for_explicitly_expired_status(self) -> None:
        sess = _make_session(status="expired")
        client, _ = _make_app([sess])
        resp = client.post("/api/onboarding/claim", json={"claimToken": "clm_xyz"})
        assert resp.status_code == 410
