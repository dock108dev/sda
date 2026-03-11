"""Auth helpers for realtime endpoints (WS + SSE).

Reuses the same API key validation as the REST layer.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request, WebSocket, status

from app.config import settings

logger = logging.getLogger(__name__)


def _check_api_key(api_key: str | None, *, client_label: str) -> bool:
    """Validate an API key. Returns True if valid."""
    if not settings.api_key:
        if settings.environment in {"production", "staging"}:
            return False
        # Dev mode: allow unauthenticated
        return True

    if not api_key:
        logger.warning("realtime_auth_missing_key", extra={"client": client_label})
        return False

    return secrets.compare_digest(api_key, settings.api_key)


async def verify_ws_api_key(websocket: WebSocket) -> bool:
    """Check API key from WS query param or header.

    Returns True if valid, False if should reject.
    """
    api_key = (
        websocket.query_params.get("api_key")
        or websocket.headers.get("x-api-key")
    )
    host = websocket.client.host if websocket.client else "unknown"
    return _check_api_key(api_key, client_label=f"ws:{host}")


async def verify_sse_api_key(request: Request) -> None:
    """Validate API key for SSE endpoint. Raises 401 on failure."""
    api_key = (
        request.query_params.get("api_key")
        or request.headers.get("x-api-key")
    )
    host = request.client.host if request.client else "unknown"
    if not _check_api_key(api_key, client_label=f"sse:{host}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
