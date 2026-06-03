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

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.audit as audit
from app.config import settings as _settings
from app.db import get_db
from app.db.magic_link import MagicLinkToken
from app.db.users import User
from app.dependencies.roles import (
    create_access_token,
    create_reset_token,
    decode_reset_token,
    require_user,
    resolve_role,
)
from app.security import pwd_context as _pwd_ctx
from app.services.email import send_magic_link_email, send_password_reset_email

from .auth_schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MagicLinkRequest,
    MagicLinkVerifyRequest,
    MeResponse,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
)
from .auth_self_service import router as self_service_router

_MAGIC_LINK_TTL = timedelta(minutes=15)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

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
            logger.warning("password_reset_email_delivery_failed", extra={"error": str(exc)}, exc_info=True)
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
        "generates a short-lived DB-tracked token, invalidates any prior "
        "active token for that email, and sends a login link. The response "
        "always returns 200 to avoid leaking whether the email is registered."
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
        # Invalidate any prior active tokens for this email (one-per-email enforcement).
        await db.execute(
            sa_update(MagicLinkToken)
            .where(
                MagicLinkToken.email == user.email,
                MagicLinkToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        db_token = MagicLinkToken(
            email=user.email,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + _MAGIC_LINK_TTL,
        )
        db.add(db_token)
        await db.flush()

        base_url = _resolve_redirect_url(body.redirect_url)
        logger.info("magic_link_requested", extra={"user_id": user.id})
        audit.emit(
            "magic_link_issued",
            actor_type="system",
            actor_id=str(user.id),
            resource_type="magic_link",
            resource_id=str(user.id),
            payload={"user_id": user.id},
        )
        try:
            await send_magic_link_email(to=user.email, token=raw_token, base_url=base_url)
        except Exception as exc:
            logger.warning("magic_link_email_delivery_failed", extra={"error": str(exc)}, exc_info=True)
    else:
        logger.info("magic_link_no_match", extra={"email": body.email.lower()})

    return {"detail": "If that email is registered, a sign-in link has been sent."}


async def _exchange_magic_link_token(token: str, db: AsyncSession) -> TokenResponse:
    """Validate a raw magic-link token, mark it used, and return a JWT."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await db.execute(
        select(MagicLinkToken)
        .where(MagicLinkToken.token_hash == token_hash)
        .with_for_update()
    )
    ml_token = result.scalar_one_or_none()

    if ml_token is None or ml_token.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired magic link",
        )

    now = datetime.now(UTC)
    expires_at = ml_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if now >= expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired magic link",
        )

    ml_token.used_at = now
    await db.flush()

    user_result = await db.execute(select(User).where(User.email == ml_token.email))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired magic link",
        )

    access_token = create_access_token(user.id, user.role)
    logger.info("magic_link_login", extra={"user_id": user.id, "email": user.email})
    return TokenResponse(access_token=access_token, role=user.role)


@router.get(
    "/magic-link/verify",
    response_model=TokenResponse,
    summary="Exchange a magic-link token for a JWT (GET, token as query param)",
)
async def verify_magic_link_get(
    token: str = Query(..., description="Raw magic-link token from the email link"),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await _exchange_magic_link_token(token, db)


@router.post(
    "/magic-link/verify",
    response_model=TokenResponse,
    summary="Exchange a magic-link token for a JWT",
)
async def verify_magic_link(
    body: MagicLinkVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await _exchange_magic_link_token(body.token, db)


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

router.include_router(self_service_router)
