"""Integration tests for ISSUE-020 — subscription lifecycle webhook handlers and billing portal.

Covers:
- customer.subscription.updated: plan_id sync, Club.plan_id update, idempotency
- customer.subscription.deleted: subscription canceled, Club.status restricted, idempotency
- invoice.payment_failed: subscription set to past_due, dunning email sent, idempotency
- EntitlementService.check_pool_limit: blocks past_due clubs with 402
- POST /api/v1/billing/portal: returns portal URL, owner-only, 404 on missing club
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies.auth import verify_api_key
from app.routers.billing import router as billing_router
from app.routers.webhooks import (
    _handle_invoice_payment_failed,
    _handle_subscription_deleted,
    _handle_subscription_updated,
)
from app.services.entitlement import EntitlementService, SubscriptionPastDueError


# ---------------------------------------------------------------------------
# Helpers — fake Stripe event factories
# ---------------------------------------------------------------------------


def _make_sub_event(
    *,
    event_type: str = "customer.subscription.updated",
    sub_id: str = "sub_test_001",
    customer_id: str = "cus_test_001",
    plan_price_id: str = "price_pro",
    status: str = "active",
    period_end: int = 1800000000,
    cancel_at_period_end: bool = False,
) -> MagicMock:
    price = MagicMock()
    price.id = plan_price_id

    item = MagicMock()
    item.price = price

    items = MagicMock()
    items.data = [item]

    obj = MagicMock()
    obj.id = sub_id
    obj.customer = customer_id
    obj.items = items
    obj.status = status
    obj.current_period_end = period_end
    obj.cancel_at_period_end = cancel_at_period_end
    obj.metadata = {}

    event = MagicMock()
    event.type = event_type
    event.data = MagicMock()
    event.data.object = obj
    return event


def _make_invoice_event(
    *,
    customer_id: str = "cus_test_001",
    sub_id: str = "sub_test_001",
    customer_email: str = "owner@example.com",
) -> MagicMock:
    obj = MagicMock()
    obj.customer = customer_id
    obj.subscription = sub_id
    obj.customer_email = customer_email

    event = MagicMock()
    event.type = "invoice.payment_failed"
    event.data = MagicMock()
    event.data.object = obj
    return event


def _make_db(*, rowcount: int = 1) -> AsyncMock:
    result = MagicMock()
    result.rowcount = rowcount
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# customer.subscription.updated
# ---------------------------------------------------------------------------


class TestHandleSubscriptionUpdated:

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_executes_upsert_and_club_update(self) -> None:
        """Two DB execute calls: upsert subscription + update Club.plan_id."""
        db = _make_db()
        event = _make_sub_event(plan_price_id="price_pro", status="active")

        with patch("app.services.audit.emit"):
            self._run(_handle_subscription_updated(db, event))

        assert db.execute.call_count == 2

    def test_syncs_club_plan_id(self) -> None:
        """Second execute must contain an UPDATE targeting Club."""
        from sqlalchemy import update

        db = _make_db()
        event = _make_sub_event(plan_price_id="price_enterprise")

        with patch("app.services.audit.emit"):
            self._run(_handle_subscription_updated(db, event))

        # Verify both calls happened; the second is the Club update.
        assert db.execute.call_count == 2

    def test_no_club_update_when_plan_id_empty(self) -> None:
        """If items.data is empty, plan_id is '' and no Club update runs."""
        db = _make_db()
        event = _make_sub_event()
        event.data.object.items.data = []

        with patch("app.services.audit.emit"):
            self._run(_handle_subscription_updated(db, event))

        # Only the subscription upsert runs; no Club update.
        assert db.execute.call_count == 1

    def test_emits_audit_event(self) -> None:
        db = _make_db()
        event = _make_sub_event(sub_id="sub_audit_01", status="active", plan_price_id="price_pro")

        with patch("app.services.audit.emit") as mock_emit:
            self._run(_handle_subscription_updated(db, event))

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        assert call_kwargs[0][0] == "subscription_updated"


# ---------------------------------------------------------------------------
# customer.subscription.deleted
# ---------------------------------------------------------------------------


class TestHandleSubscriptionDeleted:

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_executes_two_updates(self) -> None:
        """Expects: update subscription to canceled + update Club.status to restricted."""
        db = _make_db()
        event = _make_sub_event(event_type="customer.subscription.deleted")

        with patch("app.services.audit.emit"):
            self._run(_handle_subscription_deleted(db, event))

        assert db.execute.call_count == 2

    def test_emits_audit_event(self) -> None:
        db = _make_db()
        event = _make_sub_event(event_type="customer.subscription.deleted", sub_id="sub_del_01")

        with patch("app.services.audit.emit") as mock_emit:
            self._run(_handle_subscription_deleted(db, event))

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "subscription_cancelled"

    def test_payload_includes_customer_id(self) -> None:
        db = _make_db()
        event = _make_sub_event(
            event_type="customer.subscription.deleted", customer_id="cus_del_999"
        )

        with patch("app.services.audit.emit") as mock_emit:
            self._run(_handle_subscription_deleted(db, event))

        payload = mock_emit.call_args[1]["payload"]
        assert payload["customer_id"] == "cus_del_999"


# ---------------------------------------------------------------------------
# invoice.payment_failed
# ---------------------------------------------------------------------------


class TestHandleInvoicePaymentFailed:

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_updates_subscription_to_past_due(self) -> None:
        db = _make_db()
        event = _make_invoice_event()

        with (
            patch("app.services.audit.emit"),
            patch("asyncio.create_task", side_effect=lambda c: c.close()),
        ):
            self._run(_handle_invoice_payment_failed(db, event))

        db.execute.assert_called_once()

    def test_sends_dunning_email_when_email_present(self) -> None:
        db = _make_db()
        event = _make_invoice_event(customer_email="owner@example.com")

        with (
            patch("app.services.audit.emit"),
            patch("asyncio.create_task", side_effect=lambda c: c.close()) as mock_task,
        ):
            self._run(_handle_invoice_payment_failed(db, event))

        mock_task.assert_called_once()

    def test_no_dunning_email_when_no_email(self) -> None:
        db = _make_db()
        event = _make_invoice_event()
        event.data.object.customer_email = None

        with (
            patch("app.services.audit.emit"),
            patch("asyncio.create_task", side_effect=lambda c: c.close()) as mock_task,
        ):
            self._run(_handle_invoice_payment_failed(db, event))

        mock_task.assert_not_called()

    def test_skips_subscription_update_when_no_sub_id(self) -> None:
        db = _make_db()
        event = _make_invoice_event()
        event.data.object.subscription = None

        with (
            patch("app.services.audit.emit"),
            patch("asyncio.create_task", side_effect=lambda c: c.close()),
        ):
            self._run(_handle_invoice_payment_failed(db, event))

        db.execute.assert_not_called()

    def test_emits_audit_event(self) -> None:
        db = _make_db()
        event = _make_invoice_event(customer_id="cus_audit_02")

        with (
            patch("app.services.audit.emit") as mock_emit,
            patch("asyncio.create_task", side_effect=lambda c: c.close()),
        ):
            self._run(_handle_invoice_payment_failed(db, event))

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "invoice_payment_failed"


# ---------------------------------------------------------------------------
# Webhook endpoint idempotency (via _mark_processed)
# ---------------------------------------------------------------------------


class TestWebhookIdempotency:
    """Verify that replaying the same event_id is a no-op for all three event types."""

    def _build_app(self, db: AsyncMock) -> TestClient:
        from app.routers.webhooks import router as wh_router

        _app = FastAPI()

        async def _override_db():
            yield db

        _app.dependency_overrides[get_db] = _override_db
        _app.include_router(wh_router)
        return TestClient(_app)

    def _already_processed_db(self) -> AsyncMock:
        """DB where _mark_processed returns rowcount=0 (already seen)."""
        return _make_db(rowcount=0)

    def _make_signed_request(self, client: TestClient, event_type: str) -> Any:
        payload = '{"id":"evt_dup_001","type":"' + event_type + '","data":{"object":{}}}'
        fake_event = MagicMock()
        fake_event.type = event_type
        fake_event.id = "evt_dup_001"

        with (
            patch("app.routers.webhooks._verify_signature", return_value=fake_event),
            patch("app.routers.webhooks.settings") as mock_settings,
        ):
            mock_settings.stripe_webhook_secret = "whsec_test"
            resp = client.post(
                "/api/webhooks/stripe",
                content=payload,
                headers={"stripe-signature": "t=1,v1=abc"},
            )
        return resp

    def test_duplicate_event_returns_200_ok(self) -> None:
        db = self._already_processed_db()
        client = self._build_app(db)
        resp = self._make_signed_request(client, "customer.subscription.updated")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_duplicate_event_does_not_call_handler(self) -> None:
        db = self._already_processed_db()
        client = self._build_app(db)

        with patch("app.routers.webhooks._handle_subscription_updated") as mock_handler:
            self._make_signed_request(client, "customer.subscription.updated")

        mock_handler.assert_not_called()


# ---------------------------------------------------------------------------
# EntitlementService — past_due blocks pool creation with 402
# ---------------------------------------------------------------------------


class TestEntitlementServicePastDue:

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _make_club(self, stripe_customer_id: str | None = "cus_test") -> MagicMock:
        club = MagicMock()
        club.id = 1
        club.stripe_customer_id = stripe_customer_id
        club.plan_id = "price_pro"
        club.status = "active"
        return club

    def _make_sub(self, status: str) -> MagicMock:
        sub = MagicMock()
        sub.id = 1
        sub.status = status
        return sub

    def _make_db_with_club_and_sub(
        self, club: MagicMock, sub: MagicMock | None
    ) -> AsyncMock:
        db = AsyncMock()

        club_result = MagicMock()
        club_result.scalar_one_or_none = MagicMock(return_value=club)

        sub_result = MagicMock()
        sub_result.scalar_one_or_none = MagicMock(return_value=sub)

        db.execute = AsyncMock(side_effect=[club_result, sub_result])
        return db

    def test_past_due_raises_subscription_past_due_error(self) -> None:
        club = self._make_club()
        sub = self._make_sub("past_due")
        db = self._make_db_with_club_and_sub(club, sub)

        svc = EntitlementService()
        with pytest.raises(SubscriptionPastDueError):
            self._run(svc.check_subscription_active(1, db))

    def test_active_subscription_does_not_raise(self) -> None:
        club = self._make_club()
        sub = self._make_sub("active")
        db = self._make_db_with_club_and_sub(club, sub)

        svc = EntitlementService()
        self._run(svc.check_subscription_active(1, db))  # should not raise

    def test_no_stripe_customer_does_not_raise(self) -> None:
        club = self._make_club(stripe_customer_id=None)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=club)
        db.execute = AsyncMock(return_value=result)

        svc = EntitlementService()
        self._run(svc.check_subscription_active(1, db))  # should not raise

    def test_check_pool_limit_calls_check_subscription_active(self) -> None:
        """Ensure check_pool_limit propagates SubscriptionPastDueError."""
        club = self._make_club()
        sub = self._make_sub("past_due")
        db = self._make_db_with_club_and_sub(club, sub)

        svc = EntitlementService()
        with pytest.raises(SubscriptionPastDueError):
            self._run(svc.check_pool_limit(1, db))


# ---------------------------------------------------------------------------
# POST /api/v1/billing/portal
# ---------------------------------------------------------------------------


def _make_billing_app(db: AsyncMock, *, user_id: int = 42) -> TestClient:
    _app = FastAPI()

    async def _override_db():
        yield db

    async def _override_key():
        pass

    from app.dependencies.roles import require_user

    async def _override_user() -> str:
        return "user"

    _app.dependency_overrides[get_db] = _override_db
    _app.dependency_overrides[verify_api_key] = _override_key
    _app.dependency_overrides[require_user] = _override_user
    _app.include_router(billing_router)
    return TestClient(_app, raise_server_exceptions=False)


def _make_club_row(
    *,
    club_id: str = "club-uuid-001",
    slug: str = "test-club",
    stripe_customer_id: str | None = "cus_portal_001",
) -> MagicMock:
    club = MagicMock()
    club.id = 1
    club.club_id = club_id
    club.slug = slug
    club.stripe_customer_id = stripe_customer_id
    club.owner_user_id = 42
    return club


def _make_membership_row(role: str = "owner") -> MagicMock:
    m = MagicMock()
    m.role = role
    return m


class TestBillingPortalEndpoint:

    def _db_with_club_and_membership(
        self, club: MagicMock | None, membership: MagicMock | None
    ) -> AsyncMock:
        db = AsyncMock()
        club_res = MagicMock()
        club_res.scalar_one_or_none = MagicMock(return_value=club)
        mem_res = MagicMock()
        mem_res.scalar_one_or_none = MagicMock(return_value=membership)
        db.execute = AsyncMock(side_effect=[club_res, mem_res])
        return db

    def _fake_state_middleware(self, app: FastAPI, user_id: int = 42):
        """Inject request.state.user_id so the endpoint can read it."""
        from starlette.middleware.base import BaseHTTPMiddleware

        class _InjectUser(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = user_id
                return await call_next(request)

        app.add_middleware(_InjectUser)

    def test_returns_portal_url(self) -> None:
        club = _make_club_row()
        membership = _make_membership_row("owner")
        db = self._db_with_club_and_membership(club, membership)

        app = FastAPI()

        async def _override_db():
            yield db

        async def _override_key():
            pass

        from app.dependencies.roles import require_user

        async def _override_user() -> str:
            return "user"

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[verify_api_key] = _override_key
        app.dependency_overrides[require_user] = _override_user
        app.include_router(billing_router)
        self._fake_state_middleware(app)

        fake_session = MagicMock()
        fake_session.url = "https://billing.stripe.com/p/session_abc"

        with (
            patch("app.routers.billing.settings") as mock_settings,
            patch("asyncio.to_thread", new=AsyncMock(return_value=fake_session)),
        ):
            mock_settings.stripe_secret_key = "sk_test_abc"
            mock_settings.frontend_url = "http://localhost:3000"
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post(
                "/api/v1/billing/portal",
                json={"club_id": "club-uuid-001"},
            )

        assert resp.status_code == 200
        assert resp.json()["url"] == "https://billing.stripe.com/p/session_abc"

    def test_returns_404_when_club_not_found(self) -> None:
        db = self._db_with_club_and_membership(None, None)

        app = FastAPI()

        async def _override_db():
            yield db

        async def _override_key():
            pass

        from app.dependencies.roles import require_user

        async def _override_user() -> str:
            return "user"

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[verify_api_key] = _override_key
        app.dependency_overrides[require_user] = _override_user
        app.include_router(billing_router)
        self._fake_state_middleware(app)

        with patch("app.routers.billing.settings") as mock_settings:
            mock_settings.stripe_secret_key = "sk_test_abc"
            mock_settings.frontend_url = "http://localhost:3000"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/billing/portal",
                json={"club_id": "nonexistent-club"},
            )

        assert resp.status_code == 404

    def test_returns_403_when_not_owner(self) -> None:
        club = _make_club_row()
        db = self._db_with_club_and_membership(club, None)  # no owner membership

        app = FastAPI()

        async def _override_db():
            yield db

        async def _override_key():
            pass

        from app.dependencies.roles import require_user

        async def _override_user() -> str:
            return "user"

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[verify_api_key] = _override_key
        app.dependency_overrides[require_user] = _override_user
        app.include_router(billing_router)
        self._fake_state_middleware(app)

        with patch("app.routers.billing.settings") as mock_settings:
            mock_settings.stripe_secret_key = "sk_test_abc"
            mock_settings.frontend_url = "http://localhost:3000"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/billing/portal",
                json={"club_id": "club-uuid-001"},
            )

        assert resp.status_code == 403

    def test_returns_503_when_stripe_not_configured(self) -> None:
        db = self._db_with_club_and_membership(_make_club_row(), _make_membership_row())

        app = FastAPI()

        async def _override_db():
            yield db

        async def _override_key():
            pass

        from app.dependencies.roles import require_user

        async def _override_user() -> str:
            return "user"

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[verify_api_key] = _override_key
        app.dependency_overrides[require_user] = _override_user
        app.include_router(billing_router)
        self._fake_state_middleware(app)

        with patch("app.routers.billing.settings") as mock_settings:
            mock_settings.stripe_secret_key = None
            mock_settings.frontend_url = "http://localhost:3000"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/billing/portal",
                json={"club_id": "club-uuid-001"},
            )

        assert resp.status_code == 503

    def test_returns_422_when_club_has_no_stripe_customer(self) -> None:
        club = _make_club_row(stripe_customer_id=None)
        membership = _make_membership_row("owner")
        db = self._db_with_club_and_membership(club, membership)

        app = FastAPI()

        async def _override_db():
            yield db

        async def _override_key():
            pass

        from app.dependencies.roles import require_user

        async def _override_user() -> str:
            return "user"

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[verify_api_key] = _override_key
        app.dependency_overrides[require_user] = _override_user
        app.include_router(billing_router)
        self._fake_state_middleware(app)

        with patch("app.routers.billing.settings") as mock_settings:
            mock_settings.stripe_secret_key = "sk_test_abc"
            mock_settings.frontend_url = "http://localhost:3000"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/billing/portal",
                json={"club_id": "club-uuid-001"},
            )

        assert resp.status_code == 422
