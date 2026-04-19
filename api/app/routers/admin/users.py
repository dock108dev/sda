"""Admin users management endpoints.

These endpoints are for the admin UI to manage user accounts.
Secured by the ``verify_api_key`` dependency applied at the router
level in ``main.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.users import User
from app.security import pwd_context as _pwd_ctx

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin", "users"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: str

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: str = Field(default="user", pattern="^(user|admin)$")


class UpdateRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(user|admin)$")


class SetActiveRequest(BaseModel):
    is_active: bool


class UpdateEmailRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/users",
    response_model=list[UserOut],
    summary="List all user accounts",
)
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [
        UserOut(
            id=u.id,
            email=u.email,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
        )
        for u in users
    ]


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user account (admin)",
)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    existing = await db.execute(
        select(User).where(User.email == body.email.lower())
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=body.email.lower(),
        password_hash=_pwd_ctx.hash(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    logger.info("admin_create_user", extra={"user_id": user.id, "email": user.email})

    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@router.patch(
    "/users/{user_id}/role",
    response_model=UserOut,
    summary="Change a user's role",
)
async def update_role(
    user_id: int,
    body: UpdateRoleRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = body.role
    await db.flush()

    logger.info(
        "admin_update_role",
        extra={"user_id": user.id, "new_role": body.role},
    )

    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@router.patch(
    "/users/{user_id}/active",
    response_model=UserOut,
    summary="Enable or disable a user account",
)
async def set_active(
    user_id: int,
    body: SetActiveRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = body.is_active
    await db.flush()

    action = "enabled" if body.is_active else "disabled"
    logger.info(
        f"admin_user_{action}",
        extra={"user_id": user.id},
    )

    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@router.patch(
    "/users/{user_id}/email",
    response_model=UserOut,
    summary="Change a user's email address",
)
async def update_email(
    user_id: int,
    body: UpdateEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check new email isn't taken by another user
    existing = await db.execute(
        select(User).where(User.email == body.email.lower(), User.id != user_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user.email = body.email.lower()
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    logger.info(
        "admin_update_email",
        extra={"user_id": user.id, "new_email": user.email},
    )

    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@router.patch(
    "/users/{user_id}/password",
    summary="Reset a user's password",
)
async def reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = _pwd_ctx.hash(body.password)
    await db.flush()

    logger.info("admin_reset_password", extra={"user_id": user.id})
    return {"detail": "Password reset"}


@router.delete(
    "/users/{user_id}",
    summary="Delete a user account",
)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    email = user.email
    await db.delete(user)
    await db.flush()

    logger.info("admin_delete_user", extra={"user_id": user_id, "email": email})
    return {"detail": "User deleted"}
