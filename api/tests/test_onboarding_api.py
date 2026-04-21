"""Tests for public onboarding endpoints.

POST /api/onboarding/club-claims — prospect-facing "claim your club" form.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.onboarding import ClubClaim
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers.onboarding import router


_FROZEN_TS = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)


class _FakeSession:
    """Minimal async session stand-in that records adds + simulates commit.

    Mirrors enough of AsyncSession to exercise the happy path of
    ``submit_club_claim``. On ``add`` we capture the ORM instance; on
    ``flush``/``refresh`` we stamp ``received_at`` so the response has a
    real datetime to serialize.
    """

    def __init__(self) -> None:
        self.added: list[ClubClaim] = []
        self.committed = False

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "received_at", None) is None:
                obj.received_at = _FROZEN_TS

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:  # pragma: no cover — defensive
        pass

    async def close(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "received_at", None) is None:
            obj.received_at = _FROZEN_TS


def _make_app(session: _FakeSession | None = None) -> tuple[TestClient, _FakeSession]:
    sess = session or _FakeSession()

    async def _get_db_override():
        yield sess

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    app.dependency_overrides[get_db] = _get_db_override
    app.include_router(router)
    return TestClient(app), sess


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    """Build a camelCase request body — matches the frontend's wire format."""
    payload = {
        "clubName": "Pine Valley GC",
        "contactEmail": "pro@pv.example",
        "expectedEntries": 40,
        "notes": "for Masters 2027",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestSubmitClubClaimHappyPath:

    def test_201_and_response_shape(self) -> None:
        client, sess = _make_app()
        with patch(
            "app.routers.onboarding.send_email", new=AsyncMock()
        ):
            resp = client.post(
                "/api/onboarding/club-claims", json=_valid_payload()
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # Project convention: responses are camelCase on the wire.
        assert re.match(r"^claim_[\w-]{6,12}$", body["claimId"])
        assert body["receivedAt"]
        assert "claim_id" not in body
        assert "received_at" not in body
        assert sess.committed is True
        assert len(sess.added) == 1
        row = sess.added[0]
        assert row.club_name == "Pine Valley GC"
        assert row.contact_email == "pro@pv.example"
        assert row.expected_entries == 40
        assert row.notes == "for Masters 2027"
        assert row.claim_id == body["claimId"]

    def test_trims_and_lowercases(self) -> None:
        client, sess = _make_app()
        payload = _valid_payload(
            clubName="  Pine Valley GC  ",
            contactEmail="PRO@PV.EXAMPLE",
            notes="   keep me   ",
        )
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post("/api/onboarding/club-claims", json=payload)
        assert resp.status_code == 201, resp.text
        row = sess.added[0]
        assert row.club_name == "Pine Valley GC"
        assert row.contact_email == "pro@pv.example"
        assert row.notes == "keep me"

    def test_no_api_key_header_required(self) -> None:
        """Regression guard: endpoint must be publicly reachable."""
        client, _ = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json=_valid_payload(),
                # intentionally no X-API-Key / Authorization header
            )
        assert resp.status_code == 201
        assert resp.status_code != 401

    def test_captures_ip_and_user_agent(self) -> None:
        client, sess = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json=_valid_payload(),
                headers={
                    "X-Forwarded-For": "203.0.113.7, 10.0.0.1",
                    "User-Agent": "TestAgent/1.0",
                },
            )
        assert resp.status_code == 201, resp.text
        row = sess.added[0]
        assert row.source_ip == "203.0.113.7"
        assert row.user_agent == "TestAgent/1.0"

    def test_user_agent_truncated_to_500(self) -> None:
        client, sess = _make_app()
        long_ua = "x" * 1000
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json=_valid_payload(),
                headers={"User-Agent": long_ua},
            )
        assert resp.status_code == 201
        assert len(sess.added[0].user_agent or "") == 500


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestSubmitClubClaimValidation:

    def test_missing_club_name_is_422(self) -> None:
        client, _ = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json={"contactEmail": "pro@pv.example"},
            )
        assert resp.status_code == 422

    def test_empty_club_name_is_422(self) -> None:
        client, _ = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json=_valid_payload(clubName=""),
            )
        assert resp.status_code == 422

    def test_invalid_email_is_422(self) -> None:
        client, _ = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json=_valid_payload(contactEmail="not-an-email"),
            )
        assert resp.status_code == 422

    def test_negative_expected_entries_is_422(self) -> None:
        client, _ = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json=_valid_payload(expectedEntries=-1),
            )
        assert resp.status_code == 422

    def test_notes_over_2000_chars_is_422(self) -> None:
        client, _ = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            resp = client.post(
                "/api/onboarding/club-claims",
                json=_valid_payload(notes="x" * 2001),
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Email notification branches
# ---------------------------------------------------------------------------

class TestClubClaimNotification:

    def test_email_failure_is_non_fatal(self) -> None:
        client, sess = _make_app()
        boom = AsyncMock(side_effect=RuntimeError("email provider down"))
        with patch("app.routers.onboarding.settings") as mock_settings, \
             patch("app.routers.onboarding.send_email", new=boom):
            mock_settings.onboarding_notification_email = "ops@example.com"
            resp = client.post(
                "/api/onboarding/club-claims", json=_valid_payload()
            )
        assert resp.status_code == 201, resp.text
        assert len(sess.added) == 1
        assert sess.committed is True

    def test_email_sent_when_recipient_configured(self) -> None:
        client, _ = _make_app()
        sender = AsyncMock()
        with patch("app.routers.onboarding.settings") as mock_settings, \
             patch("app.routers.onboarding.send_email", new=sender):
            mock_settings.onboarding_notification_email = "ops@example.com"
            resp = client.post(
                "/api/onboarding/club-claims", json=_valid_payload()
            )
        assert resp.status_code == 201
        sender.assert_awaited_once()
        kwargs = sender.await_args.kwargs
        assert kwargs["to"] == "ops@example.com"
        assert "Pine Valley GC" in kwargs["subject"]
        assert "pro@pv.example" in kwargs["html"]

    def test_email_skipped_when_recipient_unset(self) -> None:
        client, _ = _make_app()
        sender = AsyncMock()
        with patch("app.routers.onboarding.settings") as mock_settings, \
             patch("app.routers.onboarding.send_email", new=sender):
            mock_settings.onboarding_notification_email = None
            resp = client.post(
                "/api/onboarding/club-claims", json=_valid_payload()
            )
        assert resp.status_code == 201
        sender.assert_not_awaited()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestClubClaimRateLimit:

    def test_sixth_request_in_window_is_429(self) -> None:
        client, _ = _make_app()
        with patch("app.routers.onboarding.send_email", new=AsyncMock()):
            for i in range(5):
                resp = client.post(
                    "/api/onboarding/club-claims", json=_valid_payload()
                )
                assert resp.status_code == 201, (i, resp.text)

            resp = client.post(
                "/api/onboarding/club-claims", json=_valid_payload()
            )
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


# ---------------------------------------------------------------------------
# Smoke: ORM model registered
# ---------------------------------------------------------------------------

def test_club_claim_model_registered() -> None:
    """Sanity check — ensures Alembic autogenerate sees the table."""
    assert ClubClaim.__tablename__ == "club_claims"
    cols = {c.name for c in ClubClaim.__table__.columns}
    assert {
        "id",
        "claim_id",
        "club_name",
        "contact_email",
        "expected_entries",
        "notes",
        "status",
        "received_at",
        "source_ip",
        "user_agent",
    } <= cols


@pytest.fixture(autouse=True)
def _reset_rate_limit_state() -> None:
    """Ensure each test starts with a clean in-memory rate-limit state.

    The middleware stores its buckets on the instance, but we build a new
    app/middleware per test via _make_app, so this is a no-op hook — kept
    explicit in case a future change shares middleware state across tests.
    """
    yield
