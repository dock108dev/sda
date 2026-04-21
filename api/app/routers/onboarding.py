"""Onboarding endpoints — public, no API key required.

POST /api/onboarding/club-claims — submit a 'claim your club' form
                                   from the prospect-facing onboarding site.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from html import escape

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.onboarding import ClubClaim
from app.services.email import send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ClubClaimRequest(BaseModel):
    model_config = _ALIAS_CFG

    club_name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr
    expected_entries: int | None = Field(default=None, ge=1, le=100_000)
    notes: str = Field(default="", max_length=2000)


class ClubClaimResponse(BaseModel):
    model_config = _ALIAS_CFG

    claim_id: str
    received_at: datetime


async def _notify_claim(claim: ClubClaim) -> None:
    """Send a notification email about a new club claim.

    Silently no-ops if ``onboarding_notification_email`` is unset — we don't
    want a missing optional setting to spam the logs about "no email provider
    configured" on every submission.
    """
    recipient = settings.onboarding_notification_email
    if not recipient:
        logger.info(
            "club_claim_notification_skipped_no_recipient",
            extra={"claim_id": claim.claim_id},
        )
        return

    expected = (
        escape(str(claim.expected_entries))
        if claim.expected_entries is not None
        else "—"
    )
    notes_html = escape(claim.notes or "") or "—"
    html = f"""\
<h2>New club claim</h2>
<ul>
  <li><strong>Club:</strong> {escape(claim.club_name)}</li>
  <li><strong>Contact email:</strong> {escape(claim.contact_email)}</li>
  <li><strong>Expected entries:</strong> {expected}</li>
  <li><strong>Notes:</strong> {notes_html}</li>
  <li><strong>Source IP:</strong> {escape(claim.source_ip or "unknown")}</li>
  <li><strong>Claim ID:</strong> {escape(claim.claim_id)}</li>
</ul>
"""
    await send_email(
        to=recipient,
        subject=f"[Club Claim] {claim.club_name}",
        html=html,
    )


@router.post(
    "/club-claims",
    response_model=ClubClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_club_claim(
    req: ClubClaimRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ClubClaimResponse:
    """Persist a club claim and fire off a notification email.

    Public endpoint — no API key. Rate-limited per-IP by middleware.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    source_ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    user_agent = request.headers.get("user-agent", "")[:500] or None

    claim = ClubClaim(
        claim_id=f"claim_{secrets.token_urlsafe(6)}",
        club_name=req.club_name.strip(),
        contact_email=req.contact_email.lower(),
        expected_entries=req.expected_entries,
        notes=req.notes.strip(),
        source_ip=source_ip,
        user_agent=user_agent,
    )
    db.add(claim)
    await db.flush()
    await db.commit()
    await db.refresh(claim)

    try:
        await _notify_claim(claim)
    except Exception:
        logger.exception(
            "club_claim_notification_failed",
            extra={"claim_id": claim.claim_id},
        )

    return ClubClaimResponse(
        claim_id=claim.claim_id, received_at=claim.received_at
    )
