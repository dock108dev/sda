"""Integration tests for POST /api/webhooks/stripe.

Uses mocked Stripe SDK and a fake async DB session so no live services are
needed. Covers signature validation, idempotency, each event handler, and the
202 DB-error fallback path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import stripe
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.routers.webhooks import router

_TEST_SECRET = "whsec_test_secret"
_TEST_SIG = "t=1,v1=fakesig"
_TEST_PAYLOAD = b'{"id":"evt_test","type":"checkout.session.completed"}'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str,
    event_id: str = "evt_test123",
    obj: Any = None,
) -> SimpleNamespace:
    """Build a minimal fake Stripe event object."""
    event = SimpleNamespace()
    event.type = event_type
    event.id = event_id
    event.data = SimpleNamespace()
    event.data.object = obj or SimpleNamespace(id="obj_test")
    return event


def _make_db(rowcounts: list[int] | None = None) -> AsyncMock:
    """Return an AsyncMock session whose execute() returns the given rowcounts in order."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()

    if rowcounts is not None:
        results = [MagicMock(rowcount=rc) for rc in rowcounts]
        db.execute = AsyncMock(side_effect=results)
    else:
        db.execute = AsyncMock(return_value=MagicMock(rowcount=1))

    return db


def _make_app(db: AsyncMock) -> TestClient:
    app = FastAPI()

    async def _override() -> Any:
        yield db

    app.dependency_overrides[get_db] = _override
    app.include_router(router)
    return TestClient(app)


def _post(client: TestClient, payload: bytes = _TEST_PAYLOAD) -> Any:
    return client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _TEST_SIG, "content-type": "application/json"},
    )


# ---------------------------------------------------------------------------
# Signature and configuration validation
# ---------------------------------------------------------------------------


class TestStripeWebhookValidation:

    def test_missing_webhook_secret_returns_503(self) -> None:
        client = _make_app(_make_db())
        with patch("app.routers.webhooks.settings") as mock_cfg:
            mock_cfg.stripe_webhook_secret = None
            resp = _post(client)
        assert resp.status_code == 503
        assert resp.json()["detail"]["error"] == "webhook_not_configured"

    def test_invalid_signature_returns_400(self) -> None:
        client = _make_app(_make_db())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch(
                "stripe.Webhook.construct_event",
                side_effect=stripe.SignatureVerificationError("bad sig", _TEST_SIG),
            ),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_signature"

    def test_unknown_event_type_returns_200_noop(self) -> None:
        db = _make_db()
        client = _make_app(db)
        event = _make_event("some.unknown.event.type")
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        # No DB writes for unknown events
        db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# checkout.session.completed
# ---------------------------------------------------------------------------


class TestCheckoutSessionCompleted:

    def _make_checkout_obj(self, checkout_id: str = "cs_test_abc") -> SimpleNamespace:
        return SimpleNamespace(id=checkout_id)

    def test_checkout_completed_returns_200(self) -> None:
        db = _make_db(rowcounts=[1, 1])  # mark_processed + update
        client = _make_app(db)
        event = _make_event(
            "checkout.session.completed",
            obj=self._make_checkout_obj(),
        )
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_checkout_completed_executes_two_db_statements(self) -> None:
        """Expects ProcessedStripeEvent insert + OnboardingSession update."""
        db = _make_db(rowcounts=[1, 1])
        client = _make_app(db)
        event = _make_event("checkout.session.completed", obj=self._make_checkout_obj())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            _post(client)
        assert db.execute.call_count == 2

    def test_checkout_completed_idempotent_on_duplicate_event(self) -> None:
        """Second delivery of the same event is a no-op (rowcount=0 from idempotency check)."""
        db = _make_db(rowcounts=[0])  # mark_processed returns 0 → duplicate
        client = _make_app(db)
        event = _make_event("checkout.session.completed", obj=self._make_checkout_obj())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 200
        # Only the idempotency INSERT was executed; no handler called
        assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# customer.subscription.updated
# ---------------------------------------------------------------------------


class TestSubscriptionUpdated:

    def _make_sub(
        self,
        sub_id: str = "sub_test123",
        status: str = "active",
        plan_id: str = "price_monthly_pro",
    ) -> SimpleNamespace:
        item = SimpleNamespace(price=SimpleNamespace(id=plan_id))
        items = SimpleNamespace(data=[item])
        return SimpleNamespace(
            id=sub_id,
            customer="cus_test123",
            status=status,
            current_period_end=1_735_689_600,
            cancel_at_period_end=False,
            metadata={},
            items=items,
        )

    def test_subscription_updated_returns_200(self) -> None:
        db = _make_db(rowcounts=[1, 1, 1])
        client = _make_app(db)
        event = _make_event("customer.subscription.updated", obj=self._make_sub())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 200

    def test_subscription_updated_executes_upsert(self) -> None:
        db = _make_db(rowcounts=[1, 1, 1])
        client = _make_app(db)
        event = _make_event("customer.subscription.updated", obj=self._make_sub())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            _post(client)
        # mark_processed + upsert subscription + update Club.plan_id
        assert db.execute.call_count == 3

    def test_subscription_updated_duplicate_is_noop(self) -> None:
        db = _make_db(rowcounts=[0])
        client = _make_app(db)
        event = _make_event("customer.subscription.updated", obj=self._make_sub())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 200
        assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# customer.subscription.deleted
