"""User preferences endpoints for syncing client-side settings.

GET   /auth/me/preferences  — fetch saved preferences
PUT   /auth/me/preferences  — full replace
PATCH /auth/me/preferences  — partial merge
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.user_preferences import UserPreferences
from app.dependencies.roles import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/me", tags=["auth", "preferences"])

MAX_PINNED = 10
MAX_REVEALED = 500
MAX_PAYLOAD_KEYS = 50  # safety cap on settings keys


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SettingsPayload(BaseModel):
    """Freeform settings dict — known keys validated, unknown ignored."""

    model_config = {"extra": "allow"}

    theme: str | None = None
    scoreRevealMode: str | None = None
    preferredSportsbook: str | None = None
    oddsFormat: str | None = None
    autoResumePosition: bool | None = None
    homeExpandedSections: list[str] | None = None
    hideLimitedData: bool | None = None
    timelineDefaultTiers: list[int] | None = None


class PreferencesBody(BaseModel):
    settings: dict | None = None
    pinnedGameIds: list[int] | None = Field(None, max_length=MAX_PINNED)
    revealedGameIds: list[int] | None = Field(None, max_length=MAX_REVEALED)


class PreferencesResponse(BaseModel):
    settings: dict
    pinnedGameIds: list[int]
    revealedGameIds: list[int]
    updatedAt: datetime

    model_config = {"from_attributes": True}


class OkResponse(BaseModel):
    ok: bool = True
    updatedAt: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_settings(raw: dict) -> dict:
    """Strip unknown or oversized settings values."""
    if len(raw) > MAX_PAYLOAD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"settings may have at most {MAX_PAYLOAD_KEYS} keys",
        )
    return raw


async def _get_user_id(request: Request) -> int:
    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


async def _get_or_create(db: AsyncSession, user_id: int) -> UserPreferences:
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs


def _to_response(prefs: UserPreferences) -> PreferencesResponse:
    return PreferencesResponse(
        settings=prefs.settings or {},
        pinnedGameIds=prefs.pinned_game_ids or [],
        revealedGameIds=prefs.revealed_game_ids or [],
        updatedAt=prefs.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/preferences",
    response_model=PreferencesResponse,
    summary="Get saved user preferences",
)
async def get_preferences(
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    user_id = await _get_user_id(request)
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        # Return empty defaults — don't create a row until they save
        return PreferencesResponse(
            settings={},
            pinnedGameIds=[],
            revealedGameIds=[],
            updatedAt=datetime.min,
        )
    return _to_response(prefs)


@router.put(
    "/preferences",
    response_model=OkResponse,
    summary="Replace all user preferences",
)
async def put_preferences(
    body: PreferencesBody,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = await _get_user_id(request)

    settings = _validate_settings(body.settings or {})
    pinned = body.pinnedGameIds or []
    revealed = body.revealedGameIds or []

    if len(pinned) > MAX_PINNED:
        raise HTTPException(422, f"pinnedGameIds max {MAX_PINNED}")
    if len(revealed) > MAX_REVEALED:
        raise HTTPException(422, f"revealedGameIds max {MAX_REVEALED}")

    prefs = await _get_or_create(db, user_id)
    prefs.settings = settings
    prefs.pinned_game_ids = pinned
    prefs.revealed_game_ids = revealed
    await db.flush()

    logger.info("preferences_replaced", extra={"user_id": user_id})
    return OkResponse(updatedAt=prefs.updated_at)


@router.patch(
    "/preferences",
    response_model=OkResponse,
    summary="Partially update user preferences",
)
async def patch_preferences(
    body: PreferencesBody,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    user_id = await _get_user_id(request)
    prefs = await _get_or_create(db, user_id)

    if body.settings is not None:
        merged = {**(prefs.settings or {}), **_validate_settings(body.settings)}
        prefs.settings = merged

    if body.pinnedGameIds is not None:
        if len(body.pinnedGameIds) > MAX_PINNED:
            raise HTTPException(422, f"pinnedGameIds max {MAX_PINNED}")
        prefs.pinned_game_ids = body.pinnedGameIds

    if body.revealedGameIds is not None:
        if len(body.revealedGameIds) > MAX_REVEALED:
            raise HTTPException(422, f"revealedGameIds max {MAX_REVEALED}")
        prefs.revealed_game_ids = body.revealedGameIds

    await db.flush()

    logger.info("preferences_patched", extra={"user_id": user_id})
    return OkResponse(updatedAt=prefs.updated_at)
