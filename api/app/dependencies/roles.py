"""Role-based access control dependencies.

Provides:
    resolve_role()  — returns "guest", "user", or "admin" from JWT (or admin if auth disabled)
    require_user()  — raises 403 unless role >= user
    require_admin() — raises 403 unless role == admin
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

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

def create_access_token(user_id: int, role: str) -> str:
    """Issue a signed JWT for *user_id* with the given *role*."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
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


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def resolve_role(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Determine the caller's role.

    * No ``Authorization`` header → ``"guest"``
    * Valid JWT → role claim from the token
    * ``AUTH_ENABLED=false`` → ``"admin"`` (feature-flag fallback)
    """
    if not settings.auth_enabled:
        return "admin"

    if credentials is None:
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