# ---------------------------------------------------------------------------


class TestSubscriptionDeleted:

    def _make_sub(
        self, sub_id: str = "sub_delete123", customer_id: str = "cus_delete123"
    ) -> SimpleNamespace:
        return SimpleNamespace(id=sub_id, customer=customer_id)

    def test_subscription_deleted_returns_200(self) -> None:
        db = _make_db(rowcounts=[1, 1, 1])
        client = _make_app(db)
        event = _make_event("customer.subscription.deleted", obj=self._make_sub())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 200

    def test_subscription_deleted_executes_update(self) -> None:
        db = _make_db(rowcounts=[1, 1, 1])
        client = _make_app(db)
        event = _make_event("customer.subscription.deleted", obj=self._make_sub())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            _post(client)
        # mark_processed + update subscription + update Club.status
        assert db.execute.call_count == 3

    def test_subscription_deleted_duplicate_is_noop(self) -> None:
        db = _make_db(rowcounts=[0])
        client = _make_app(db)
        event = _make_event("customer.subscription.deleted", obj=self._make_sub())
        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp = _post(client)
        assert resp.status_code == 200
        assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# End-to-end idempotency replay test
# ---------------------------------------------------------------------------


class TestDbErrorFallback:
    """When the DB write fails, route returns 202 and enqueues the Celery task."""

    def test_db_error_returns_202(self) -> None:
        from sqlalchemy.exc import OperationalError

        db = _make_db()
        db.execute = AsyncMock(side_effect=OperationalError("db down", None, None))
        db.rollback = AsyncMock()
        client = _make_app(db)
        event = _make_event("checkout.session.completed", obj=SimpleNamespace(id="cs_db_err"))

        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
            patch("app.tasks.webhook_retry.process_stripe_webhook_event") as mock_task,
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            mock_task.delay = MagicMock()
            resp = _post(client)

        assert resp.status_code == 202
        assert resp.json()["status"] == "queued"
        mock_task.delay.assert_called_once_with(event.id, _TEST_PAYLOAD.decode())

    def test_db_error_triggers_rollback(self) -> None:
        from sqlalchemy.exc import OperationalError

        db = _make_db()
        db.execute = AsyncMock(side_effect=OperationalError("db down", None, None))
        db.rollback = AsyncMock()
        client = _make_app(db)
        event = _make_event("checkout.session.completed", obj=SimpleNamespace(id="cs_rollback"))

        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
            patch("app.tasks.webhook_retry.process_stripe_webhook_event") as mock_task,
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            mock_task.delay = MagicMock()
            _post(client)

        db.rollback.assert_called_once()


class TestIdempotencyReplay:
    """Simulate replaying the same event twice; assert DB state unchanged on second call."""

    def test_same_checkout_event_replayed_twice(self) -> None:
        """First delivery processes; second delivery is a no-op."""
        db = _make_db()
        # First call: mark_processed returns 1 (new), handler update returns 1
        # Second call: mark_processed returns 0 (duplicate), handler is NOT called
        first_mark = MagicMock(rowcount=1)
        first_update = MagicMock(rowcount=1)
        second_mark = MagicMock(rowcount=0)
        db.execute = AsyncMock(side_effect=[first_mark, first_update, second_mark])

        client = _make_app(db)
        checkout_obj = SimpleNamespace(id="cs_replay_test")
        event = _make_event("checkout.session.completed", event_id="evt_replay_001", obj=checkout_obj)

        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET

            resp1 = _post(client)
            assert resp1.status_code == 200

            resp2 = _post(client)
            assert resp2.status_code == 200

        # First call: 2 executes (mark + update), second call: 1 execute (mark only)
        assert db.execute.call_count == 3

    def test_same_subscription_updated_event_replayed_twice(self) -> None:
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(rowcount=1),  # 1st call: mark_processed — new
                MagicMock(rowcount=1),  # 1st call: upsert subscription
                MagicMock(rowcount=1),  # 1st call: update Club.plan_id
                MagicMock(rowcount=0),  # 2nd call: mark_processed — duplicate
            ]
        )
        client = _make_app(db)

        item = SimpleNamespace(price=SimpleNamespace(id="price_pro"))
        sub = SimpleNamespace(
            id="sub_replay_001",
            customer="cus_replay",
            status="active",
            current_period_end=None,
            cancel_at_period_end=False,
            metadata=None,
            items=SimpleNamespace(data=[item]),
        )
        event = _make_event(
            "customer.subscription.updated",
            event_id="evt_sub_replay_001",
            obj=sub,
        )

        with (
            patch("app.routers.webhooks.settings") as mock_cfg,
            patch("stripe.Webhook.construct_event", return_value=event),
        ):
            mock_cfg.stripe_webhook_secret = _TEST_SECRET
            resp1 = _post(client)
            resp2 = _post(client)

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # 3 executes on first call, 1 on second
        assert db.execute.call_count == 4
