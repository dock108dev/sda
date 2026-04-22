"""Unit tests for Stripe ORM models.

Verifies field types, constraints, and that all three models are importable
from the db package without a live database connection.
"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.stripe import ProcessedStripeEvent, StripeCustomer, StripeSubscription


# ---------------------------------------------------------------------------
# StripeCustomer
# ---------------------------------------------------------------------------


class TestStripeCustomerModel:

    def test_tablename(self) -> None:
        assert StripeCustomer.__tablename__ == "stripe_customers"

    def test_required_columns_present(self) -> None:
        col_names = {c.name for c in StripeCustomer.__table__.columns}
        assert {"id", "club_id", "stripe_customer_id", "created_at"} <= col_names

    def test_stripe_customer_id_is_unique(self) -> None:
        col = StripeCustomer.__table__.c.stripe_customer_id
        assert col.unique, "stripe_customer_id must have a unique constraint"

    def test_stripe_customer_id_type(self) -> None:
        col = StripeCustomer.__table__.c.stripe_customer_id
        assert isinstance(col.type, String)

    def test_club_id_not_nullable(self) -> None:
        col = StripeCustomer.__table__.c.club_id
        assert not col.nullable

    def test_created_at_has_server_default(self) -> None:
        col = StripeCustomer.__table__.c.created_at
        assert col.server_default is not None


# ---------------------------------------------------------------------------
# StripeSubscription
# ---------------------------------------------------------------------------


class TestStripeSubscriptionModel:

    def test_tablename(self) -> None:
        assert StripeSubscription.__tablename__ == "stripe_subscriptions"

    def test_required_columns_present(self) -> None:
        col_names = {c.name for c in StripeSubscription.__table__.columns}
        assert {
            "id",
            "stripe_subscription_id",
            "stripe_customer_id",
            "plan_id",
            "status",
            "current_period_end",
            "cancel_at_period_end",
            "metadata",
        } <= col_names

    def test_stripe_subscription_id_is_unique(self) -> None:
        col = StripeSubscription.__table__.c.stripe_subscription_id
        assert col.unique, "stripe_subscription_id must have a unique constraint"

    def test_stripe_subscription_id_type(self) -> None:
        col = StripeSubscription.__table__.c.stripe_subscription_id
        assert isinstance(col.type, String)

    def test_stripe_customer_id_type(self) -> None:
        col = StripeSubscription.__table__.c.stripe_customer_id
        assert isinstance(col.type, String)

    def test_cancel_at_period_end_is_boolean(self) -> None:
        col = StripeSubscription.__table__.c.cancel_at_period_end
        assert isinstance(col.type, Boolean)

    def test_cancel_at_period_end_has_server_default(self) -> None:
        col = StripeSubscription.__table__.c.cancel_at_period_end
        assert col.server_default is not None

    def test_metadata_is_jsonb(self) -> None:
        col = StripeSubscription.__table__.c.metadata
        assert isinstance(col.type, JSONB)

    def test_metadata_is_nullable(self) -> None:
        col = StripeSubscription.__table__.c.metadata
        assert col.nullable

    def test_current_period_end_is_nullable(self) -> None:
        col = StripeSubscription.__table__.c.current_period_end
        assert col.nullable


# ---------------------------------------------------------------------------
# ProcessedStripeEvent
# ---------------------------------------------------------------------------


class TestProcessedStripeEventModel:

    def test_tablename(self) -> None:
        assert ProcessedStripeEvent.__tablename__ == "processed_stripe_events"

    def test_required_columns_present(self) -> None:
        col_names = {c.name for c in ProcessedStripeEvent.__table__.columns}
        assert {"event_id", "processed_at"} <= col_names

    def test_event_id_is_primary_key(self) -> None:
        col = ProcessedStripeEvent.__table__.c.event_id
        assert col.primary_key, "event_id must be the primary key"

    def test_event_id_type(self) -> None:
        col = ProcessedStripeEvent.__table__.c.event_id
        assert isinstance(col.type, String)

    def test_processed_at_has_server_default(self) -> None:
        col = ProcessedStripeEvent.__table__.c.processed_at
        assert col.server_default is not None


# ---------------------------------------------------------------------------
# Package-level imports
# ---------------------------------------------------------------------------


def test_models_importable_from_db_package() -> None:
    """All three models must be reachable from app.db without a live DB."""
    from app.db import ProcessedStripeEvent, StripeCustomer, StripeSubscription

    assert StripeCustomer.__tablename__ == "stripe_customers"
    assert StripeSubscription.__tablename__ == "stripe_subscriptions"
    assert ProcessedStripeEvent.__tablename__ == "processed_stripe_events"
