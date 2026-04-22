"""Billing management endpoints — Stripe Customer Portal self-service."""

from __future__ import annotations

import asyncio
import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.club import Club
from app.db.club_membership import ClubMembership
from app.dependencies.roles import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class PortalRequest(BaseModel):
    club_id: str


class PortalResponse(BaseModel):
    url: str


@router.post("/portal", response_model=PortalResponse)
async def create_customer_portal(
    body: PortalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _role: str = Depends(require_user),
) -> PortalResponse:
    """Create a Stripe Customer Portal session for self-service billing management.

    Requires the caller to be the owner of the specified club.
    Returns a short-lived portal URL the client should redirect the user to.
    """
    api_key = settings.stripe_secret_key
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "billing_not_configured", "message": "Billing is not configured."},
        )

    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication required",
        )

    result = await db.execute(select(Club).where(Club.club_id == body.club_id))
    club = result.scalar_one_or_none()
    if club is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Club not found")

    membership_result = await db.execute(
        select(ClubMembership).where(
            ClubMembership.club_id == club.id,
            ClubMembership.user_id == user_id,
            ClubMembership.role == "owner",
        )
    )
    if membership_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Club owner role required",
        )

    if not club.stripe_customer_id:
        raise HTTPException(
            status_code=422,
            detail="Club has no Stripe customer record",
        )

    return_url = settings.frontend_url.rstrip("/") + f"/clubs/{club.slug}/settings"

    try:
        session = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=club.stripe_customer_id,
            return_url=return_url,
            api_key=api_key,
        )
    except stripe.StripeError as exc:
        logger.error(
            "stripe_portal_error",
            extra={"club_id": body.club_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "stripe_error", "message": "Failed to create billing portal session."},
        ) from exc

    return PortalResponse(url=session.url)
