"""API key authentication for consumer (v1) endpoints.

Unlike verify_api_key, this dependency does NOT set api_key_verified on
request.state, so the key alone does not escalate the caller to admin role.
Consumer endpoints are read-only; role is determined solely by JWT scope.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.config import settings

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_consumer_api_key(
    request: Request,
    api_key: str | None = Depends(API_KEY_HEADER),
) -> str:
    """Validate API key for consumer endpoints (read-only scope).

    Uses CONSUMER_API_KEY when configured. Falls back to API_KEY for
    single-key setups (dev / simple deployments). When both keys are
    configured and are different, admin keys are rejected with 403.

    Raises:
        HTTPException: 401 if key is missing or invalid.
        HTTPException: 403 if an admin-scoped key is used on a consumer route.
    """
    # Resolve the expected consumer key: prefer CONSUMER_API_KEY if set.
    consumer_key = settings.consumer_api_key or settings.api_key

    if not consumer_key:
        if settings.environment in {"production", "staging"}:
            logger.error(
                "No API key configured in production/staging - rejecting request"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server authentication misconfigured",
            )
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

    # Scope check: if both keys are configured and differ, reject admin keys.
    admin_key = settings.api_key
    if settings.consumer_api_key and admin_key and settings.consumer_api_key != admin_key:
        if secrets.compare_digest(api_key, admin_key) and not secrets.compare_digest(
            api_key, settings.consumer_api_key
        ):
            logger.warning(
                "Admin API key used on consumer route",
                extra={
                    "client_ip": request.client.host if request.client else "unknown",
                    "path": request.url.path,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin API key is not authorized for consumer routes",
            )

    if not secrets.compare_digest(api_key, consumer_key):
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

    # Intentionally do NOT set request.state.api_key_verified = True.
    # That flag causes resolve_role() to grant admin, which is not
    # appropriate for the consumer API surface.
    return api_key
