"""User preferences endpoints for syncing client-side settings.

GET   /auth/me/preferences  — fetch saved preferences
PUT   /auth/me/preferences  — full replace
PATCH /auth/me/preferences  — partial merge
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
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
MAX_HIDE_LEAGUES = 20
MAX_HIDE_TEAMS = 100
MAX_HIDE_VALUE_LEN = 64
SCORE_REVEAL_MODES = {"always", "onMarkRead", "blacklist"}
DEFAULT_SCORE_REVEAL_MODE = "onMarkRead"


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
            status_code=422,
            detail=f"settings may have at most {MAX_PAYLOAD_KEYS} keys",
        )
    return raw


def _normalize_score_reveal_mode(mode: str | None) -> str:
    if not mode:
        return DEFAULT_SCORE_REVEAL_MODE
    clean = mode.strip()
    if clean in SCORE_REVEAL_MODES:
        return clean
    return DEFAULT_SCORE_REVEAL_MODE


def _normalize_leagues(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail="scoreHideLeagues must contain strings",
            )
        item = str(value).strip().upper()
        if not item:
            continue
        if len(item) > MAX_HIDE_VALUE_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"scoreHideLeagues values must be <= {MAX_HIDE_VALUE_LEN} chars",
            )
        if item not in seen:
            seen.add(item)
            normalized.append(item)
    if len(normalized) > MAX_HIDE_LEAGUES:
        raise HTTPException(
            status_code=422,
            detail=f"scoreHideLeagues max {MAX_HIDE_LEAGUES}",
        )
    return normalized


def _normalize_teams(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail="scoreHideTeams must contain strings",
            )
        item = str(value).strip()
        if not item:
            continue
        if len(item) > MAX_HIDE_VALUE_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"scoreHideTeams values must be <= {MAX_HIDE_VALUE_LEN} chars",
            )
        dedupe_key = item.casefold()
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            normalized.append(item)
    if len(normalized) > MAX_HIDE_TEAMS:
        raise HTTPException(
            status_code=422,
            detail=f"scoreHideTeams max {MAX_HIDE_TEAMS}",
        )
    return normalized


def _extract_score_fields(
    incoming_settings: dict | None,
    existing_mode: str | None,
    existing_leagues: list[str] | None,
    existing_teams: list[str] | None,
) -> tuple[str, list[str], list[str], dict]:
    """Resolve canonical score fields with backward compatibility semantics."""
    settings = dict(incoming_settings or {})

    raw_mode = settings.get("scoreRevealMode")
    raw_leagues = settings.get("scoreHideLeagues")
    raw_teams = settings.get("scoreHideTeams")

    mode = (
        _normalize_score_reveal_mode(raw_mode)
        if raw_mode is not None
        else _normalize_score_reveal_mode(existing_mode)
    )
    leagues = (
        _normalize_leagues(raw_leagues)
        if raw_leagues is not None
        else _normalize_leagues(existing_leagues or [])
    )
    teams = (
        _normalize_teams(raw_teams)
        if raw_teams is not None
        else _normalize_teams(existing_teams or [])
    )

    settings["scoreRevealMode"] = mode
    settings["scoreHideLeagues"] = leagues
    settings["scoreHideTeams"] = teams
    return mode, leagues, teams, settings


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


async def _get_existing(db: AsyncSession, user_id: int) -> UserPreferences | None:
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _to_response(prefs: UserPreferences) -> PreferencesResponse:
    settings = dict(prefs.settings or {})
    mode = _normalize_score_reveal_mode(getattr(prefs, "score_reveal_mode", None))
    leagues = _normalize_leagues(getattr(prefs, "score_hide_leagues", []) or [])
    teams = _normalize_teams(getattr(prefs, "score_hide_teams", []) or [])
    settings["scoreRevealMode"] = mode
    settings["scoreHideLeagues"] = leagues
    settings["scoreHideTeams"] = teams
    return PreferencesResponse(
        settings=settings,
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
            settings={
                "scoreRevealMode": DEFAULT_SCORE_REVEAL_MODE,
                "scoreHideLeagues": [],
                "scoreHideTeams": [],
            },
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

    settings_raw = _validate_settings(body.settings or {})
    pinned = body.pinnedGameIds or []
    revealed = body.revealedGameIds or []

    if len(pinned) > MAX_PINNED:
        raise HTTPException(422, f"pinnedGameIds max {MAX_PINNED}")
    if len(revealed) > MAX_REVEALED:
        raise HTTPException(422, f"revealedGameIds max {MAX_REVEALED}")

    existing = await _get_existing(db, user_id)
    mode, leagues, teams, settings = _extract_score_fields(
        settings_raw,
        existing_mode=existing.score_reveal_mode if existing else DEFAULT_SCORE_REVEAL_MODE,
        existing_leagues=existing.score_hide_leagues if existing else [],
        existing_teams=existing.score_hide_teams if existing else [],
    )
    prefs = existing or await _get_or_create(db, user_id)
    prefs.settings = settings
    prefs.score_reveal_mode = mode
    prefs.score_hide_leagues = leagues
    prefs.score_hide_teams = teams
    prefs.pinned_game_ids = pinned
    prefs.revealed_game_ids = revealed
    await db.flush()
    await db.refresh(prefs, ["updated_at"])

    logger.info(
        "preferences_replaced",
        extra={
            "user_id": user_id,
            "score_reveal_mode": mode,
            "hide_leagues_count": len(leagues),
            "hide_teams_count": len(teams),
        },
    )
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
        mode, leagues, teams, merged = _extract_score_fields(
            merged,
            existing_mode=prefs.score_reveal_mode,
            existing_leagues=prefs.score_hide_leagues,
            existing_teams=prefs.score_hide_teams,
        )
        prefs.settings = merged
        prefs.score_reveal_mode = mode
        prefs.score_hide_leagues = leagues
        prefs.score_hide_teams = teams

    if body.pinnedGameIds is not None:
        if len(body.pinnedGameIds) > MAX_PINNED:
            raise HTTPException(422, f"pinnedGameIds max {MAX_PINNED}")
        prefs.pinned_game_ids = body.pinnedGameIds

    if body.revealedGameIds is not None:
        if len(body.revealedGameIds) > MAX_REVEALED:
            raise HTTPException(422, f"revealedGameIds max {MAX_REVEALED}")
        prefs.revealed_game_ids = body.revealedGameIds

    await db.flush()
    await db.refresh(prefs, ["updated_at"])

    logger.info(
        "preferences_patched",
        extra={
            "user_id": user_id,
            "score_reveal_mode": prefs.score_reveal_mode,
            "hide_leagues_count": len(prefs.score_hide_leagues or []),
            "hide_teams_count": len(prefs.score_hide_teams or []),
        },
    )
    return OkResponse(updatedAt=prefs.updated_at)
