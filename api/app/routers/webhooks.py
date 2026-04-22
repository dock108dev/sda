"""Stripe webhook handler — idempotent event processing via processed_stripe_events table."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

import app.services.audit as audit
from app.config import settings
from app.db import get_db
from app.db.club import Club
from app.db.onboarding import OnboardingSession
from app.db.stripe import ProcessedStripeEvent, StripeSubscription
from app.services.email import send_dunning_email, send_payment_confirmation_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _verify_signature(payload: bytes, sig_header: str, secret: str) -> Any:
    """Verify the Stripe webhook signature and return the parsed event; raise 400 on failure."""
    try:
        return stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.SignatureVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_signature", "message": "Invalid Stripe signature."},
        ) from exc


async def _mark_processed(db: AsyncSession, event_id: str) -> bool:
    """Insert event_id into processed_stripe_events; return True only for newly inserted rows."""
    stmt = pg_insert(ProcessedStripeEvent).values(event_id=event_id).on_conflict_do_nothing()
    result = await db.execute(stmt)
    return result.rowcount > 0


async def _handle_checkout_completed(db: AsyncSession, event: Any) -> None:
    """Advance OnboardingSession to status=paid for the completed checkout session."""
    checkout_id: str = event.data.object.id
    await db.execute(
        update(OnboardingSession)
        .where(OnboardingSession.stripe_checkout_session_id == checkout_id)
        .values(status="paid")
    )
    logger.info("onboarding_session_paid", extra={"checkout_session_id": checkout_id})
    audit.emit(
        "subscription_activated",
        actor_type="webhook",
        actor_id=checkout_id,
        resource_type="subscription",
        resource_id=checkout_id,
        payload={"checkout_session_id": checkout_id},
    )

    # Fire-and-forget payment confirmation email using email from Stripe event.
    customer_email: str | None = getattr(event.data.object, "customer_email", None)
    if not customer_email:
        details = getattr(event.data.object, "customer_details", None)
        if details:
            customer_email = getattr(details, "email", None)
    if customer_email:
        asyncio.create_task(
            send_payment_confirmation_email(to=customer_email)
        )


async def _handle_subscription_updated(db: AsyncSession, event: Any) -> None:
    """Upsert a StripeSubscription row and sync Club.plan_id from a subscription.updated event."""
    sub = event.data.object

    plan_id = ""
    items_data = getattr(getattr(sub, "items", None), "data", None)
    if items_data:
        plan_id = items_data[0].price.id

    period_end: datetime | None = None
    raw_period_end = getattr(sub, "current_period_end", None)
    if raw_period_end:
        period_end = datetime.fromtimestamp(raw_period_end, tz=UTC)

    raw_metadata = getattr(sub, "metadata", None)
    metadata = dict(raw_metadata) if raw_metadata else None
    cancel_at = bool(getattr(sub, "cancel_at_period_end", False))

    stmt = (
        pg_insert(StripeSubscription.__table__)
        .values(
            stripe_subscription_id=sub.id,
            stripe_customer_id=sub.customer,
            plan_id=plan_id,
            status=sub.status,
            current_period_end=period_end,
            cancel_at_period_end=cancel_at,
            metadata=metadata,
        )
        .on_conflict_do_update(
            index_elements=["stripe_subscription_id"],
            set_={
                "plan_id": plan_id,
                "status": sub.status,
                "current_period_end": period_end,
                "cancel_at_period_end": cancel_at,
                "metadata": metadata,
            },
        )
    )
    await db.execute(stmt)

    # Keep Club.plan_id in sync so EntitlementService reads fresh limits immediately.
    if plan_id:
        await db.execute(
            update(Club)
            .where(Club.stripe_customer_id == sub.customer)
            .values(plan_id=plan_id)
        )

    logger.info("subscription_synced", extra={"subscription_id": sub.id, "status": sub.status})
    audit.emit(
        "subscription_updated",
        actor_type="webhook",
        actor_id=sub.id,
        resource_type="subscription",
        resource_id=sub.id,
        payload={"subscription_id": sub.id, "status": sub.status, "plan_id": plan_id},
    )


async def _handle_subscription_deleted(db: AsyncSession, event: Any) -> None:
    """Mark subscription canceled and restrict the club; preserves entitlement history."""
    sub = event.data.object
    sub_id: str = sub.id
    customer_id: str = sub.customer

    await db.execute(
        update(StripeSubscription)
        .where(StripeSubscription.stripe_subscription_id == sub_id)
        .values(status="canceled", cancel_at_period_end=False)
    )
    await db.execute(
        update(Club)
        .where(Club.stripe_customer_id == customer_id)
        .values(status="restricted")
    )
    logger.info("subscription_cancelled", extra={"subscription_id": sub_id})
    audit.emit(
        "subscription_cancelled",
        actor_type="webhook",
        actor_id=sub_id,
        resource_type="subscription",
        resource_id=sub_id,
        payload={"subscription_id": sub_id, "customer_id": customer_id},
    )


async def _handle_invoice_payment_failed(db: AsyncSession, event: Any) -> None:
    """Set subscription to past_due and send a dunning email to the club owner."""
    invoice = event.data.object
    customer_id: str = invoice.customer
    sub_id: str | None = getattr(invoice, "subscription", None)

    if sub_id:
        await db.execute(
            update(StripeSubscription)
            .where(StripeSubscription.stripe_subscription_id == sub_id)
            .values(status="past_due")
        )

    logger.info(
        "invoice_payment_failed",
        extra={"customer_id": customer_id, "subscription_id": sub_id},
    )
    audit.emit(
        "invoice_payment_failed",
        actor_type="webhook",
        actor_id=customer_id,
        resource_type="subscription",
        resource_id=sub_id or customer_id,
        payload={"customer_id": customer_id, "subscription_id": sub_id},
    )

    customer_email: str | None = getattr(invoice, "customer_email", None)
    if customer_email:
        asyncio.create_task(send_dunning_email(to=customer_email))


_HANDLERS: dict[str, Any] = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_failed": _handle_invoice_payment_failed,
}


@router.post("/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Process Stripe webhook events; idempotent via processed_stripe_events table.

    Verifies the Stripe-Signature header before any processing. Unknown event
    types return 200 immediately. Known event types are deduplicated via
    INSERT … ON CONFLICT DO NOTHING on processed_stripe_events.

    If the DB write fails after signature verification, the event is enqueued
    as a Celery task for async retry and HTTP 202 is returned.
    """
    secret = settings.stripe_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "webhook_not_configured",
                "message": "Webhook processing is not configured.",
            },
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    event = _verify_signature(payload, sig_header, secret)

    handler = _HANDLERS.get(event.type)
    if handler is None:
        logger.debug("stripe_webhook_noop", extra={"event_type": event.type, "event_id": event.id})
        return {"status": "ok"}

    try:
        newly_processed = await _mark_processed(db, event.id)
        if not newly_processed:
            logger.info(
                "stripe_webhook_duplicate",
                extra={"event_type": event.type, "event_id": event.id},
            )
            return {"status": "ok"}

        await handler(db, event)
        logger.info(
            "stripe_webhook_processed",
            extra={"event_type": event.type, "event_id": event.id},
        )
        return {"status": "ok"}
    except Exception:
        logger.warning(
            "stripe_webhook_db_error_enqueuing",
            extra={"event_id": event.id, "event_type": event.type},
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            logger.warning("stripe_webhook_rollback_failed", exc_info=True)
        # Lazy import avoids circular dependency at module load time.
        from app.tasks.webhook_retry import process_stripe_webhook_event
        process_stripe_webhook_event.delay(event.id, payload.decode())
        return JSONResponse({"status": "queued"}, status_code=202)
