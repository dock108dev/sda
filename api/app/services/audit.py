"""AuditService — fire-and-forget structured audit log writes.

All public entry points schedule work via asyncio.create_task so callers
on the hot path are never slowed or blocked by audit write failures.
Failures are swallowed and logged as warnings — never re-raised.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from app.context import request_id_var

logger = logging.getLogger(__name__)


def emit(
    event_type: str,
    *,
    actor_type: str,
    resource_type: str,
    resource_id: str,
    actor_id: str | None = None,
    club_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Schedule an audit event write without awaiting it.

    Safe to call from any async context. Failures never propagate.
    actor_type must be one of: user, webhook, system.
    """
    rid = request_id_var.get()
    merged_payload: dict[str, Any] | None = payload
    if rid:
        merged_payload = {**(payload or {}), "request_id": rid}

    asyncio.create_task(
        _write(
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            club_id=club_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=merged_payload,
        )
    )


async def _write(
    event_type: str,
    actor_type: str,
    resource_type: str,
    resource_id: str,
    actor_id: str | None,
    club_id: int | None,
    payload: dict[str, Any] | None,
) -> None:
    try:
        from app.db import get_async_session
        from app.db.audit import AuditEvent

        async with get_async_session() as db:
            db.add(
                AuditEvent(
                    event_id=str(uuid4()),
                    event_type=event_type,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    club_id=club_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    payload=payload,
                )
            )
    except Exception:
        logger.error(
            "audit_write_failed",
            exc_info=True,
            extra={"event_type": event_type, "resource_id": resource_id},
        )
