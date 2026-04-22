"""Club branding endpoint — owner role, gated by custom_branding entitlement.

PUT /api/v1/clubs/{club_id}/branding  — set logo_url and palette colours.
Returns 402 when the club's plan lacks the custom_branding feature.
Returns 403 when caller is not the club owner.
Returns 422 on invalid hex colour or non-HTTPS logo_url.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.club import Club
from app.db.club_membership import ClubMembership
from app.dependencies.roles import require_user
from app.services.entitlement import EntitlementError, EntitlementService

router = APIRouter(prefix="/api/v1/clubs", tags=["clubs"])

_entitlements = EntitlementService()
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandingRequest(BaseModel):
    logo_url: str | None = None
    primary_color: str | None = None
    accent_color: str | None = None

    @field_validator("primary_color", "accent_color", mode="before")
    @classmethod
    def validate_hex(cls, v: Any) -> Any:
        if v is None:
            return v
        if not isinstance(v, str) or not _HEX_COLOR_RE.match(v):
            raise ValueError("must be a #RRGGBB hex color (e.g. '#1A2B3C')")
        return v.upper()

    @field_validator("logo_url", mode="before")
    @classmethod
    def validate_https_url(cls, v: Any) -> Any:
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("must be a string URL")
        try:
            parsed = urlparse(v)
        except Exception:
            raise ValueError("invalid URL")
        if parsed.scheme != "https":
            raise ValueError("logo_url must use HTTPS")
        return v


class BrandingResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    club_id: str
    branding: dict[str, str]


@router.put(
    "/{club_id}/branding",
    response_model=BrandingResponse,
    status_code=status.HTTP_200_OK,
)
async def set_club_branding(
    club_id: str,
    body: BrandingRequest,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    """Set custom branding for a club.

    Requires owner membership and the custom_branding plan entitlement.
    Stores logo_url, primary_color, and accent_color in branding_json JSONB.
    Only non-null fields are persisted; pass null to clear individual fields.
    """
    caller_id: int | None = getattr(request.state, "user_id", None)
    if caller_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    result = await db.execute(select(Club).where(Club.club_id == club_id))
    club = result.scalar_one_or_none()
    if club is None or club.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Club not found")

    membership_result = await db.execute(
        select(ClubMembership).where(
            ClubMembership.club_id == club.id,
            ClubMembership.user_id == caller_id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None or membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required",
        )

    try:
        await _entitlements.assert_feature(club.id, "custom_branding", db)
    except EntitlementError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc

    branding: dict[str, str] = {}
    if body.logo_url is not None:
        branding["logo_url"] = body.logo_url
    if body.primary_color is not None:
        branding["primary_color"] = body.primary_color
    if body.accent_color is not None:
        branding["accent_color"] = body.accent_color

    club.branding_json = branding if branding else None
    await db.flush()

    return BrandingResponse(
        club_id=club.club_id,
        branding=club.branding_json or {},
    )
