"""Commerce endpoints — Stripe checkout session creation."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.onboarding import ClubClaim, OnboardingSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/commerce", tags=["commerce"])

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CheckoutRequest(BaseModel):
    model_config = _ALIAS_CFG

    plan_id: str = Field(min_length=1, max_length=255)
    club_claim_id: str = Field(min_length=1, max_length=32)


class CheckoutResponse(BaseModel):
    model_config = _ALIAS_CFG

    checkout_url: str
    session_token: str


def _require_stripe_key() -> str:
    """Return the configured Stripe secret key or raise 503."""
    key = settings.stripe_secret_key
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "stripe_unavailable",
                "message": "Payment processing is not configured.",
            },
        )
    return key


def _stripe_503(exc: Exception) -> HTTPException:
    logger.error("stripe_api_error", extra={"error": str(exc)})
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "stripe_unavailable",
            "message": "Payment processing is temporarily unavailable.",
        },
    )


async def _get_or_create_stripe_customer(email: str, api_key: str) -> str:
    """Return Stripe customer ID for email, creating one if none exists."""
    stripe.api_key = api_key
    try:
        result: Any = await asyncio.to_thread(
            stripe.Customer.search,
            query=f'email:"{email}"',
            limit=1,
        )
        if result.data:
            return result.data[0].id
        customer: Any = await asyncio.to_thread(stripe.Customer.create, email=email)
        return customer.id
    except stripe.StripeError as exc:
        raise _stripe_503(exc) from exc


async def _create_checkout_session(
    customer_id: str,
    plan_id: str,
    idempotency_key: str,
    api_key: str,
) -> Any:
    """Create a Stripe Checkout Session in subscription mode."""
    stripe.api_key = api_key
    try:
        return await asyncio.to_thread(
            stripe.checkout.Session.create,
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": plan_id, "quantity": 1}],
            success_url=settings.stripe_checkout_success_url,
            cancel_url=settings.stripe_checkout_cancel_url,
            idempotency_key=idempotency_key,
        )
    except stripe.StripeError as exc:
        raise _stripe_503(exc) from exc


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_checkout_session(
    req: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for a prospect's club subscription.

    Validates the club claim, creates or retrieves the Stripe Customer for the
    contact email, creates a Checkout Session in subscription mode, and stores
    a pending OnboardingSession before returning the checkout URL.
    """
    api_key = _require_stripe_key()

    result = await db.execute(
        select(ClubClaim).where(ClubClaim.claim_id == req.club_claim_id)
    )
    claim: ClubClaim | None = result.scalar_one_or_none()
    if claim is None or claim.status != "new":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_claim",
                "message": "Club claim not found or not eligible for checkout.",
            },
        )

    customer_id = await _get_or_create_stripe_customer(claim.contact_email, api_key)

    idempotency_key = f"{req.club_claim_id}:{req.plan_id}"
    checkout = await _create_checkout_session(
        customer_id=customer_id,
        plan_id=req.plan_id,
        idempotency_key=idempotency_key,
        api_key=api_key,
    )

    session_token = f"sess_{secrets.token_urlsafe(32)}"
    claim_token = f"clm_{secrets.token_urlsafe(32)}"
    session = OnboardingSession(
        session_token=session_token,
        claim_token=claim_token,
        claim_id=req.club_claim_id,
        stripe_checkout_session_id=checkout.id,
        plan_id=req.plan_id,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(session)
    await db.flush()

    logger.info(
        "checkout_session_created",
        extra={
            "claim_id": req.club_claim_id,
            "plan_id": req.plan_id,
            "session_token": session_token,
        },
    )

    return CheckoutResponse(
        checkout_url=checkout.url,
        session_token=session_token,
    )
