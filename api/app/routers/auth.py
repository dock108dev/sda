"""Authentication endpoints for downstream consuming applications.

POST /auth/signup            — create a new user account, returns JWT
POST /auth/login             — authenticate with email/password, returns JWT
POST /auth/refresh           — exchange a valid JWT for a fresh one
POST /auth/forgot-password   — request a password reset email
POST /auth/reset-password    — reset password using a valid token
POST /auth/magic-link        — request a magic-link login email
POST /auth/magic-link/verify — exchange a magic-link token for a JWT
GET  /auth/me                — return current caller identity & role
PATCH /auth/me/email         — update own email (authenticated)
PATCH /auth/me/password      — change own password (authenticated)
DELETE /auth/me              — delete own account (authenticated)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.users import User
from app.dependencies.roles import (
    create_access_token,
    create_magic_link_token,
    create_reset_token,
    decode_magic_link_token,
    decode_reset_token,
    require_user,
    resolve_role,
)
from app.config import settings as _settings
from app.security import pwd_context as _pwd_ctx
from app.services.email import send_magic_link_email, send_password_reset_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="Password")
    remember_me: bool = Field(default=False, description="Issue a long-lived token (30 days)")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer")
    role: str = Field(..., description="User role")


class MeResponse(BaseModel):
    id: int | None = Field(None, description="User ID (null for guests)")
    email: str | None = Field(None, description="User email (null for guests)")
    role: str = Field(..., description="Current role: guest, user, or admin")


class UpdateEmailRequest(BaseModel):
    email: EmailStr = Field(..., description="New email address")
    password: str = Field(..., description="Current password for verification")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password (min 8 characters)")


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., description="Current password for verification")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(..., description="Account email address")
    redirect_url: str | None = Field(
        None,
        description="Base URL for the reset link (must be an allowed origin). Defaults to FRONTEND_URL.",
    )


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=8, description="New password (min 8 characters)")


class MagicLinkRequest(BaseModel):
    email: EmailStr = Field(..., description="Account email address")
    redirect_url: str | None = Field(
        None,
        description="Base URL for the magic link (must be an allowed origin). Defaults to FRONTEND_URL.",
    )


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(..., description="Magic link token from email")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_redirect_url(redirect_url: str | None) -> str:
    """Return the redirect base URL, validated against ALLOWED_CORS_ORIGINS.

    Falls back to FRONTEND_URL when *redirect_url* is ``None`` or not in the
    allowlist.  This prevents phishing via arbitrary redirect URLs.
    """
    if redirect_url is None:
        return _settings.frontend_url

    # Strip trailing slash for comparison
    candidate = redirect_url.rstrip("/")
    allowed = {o.rstrip("/") for o in _settings.allowed_cors_origins}
    allowed.add(_settings.frontend_url.rstrip("/"))

    if candidate in allowed:
        return candidate
    return _settings.frontend_url


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
)
async def signup(
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    # Check for existing email
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
        role="user",
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()  # populate user.id
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    token = create_access_token(user.id, user.role)
    logger.info("user_signup", extra={"user_id": user.id, "email": user.email})

    return TokenResponse(access_token=token, role=user.role)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive a JWT",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await db.execute(
        select(User).where(User.email == body.email.lower())
    )
    user = result.scalar_one_or_none()

    if user is None or not _pwd_ctx.verify(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    token = create_access_token(user.id, user.role, remember_me=body.remember_me)
    logger.info("user_login", extra={"user_id": user.id, "email": user.email, "remember_me": body.remember_me})

    return TokenResponse(access_token=token, role=user.role)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh an access token",
    description=(
        "Accepts a valid (non-expired) JWT via the Authorization header "
        "and returns a fresh token with a new expiration. Preserves the "
        "TTL tier — remember-me tokens produce new remember-me tokens."
    ),
)
async def refresh_token(
    request: Request,
    _role: str = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    # Preserve TTL tier — resolve_role stashes the rm claim on request.state
    remember_me = getattr(request.state, "remember_me", False)
    token = create_access_token(user.id, user.role, remember_me=remember_me)

    logger.info("token_refreshed", extra={"user_id": user.id, "remember_me": remember_me})
    return TokenResponse(access_token=token, role=user.role)


@router.post(
    "/forgot-password",
    summary="Request a password reset token",
    description=(
        "Accepts an email address. If a matching active account exists, "
        "generates a short-lived reset token. The response always returns "
        "200 to avoid leaking whether the email is registered."
    ),
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(
        select(User).where(User.email == body.email.lower())
    )
    user = result.scalar_one_or_none()

    if user is not None and user.is_active:
        token = create_reset_token(user.id)
        base_url = _resolve_redirect_url(body.redirect_url)
        logger.info(
            "password_reset_requested",
            extra={"user_id": user.id},
        )
        try:
            await send_password_reset_email(to=user.email, token=token, base_url=base_url)
        except Exception as exc:
            logger.debug("password_reset_email_delivery_failed", extra={"error": str(exc)})
    else:
        # Log but don't reveal whether the account exists
        logger.info(
            "password_reset_no_match",
            extra={"email": body.email.lower()},
        )

    return {"detail": "If that email is registered, a reset link has been sent."}


@router.post(
    "/reset-password",
    summary="Reset password using a valid token",
)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        user_id = decode_reset_token(body.token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user.password_hash = _pwd_ctx.hash(body.new_password)
    await db.flush()

    logger.info("password_reset_completed", extra={"user_id": user.id})
    return {"detail": "Password has been reset."}


@router.post(
    "/magic-link",
    summary="Request a magic-link login email",
    description=(
        "Accepts an email address. If a matching active account exists, "
        "sends a short-lived login link via email. The response always "
        "returns 200 to avoid leaking whether the email is registered."
    ),
)
async def request_magic_link(
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(
        select(User).where(User.email == body.email.lower())
    )
    user = result.scalar_one_or_none()

    if user is not None and user.is_active:
        token = create_magic_link_token(user.id)
        base_url = _resolve_redirect_url(body.redirect_url)
        logger.info(
            "magic_link_requested",
            extra={"user_id": user.id},
        )
        try:
            await send_magic_link_email(to=user.email, token=token, base_url=base_url)
        except Exception as exc:
            logger.debug("magic_link_email_delivery_failed", extra={"error": str(exc)})
    else:
        logger.info(
            "magic_link_no_match",
            extra={"email": body.email.lower()},
        )

    return {"detail": "If that email is registered, a sign-in link has been sent."}


@router.post(
    "/magic-link/verify",
    response_model=TokenResponse,
    summary="Exchange a magic-link token for a JWT",
)
async def verify_magic_link(
    body: MagicLinkVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        user_id = decode_magic_link_token(body.token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired magic link",
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired magic link",
        )

    token = create_access_token(user.id, user.role)
    logger.info("magic_link_login", extra={"user_id": user.id, "email": user.email})
    return TokenResponse(access_token=token, role=user.role)


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user identity",
    description=(
        "Returns the caller's identity and role. Guests (no token) "
        "receive ``{role: 'guest'}``. Authenticated callers receive "
        "their user ID, email, and role."
    ),
)
async def me(
    request: Request,
    role: str = Depends(resolve_role),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    if role == "guest":
        return MeResponse(role="guest")

    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        return MeResponse(role=role)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return MeResponse(role=role)

    return MeResponse(id=user.id, email=user.email, role=user.role)


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
