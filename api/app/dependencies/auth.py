"""API key authentication dependency."""

from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.config import settings

logger = logging.getLogger(__name__)

# Header name for API key
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: str | None = Depends(API_KEY_HEADER),
) -> str:
    """Validate API key from request header.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        request: The incoming request (for logging context).
        api_key: The API key from the X-API-Key header.

    Returns:
        The validated API key.

    Raises:
        HTTPException: 401 if key is missing or invalid.
    """
    if not settings.api_key:
        # Fail-fast in production/staging - never allow unauthenticated access
        if settings.environment in {"production", "staging"}:
            logger.error(
                "API_KEY not configured in production/staging - rejecting request"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server authentication misconfigured",
            )
        # In development, allow unauthenticated requests with a warning
        logger.warning("API_KEY not configured - allowing unauthenticated request (dev mode)")
        return ""

    if not api_key:
        logger.warning(
            "Missing API key",
            extra={
                "client_ip": request.client.host if request.client else "unknown",
                "path": request.url.path,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Scope check: if a separate CONSUMER_API_KEY is configured, reject it here.
    # This prevents consumer keys from accessing admin routes.
    consumer_key = settings.consumer_api_key
    if consumer_key and secrets.compare_digest(api_key, consumer_key):
        # Only reject if it's NOT also the admin key (single-key setups are fine).
        if not settings.api_key or not secrets.compare_digest(api_key, settings.api_key):
            logger.warning(
                "Consumer API key used on admin route",
                extra={
                    "client_ip": request.client.host if request.client else "unknown",
                    "path": request.url.path,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Consumer API key is not authorized for admin routes",
            )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, settings.api_key):
        logger.warning(
            "Invalid API key attempt",
            extra={
                "client_ip": request.client.host if request.client else "unknown",
                "path": request.url.path,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Mark request as API-key-authenticated so resolve_role() can grant
    # admin access without requiring an Origin header match.
    request.state.api_key_verified = True

    return api_key
