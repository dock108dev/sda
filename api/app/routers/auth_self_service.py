"""Authenticated account-management routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.users import User
from app.dependencies.roles import require_user
from app.security import pwd_context as _pwd_ctx

from .auth_schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    MeResponse,
    UpdateEmailRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Self-service account management (requires authentication)
# ---------------------------------------------------------------------------

async def _get_authenticated_user(
    request: Request,
    db: AsyncSession,
) -> User:
    """Fetch the authenticated user or raise 401."""
    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.patch(
    "/me/email",
    response_model=MeResponse,
    summary="Update own email address",
    description="Requires current password for verification.",
)
async def update_email(
    body: UpdateEmailRequest,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    user = await _get_authenticated_user(request, db)

    if not _pwd_ctx.verify(body.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Invalid password")

    # Check new email isn't taken
    existing = await db.execute(
        select(User).where(User.email == body.email.lower(), User.id != user.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user.email = body.email.lower()
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    logger.info("user_email_updated", extra={"user_id": user.id, "new_email": user.email})
    return MeResponse(id=user.id, email=user.email, role=user.role)


@router.patch(
    "/me/password",
    summary="Change own password",
)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user = await _get_authenticated_user(request, db)

    if not _pwd_ctx.verify(body.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Invalid current password")

    user.password_hash = _pwd_ctx.hash(body.new_password)
    await db.flush()

    logger.info("user_password_changed", extra={"user_id": user.id})
    return {"detail": "Password updated"}


@router.delete(
    "/me",
    status_code=status.HTTP_200_OK,
    summary="Delete own account",
    description="Permanently deletes the account. Requires password confirmation.",
)
async def delete_account(
    body: DeleteAccountRequest,
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user = await _get_authenticated_user(request, db)

    if not _pwd_ctx.verify(body.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Invalid password")

    await db.delete(user)
    await db.flush()

    logger.info("user_account_deleted", extra={"user_id": user.id, "email": user.email})
    return {"detail": "Account deleted"}
