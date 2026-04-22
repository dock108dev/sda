"""Club membership endpoints — invite flow and role-based access control.

POST /api/v1/clubs/invites/{token}/accept  — accept a signed JWT invite
POST /api/v1/clubs/{club_id}/invites       — send an invite (admin or owner)
GET  /api/v1/clubs/{club_id}/members       — list members (any role)
DELETE /api/v1/clubs/{club_id}/members/{target_user_id} — remove member (owner only)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.audit as audit
from app.db import get_db
from app.db.club import Club
from app.db.club_membership import ClubMembership
from app.db.users import User
from app.dependencies.roles import create_invite_token, decode_invite_token, require_user
from app.services.email import send_club_invite_email
from app.services.entitlement import EntitlementService, SeatLimitError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/clubs", tags=["clubs"])

_entitlements = EntitlementService()
_ADMIN_ROLES = frozenset({"owner", "admin"})
_VALID_INVITE_ROLES = frozenset({"admin", "viewer"})


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class InviteRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address to invite")
    role: str = Field(..., description="Role to grant: admin or viewer")


class MemberResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user_id: int
    email: str
    role: str
    accepted_at: str | None


class ClubSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    club_id: str
    name: str
    slug: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_active_club(club_public_id: str, db: AsyncSession) -> Club:
    result = await db.execute(select(Club).where(Club.club_id == club_public_id))
    club = result.scalar_one_or_none()
    if club is None or club.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Club not found")
    return club


async def _get_membership(club: Club, user_id: int, db: AsyncSession) -> ClubMembership:
    result = await db.execute(
        select(ClubMembership).where(
            ClubMembership.club_id == club.id,
            ClubMembership.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a club member")
    return membership


def _caller_id(request: Request) -> int:
    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user_id


# ---------------------------------------------------------------------------
# Endpoints — static path first to avoid route shadowing
# ---------------------------------------------------------------------------


@router.post(
    "/invites/{token}/accept",
    response_model=ClubSummary,
    summary="Accept a club membership invite",
)
async def accept_invite(
    token: str,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ClubSummary:
    """Accept a signed JWT invite and create a membership row.

    Returns 410 Gone when the token is expired or malformed.
    Returns 409 Conflict when the caller is already a member.
    """
    caller_id = _caller_id(request)

    try:
        payload: dict[str, Any] = decode_invite_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite has expired")
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invalid invite token")

    club_db_id: int = payload["club_id"]
    role: str = payload["role"]
    inviter_id: int | None = payload.get("inviter_id")
    iat: float | None = payload.get("iat")
    invited_at = datetime.fromtimestamp(iat, tz=UTC) if iat else datetime.now(UTC)

    result = await db.execute(select(Club).where(Club.id == club_db_id))
    club = result.scalar_one_or_none()
    if club is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Club not found")

    membership = ClubMembership(
        club_id=club.id,
        user_id=caller_id,
        role=role,
        invited_at=invited_at,
        accepted_at=datetime.now(UTC),
        invited_by_user_id=inviter_id,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already a member of this club",
        )

    audit.emit(
        "club_invite_accepted",
        actor_type="user",
        actor_id=str(caller_id),
        resource_type="club_membership",
        resource_id=str(club.id),
        payload={"club_id": club.club_id, "role": role},
    )
    logger.info(
        "club_invite_accepted",
        extra={"user_id": caller_id, "club_id": club.club_id, "role": role},
    )
    return ClubSummary(club_id=club.club_id, name=club.name, slug=club.slug)


@router.post(
    "/{club_id}/invites",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a club membership invite",
)
async def send_invite(
    club_id: str,
    body: InviteRequest,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Send an invite email to *email* granting *role* in the club.

    Requires owner or admin membership. Admin invites are subject to the
    plan's max_admins_per_club limit enforced via EntitlementService; exceeding
    the limit raises HTTP 402.
    """
    if body.role not in _VALID_INVITE_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role '{body.role}'. Must be one of: {', '.join(sorted(_VALID_INVITE_ROLES))}",
        )

    caller_id = _caller_id(request)
    club = await _get_active_club(club_id, db)
    caller_membership = await _get_membership(club, caller_id, db)

    if caller_membership.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Owner or admin role required"
        )

    if body.role == "admin":
        try:
            await _entitlements.check_admin_seat(club.id, db)
        except SeatLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
            ) from exc

    result = await db.execute(select(User).where(User.id == caller_id))
    caller = result.scalar_one_or_none()
    inviter_email = caller.email if caller else "a club admin"

    token = create_invite_token(
        club_id=club.id,
        invitee_email=str(body.email).lower(),
        role=body.role,
        inviter_id=caller_id,
    )

    try:
        await send_club_invite_email(
            to=str(body.email).lower(),
            club_name=club.name,
            inviter_email=inviter_email,
            role=body.role,
            token=token,
        )
    except Exception:
        logger.exception(
            "club_invite_email_failed",
            extra={"club_id": club_id, "to": str(body.email)},
        )

    audit.emit(
        "club_invite_sent",
        actor_type="user",
        actor_id=str(caller_id),
        resource_type="club_membership",
        resource_id=str(club.id),
        payload={
            "club_id": club.club_id,
            "invitee_email": str(body.email).lower(),
            "role": body.role,
        },
    )
    logger.info(
        "club_invite_sent",
        extra={"club_id": club_id, "invitee": str(body.email), "role": body.role},
    )
    return {"detail": "Invite sent"}


@router.get(
    "/{club_id}/members",
    response_model=list[MemberResponse],
    summary="List club members",
)
async def list_members(
    club_id: str,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    """Return all accepted members and their roles.

    Requires club membership (any role).
    """
    caller_id = _caller_id(request)
    club = await _get_active_club(club_id, db)
    await _get_membership(club, caller_id, db)

    result = await db.execute(
        select(ClubMembership, User)
        .join(User, ClubMembership.user_id == User.id)
        .where(ClubMembership.club_id == club.id)
        .order_by(ClubMembership.accepted_at.asc())
    )
    rows = result.all()
    return [
        MemberResponse(
            user_id=m.user_id,
            email=u.email,
            role=m.role,
            accepted_at=m.accepted_at.isoformat() if m.accepted_at else None,
        )
        for m, u in rows
    ]


@router.delete(
    "/{club_id}/members/{target_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a club member",
)
async def remove_member(
    club_id: str,
    target_user_id: int,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a member from the club. Requires owner role.

    Returns 409 Conflict if the owner attempts to remove themselves.
    """
    caller_id = _caller_id(request)
    club = await _get_active_club(club_id, db)
    caller_membership = await _get_membership(club, caller_id, db)

    if caller_membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required"
        )

    if target_user_id == caller_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner cannot remove themselves",
        )

    result = await db.execute(
        select(ClubMembership).where(
            ClubMembership.club_id == club.id,
            ClubMembership.user_id == target_user_id,
        )
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )

    await db.delete(target)
    await db.flush()

    audit.emit(
        "club_member_removed",
        actor_type="user",
        actor_id=str(caller_id),
        resource_type="club_membership",
        resource_id=str(club.id),
        payload={"club_id": club.club_id, "removed_user_id": target_user_id},
    )
    logger.info(
        "club_member_removed",
        extra={"club_id": club_id, "target_user_id": target_user_id},
    )
