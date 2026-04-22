"""Onboarding endpoints — public, no API key required.

POST /api/onboarding/club-claims        — submit a 'claim your club' form
GET  /api/onboarding/session/{token}    — poll session status (frontend polling)
POST /api/onboarding/claim              — complete paid→claimed transition
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.alias_generators import to_camel

from app.utils.sanitize import sanitize_text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.onboarding import ClubClaim, OnboardingSession
from app.db.users import User
from app.services.email import send_email
from app.services.onboarding_state_machine import (
    InvalidTransitionError,
    SessionStatus,
    assert_can_transition,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ClubClaimRequest(BaseModel):
    model_config = _ALIAS_CFG

    club_name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr
    expected_entries: int | None = Field(default=None, ge=1, le=100_000)
    notes: str = Field(default="", max_length=2000)

    @field_validator("club_name", "notes", mode="before")
    @classmethod
    def _strip_html(cls, v: object) -> object:
        return sanitize_text(v)


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


# ---------------------------------------------------------------------------
# Session polling and claim endpoints
# ---------------------------------------------------------------------------


class SessionStatusResponse(BaseModel):
    model_config = _ALIAS_CFG

    session_token: str
    status: str
    expires_at: datetime | None


class ClaimRequest(BaseModel):
    model_config = _ALIAS_CFG

    claim_token: str = Field(min_length=1, max_length=64)


class ClaimResponse(BaseModel):
    model_config = _ALIAS_CFG

    session_token: str
    status: str


def _is_session_expired(session: OnboardingSession) -> bool:
    """Return True if the session has passed its TTL or is explicitly expired."""
    if session.status == SessionStatus.EXPIRED:
        return True
    if session.expires_at is not None:
        now = datetime.now(UTC)
        exp = session.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return now >= exp
    return False


@router.get(
    "/session/{session_token}",
    response_model=SessionStatusResponse,
)
async def get_session_status(
    session_token: str,
    db: AsyncSession = Depends(get_db),
) -> SessionStatusResponse:
    """Return the current status of an onboarding session.

    Used by the frontend to poll until status transitions to 'paid'
    after the Stripe webhook fires. Returns 410 for expired sessions,
    404 for unknown tokens.
    """
    result = await db.execute(
        select(OnboardingSession).where(
            OnboardingSession.session_token == session_token
        )
    )
    session: OnboardingSession | None = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    if _is_session_expired(session):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="expired")

    return SessionStatusResponse(
        session_token=session.session_token,
        status=session.status,
        expires_at=session.expires_at,
    )


@router.post(
    "/claim",
    response_model=ClaimResponse,
    status_code=status.HTTP_200_OK,
)
async def claim_session(
    req: ClaimRequest,
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    """Transition a paid onboarding session to claimed, creating the account context.

    Accepts the claim_token (delivered via the Stripe success_url). Uses a
    row-level lock to prevent concurrent double-claims — exactly one request
    succeeds; duplicates receive 409.
    """
    result = await db.execute(
        select(OnboardingSession)
        .where(OnboardingSession.claim_token == req.claim_token)
        .with_for_update()
    )
    session: OnboardingSession | None = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    if _is_session_expired(session):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="expired")

    if session.status == SessionStatus.CLAIMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "already_claimed", "message": "Session already claimed."},
        )

    try:
        assert_can_transition(session.status, SessionStatus.CLAIMED)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_transition", "message": str(exc)},
        ) from exc

    session.status = SessionStatus.CLAIMED
    await db.flush()

    # Create the club_admin user account from the associated club claim.
    claim_result = await db.execute(
        select(ClubClaim).where(ClubClaim.claim_id == session.claim_id)
    )
    club_claim = claim_result.scalar_one_or_none()
    if club_claim is not None:
        existing_user = await db.execute(
            select(User).where(User.email == club_claim.contact_email.lower())
        )
        if existing_user.scalar_one_or_none() is None:
            new_user = User(
                email=club_claim.contact_email.lower(),
                password_hash=None,
                role="club_admin",
                is_active=True,
            )
            db.add(new_user)
            await db.flush()
            logger.info(
                "club_admin_user_created",
                extra={"email": club_claim.contact_email.lower(), "claim_id": session.claim_id},
            )

    logger.info(
        "onboarding_session_claimed",
        extra={"session_token": session.session_token, "claim_id": session.claim_id},
    )

    return ClaimResponse(
        session_token=session.session_token,
        status=session.status,
    )
