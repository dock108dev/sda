"""Integration tests for POST /api/v1/commerce/checkout.

Mocks the Stripe SDK to verify endpoint behaviour without live network calls.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.onboarding import ClubClaim, OnboardingSession
from app.routers.commerce import router


_FROZEN_TS = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

_FAKE_CUSTOMER_ID = "cus_test123"
_FAKE_CHECKOUT_SESSION_ID = "cs_test_abc"
_FAKE_CHECKOUT_URL = "https://checkout.stripe.com/pay/cs_test_abc"
_TEST_STRIPE_KEY = "sk_test_fakekeyfortests"


class _FakeSession:
    """Minimal async session that tracks added objects."""

    def __init__(self, claims: list[ClubClaim] | None = None) -> None:
        self._claims = {c.claim_id: c for c in (claims or [])}
        self.added: list[Any] = []
        self.flushed = False

    async def execute(self, stmt: Any) -> Any:
        # Extract the claim_id filter from the WHERE clause value
        # We look at compiled params or traverse the clause.
        # Simpler: inspect the statement's whereclause for the value.
        from sqlalchemy import inspect as sa_inspect

        where = stmt.whereclause
        # The value is the right-hand side of the BinaryExpression
        claim_id = where.right.value if where is not None else None
        claim = self._claims.get(claim_id)

        result = MagicMock()
        result.scalar_one_or_none.return_value = claim
        return result

    def add(self, obj: Any) -> None:
        if isinstance(obj, OnboardingSession):
            obj.created_at = _FROZEN_TS
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _make_claim(claim_id: str = "claim_abc123", status: str = "new") -> ClubClaim:
    claim = ClubClaim(
        claim_id=claim_id,
        club_name="Pebble Beach GC",
        contact_email="pro@pebble.example",
        status=status,
    )
    return claim


def _make_app(claims: list[ClubClaim] | None = None) -> tuple[TestClient, _FakeSession]:
    sess = _FakeSession(claims=claims)

    async def _get_db_override() -> Any:
        yield sess

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_db_override
    app.include_router(router)
    return TestClient(app), sess


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "planId": "price_monthly_pro",
        "clubClaimId": "claim_abc123",
    }
    payload.update(overrides)
    return payload


def _mock_stripe_customer_search(found: bool = False) -> MagicMock:
    result = MagicMock()
    result.data = [SimpleNamespace(id=_FAKE_CUSTOMER_ID)] if found else []
    return result


def _mock_checkout_session() -> MagicMock:
    sess = MagicMock()
    sess.id = _FAKE_CHECKOUT_SESSION_ID
    sess.url = _FAKE_CHECKOUT_URL
    return sess


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCreateCheckoutSessionHappyPath:

    def test_201_creates_new_customer_and_returns_checkout_url(self) -> None:
        claim = _make_claim()
        client, db_sess = _make_app(claims=[claim])

        with (
            patch("app.routers.commerce.settings") as mock_settings,
            patch("stripe.Customer.search", return_value=_mock_stripe_customer_search(found=False)),
            patch("stripe.Customer.create", return_value=SimpleNamespace(id=_FAKE_CUSTOMER_ID)),
            patch(
                "stripe.checkout.Session.create",
                return_value=_mock_checkout_session(),
            ),
        ):
            mock_settings.stripe_secret_key = _TEST_STRIPE_KEY
            mock_settings.stripe_checkout_success_url = "https://example.com/success"
            mock_settings.stripe_checkout_cancel_url = "https://example.com/cancel"

            resp = client.post("/api/v1/commerce/checkout", json=_valid_payload())

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["checkoutUrl"] == _FAKE_CHECKOUT_URL
        assert re.match(r"^sess_[\w-]{40,}$", body["sessionToken"])

    def test_reuses_existing_stripe_customer(self) -> None:
        claim = _make_claim()
        client, db_sess = _make_app(claims=[claim])

        create_mock = MagicMock()
        with (
            patch("app.routers.commerce.settings") as mock_settings,
            patch(
                "stripe.Customer.search",
                return_value=_mock_stripe_customer_search(found=True),
            ),
            patch("stripe.Customer.create", create_mock),
            patch(
                "stripe.checkout.Session.create",
                return_value=_mock_checkout_session(),
            ),
        ):
            mock_settings.stripe_secret_key = _TEST_STRIPE_KEY
            mock_settings.stripe_checkout_success_url = "https://example.com/success"
            mock_settings.stripe_checkout_cancel_url = "https://example.com/cancel"

            resp = client.post("/api/v1/commerce/checkout", json=_valid_payload())

        assert resp.status_code == 201
        # Customer.create must NOT be called when customer already exists
        create_mock.assert_not_called()

    def test_onboarding_session_row_stored(self) -> None:
        claim = _make_claim()
        client, db_sess = _make_app(claims=[claim])

        with (
            patch("app.routers.commerce.settings") as mock_settings,
            patch("stripe.Customer.search", return_value=_mock_stripe_customer_search()),
            patch("stripe.Customer.create", return_value=SimpleNamespace(id=_FAKE_CUSTOMER_ID)),
            patch(
                "stripe.checkout.Session.create",
                return_value=_mock_checkout_session(),
            ),
        ):
            mock_settings.stripe_secret_key = _TEST_STRIPE_KEY
            mock_settings.stripe_checkout_success_url = "https://example.com/success"
            mock_settings.stripe_checkout_cancel_url = "https://example.com/cancel"

            resp = client.post("/api/v1/commerce/checkout", json=_valid_payload())

        assert resp.status_code == 201
        assert db_sess.flushed is True
        sessions = [o for o in db_sess.added if isinstance(o, OnboardingSession)]
        assert len(sessions) == 1
        s = sessions[0]
        assert s.claim_id == "claim_abc123"
        assert s.stripe_checkout_session_id == _FAKE_CHECKOUT_SESSION_ID
        assert s.plan_id == "price_monthly_pro"
        assert s.status == "pending"
        # session_token must match what was returned in response
        body = resp.json()
        assert s.session_token == body["sessionToken"]

    def test_checkout_idempotency_key_matches_claim_and_plan(self) -> None:
        claim = _make_claim()
        client, _ = _make_app(claims=[claim])

        create_session_mock = MagicMock(return_value=_mock_checkout_session())
        with (
            patch("app.routers.commerce.settings") as mock_settings,
            patch("stripe.Customer.search", return_value=_mock_stripe_customer_search()),
            patch("stripe.Customer.create", return_value=SimpleNamespace(id=_FAKE_CUSTOMER_ID)),
            patch("stripe.checkout.Session.create", create_session_mock),
        ):
            mock_settings.stripe_secret_key = _TEST_STRIPE_KEY
            mock_settings.stripe_checkout_success_url = "https://example.com/success"
            mock_settings.stripe_checkout_cancel_url = "https://example.com/cancel"

            client.post("/api/v1/commerce/checkout", json=_valid_payload())

        _, kwargs = create_session_mock.call_args
        assert kwargs.get("idempotency_key") == "claim_abc123:price_monthly_pro"


# ---------------------------------------------------------------------------
# 400 error cases
# ---------------------------------------------------------------------------


class TestCreateCheckoutSession400:

    def test_missing_claim_returns_400(self) -> None:
        client, _ = _make_app(claims=[])  # no claims in DB

        with patch("app.routers.commerce.settings") as mock_settings:
            mock_settings.stripe_secret_key = _TEST_STRIPE_KEY

            resp = client.post("/api/v1/commerce/checkout", json=_valid_payload())

        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_claim"

    def test_claim_with_non_new_status_returns_400(self) -> None:
        claim = _make_claim(status="processed")
        client, _ = _make_app(claims=[claim])

        with patch("app.routers.commerce.settings") as mock_settings:
            mock_settings.stripe_secret_key = _TEST_STRIPE_KEY

            resp = client.post("/api/v1/commerce/checkout", json=_valid_payload())

        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_claim"

    def test_claim_cancelled_status_returns_400(self) -> None:
        claim = _make_claim(status="cancelled")
        client, _ = _make_app(claims=[claim])

        with patch("app.routers.commerce.settings") as mock_settings:
            mock_settings.stripe_secret_key = _TEST_STRIPE_KEY

            resp = client.post(
                "/api/v1/commerce/checkout",
                json=_valid_payload(clubClaimId="claim_abc123"),
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 503 error cases
# ---------------------------------------------------------------------------


class TestCreateCheckoutSession503:

    def test_missing_stripe_key_returns_503(self) -> None:
        claim = _make_claim()
        client, _ = _make_app(claims=[claim])

        with patch("app.routers.commerce.settings") as mock_settings:
            mock_settings.stripe_secret_key = None

            resp = client.post("/api/v1/commerce/checkout", json=_valid_payload())

        assert resp.status_code == 503
        assert resp.json()["detail"]["error"] == "stripe_unavailable"

    def test_stripe_auth_error_returns_503(self) -> None:
        import stripe

        claim = _make_claim()
        client, _ = _make_app(claims=[claim])

        with (
            patch("app.routers.commerce.settings") as mock_settings,
            patch(
                "stripe.Customer.search",
                side_effect=stripe.AuthenticationError("bad key"),
            ),
        ):
            mock_settings.stripe_secret_key = "sk_test_invalid"
            mock_settings.stripe_checkout_success_url = "https://example.com/success"
            mock_settings.stripe_checkout_cancel_url = "https://example.com/cancel"

            resp = client.post("/api/v1/commerce/checkout", json=_valid_payload())

        assert resp.status_code == 503
        assert resp.json()["detail"]["error"] == "stripe_unavailable"


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


class TestCheckoutRequestValidation:

    def test_missing_plan_id_returns_422(self) -> None:
        client, _ = _make_app()
        resp = client.post(
            "/api/v1/commerce/checkout",
            json={"clubClaimId": "claim_abc123"},
        )
        assert resp.status_code == 422

    def test_missing_club_claim_id_returns_422(self) -> None:
        client, _ = _make_app()
        resp = client.post(
            "/api/v1/commerce/checkout",
            json={"planId": "price_pro"},
        )
        assert resp.status_code == 422
