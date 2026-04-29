"""Role-based access control dependencies.

Provides:
    resolve_role()  — returns "guest", "user", or "admin" from JWT (or admin if auth disabled)
    require_user()  — raises 403 unless role >= user
    require_admin() — raises 403 unless role == admin
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# Optional bearer token — does not auto-error so guests pass through.
_bearer_scheme = HTTPBearer(auto_error=False)

VALID_ROLES = {"guest", "user", "admin"}
_ROLE_LEVEL = {"guest": 0, "user": 1, "admin": 2}


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

_REMEMBER_ME_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days


def create_access_token(
    user_id: int,
    role: str,
    *,
    remember_me: bool = False,
) -> str:
    """Issue a signed JWT for *user_id* with the given *role*.

    When *remember_me* is True, the token lives for 30 days instead of
    the default TTL. A ``rm`` claim is embedded so the refresh endpoint
    can preserve the TTL tier.
    """
    now = datetime.now(UTC)
    ttl = (
        timedelta(minutes=_REMEMBER_ME_EXPIRE_MINUTES)
        if remember_me
        else timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + ttl,
    }
    if remember_me:
        payload["rm"] = True
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.  Raises *jwt.PyJWTError* on failure."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


_RESET_TOKEN_EXPIRE_MINUTES = 30


def create_reset_token(user_id: int) -> str:
    """Issue a short-lived JWT for password reset."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "purpose": "password_reset",
        "iat": now,
        "exp": now + timedelta(minutes=_RESET_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_reset_token(token: str) -> int:
    """Decode a password-reset JWT and return the user ID.

    Raises ``jwt.PyJWTError`` on expiry/signature failure and
    ``ValueError`` if the token is not a reset token.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("purpose") != "password_reset":
        raise ValueError("Token is not a password reset token")
    return int(payload["sub"])


_INVITE_TOKEN_EXPIRE_HOURS = 24


def create_invite_token(
    *,
    club_id: int,
    invitee_email: str,
    role: str,
    inviter_id: int,
) -> str:
    """Issue a signed JWT for a club membership invite (24-hour TTL)."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": invitee_email,
        "purpose": "club_invite",
        "club_id": club_id,
        "role": role,
        "inviter_id": inviter_id,
        "iat": now,
        "exp": now + timedelta(hours=_INVITE_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_invite_token(token: str) -> dict[str, Any]:
    """Decode a club invite JWT and return the payload.

    Raises ``jwt.PyJWTError`` on expiry/signature failure and
    ``ValueError`` if the token is not a club invite token.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("purpose") != "club_invite":
        raise ValueError("Token is not a club invite token")
    return payload


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def _is_admin_origin(request: Request) -> bool:
    """Check if request origin context matches configured admin origins.

    Accepts:
    - ``Origin`` from direct browser requests
    - ``X-Forwarded-Origin`` from internal proxy routes
    - origin parsed from ``Referer`` as a fallback
    """
    candidates: set[str] = set()
    origin = request.headers.get("origin")
    fwd_origin = request.headers.get("x-forwarded-origin")
    referer = request.headers.get("referer")
    if origin:
        candidates.add(str(origin))
    if fwd_origin:
        candidates.add(str(fwd_origin))
    if referer:
        try:
            parsed = urlparse(str(referer))
            if parsed.scheme and parsed.netloc:
                candidates.add(f"{parsed.scheme}://{parsed.netloc}")
        except ValueError:
            pass
    origins_cfg = getattr(settings, "admin_origins", ())
    if not isinstance(origins_cfg, list | tuple | set | frozenset):
        origins_cfg = ()
    allowed_origins = {str(origin) for origin in origins_cfg if origin}
    return any(candidate in allowed_origins for candidate in candidates)


async def resolve_role(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Determine the caller's role.

    * Valid JWT → role claim from the token
    * No JWT + request Origin matches ``ADMIN_ORIGINS`` → ``"admin"``
      (admin UI sits behind API-key auth and doesn't forward JWTs)
    * No JWT + unknown origin → ``"guest"``
    * ``AUTH_ENABLED=false`` → ``"admin"`` (feature-flag fallback)
    """
    if not settings.auth_enabled:
        return "admin"

    # Requests that passed API-key verification (admin proxy) are admin —
    # UNLESS the caller also supplies a JWT, in which case the JWT role wins.
    # Without this check, any authenticated user routing through the proxy
    # (which injects the admin API key on all paths) would receive admin access
    # regardless of their actual role claim.
    if getattr(request.state, "api_key_verified", False):
        if credentials is not None:
            try:
                payload = decode_access_token(credentials.credentials)
            except jwt.ExpiredSignatureError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired",
                )
            except jwt.PyJWTError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token",
                )
            role = payload.get("role", "user")
            if role not in VALID_ROLES:
                role = "user"
            try:
                request.state.user_id = int(payload["sub"])
            except (KeyError, ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token",
                )
            request.state.user_role = role
            request.state.remember_me = bool(payload.get("rm"))
            return role
        return "admin"

    if credentials is None:
        if _is_admin_origin(request):
            return "admin"
        return "guest"

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    role = payload.get("role", "user")
    if role not in VALID_ROLES:
        role = "user"

    # Stash user info on the request state for downstream use (e.g. /me)
    try:
        request.state.user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    request.state.user_role = role
    request.state.remember_me = bool(payload.get("rm"))
    return role


async def require_user(role: str = Depends(resolve_role)) -> str:
    """Raise 403 unless the caller is at least a ``user``."""
    if _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL["user"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication required",
        )
    return role


async def require_admin(role: str = Depends(resolve_role)) -> str:
    """Raise 403 unless the caller is an ``admin``."""
    if _ROLE_LEVEL.get(role, 0) < _ROLE_LEVEL["admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return role
