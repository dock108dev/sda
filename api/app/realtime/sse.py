"""Server-Sent Events endpoint for realtime subscriptions.

URL: GET /v1/sse?channels=games:NBA:2026-03-05,game:123:summary
Auth: X-API-Key header or api_key query param
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import StreamingResponse

from .auth import verify_sse_api_key
from .manager import SSEConnection, realtime_manager
from .models import is_valid_channel

logger = logging.getLogger(__name__)

router = APIRouter()

SSE_KEEPALIVE_INTERVAL_S = 15


@router.get("/v1/sse")
async def sse_endpoint(
    request: Request,
    channels: str = Query(..., description="Comma-separated channel list"),
    _auth: None = Depends(verify_sse_api_key),
) -> StreamingResponse:
    """SSE realtime endpoint.

    Streams JSON events as `data:` lines. Sends keepalive comments every 15s.
    """
    channel_list = [ch.strip() for ch in channels.split(",") if ch.strip()]

    # Validate channels upfront
    valid = [ch for ch in channel_list if is_valid_channel(ch)]
    if not valid:
        return StreamingResponse(
            iter(["data: {\"type\":\"error\",\"message\":\"No valid channels\"}\n\n"]),
            media_type="text/event-stream",
            status_code=400,
        )

    conn = SSEConnection()

    for ch in valid:
        realtime_manager.subscribe(conn, ch)

    logger.info(
        "sse_connected",
        extra={"conn": conn.id, "channels": valid},
    )

    async def _event_generator():
        try:
            # Send initial confirmation
            confirm = json.dumps({"type": "subscribed", "channels": valid})
            yield f"data: {confirm}\n\n"

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    # Wait for event or timeout for keepalive
                    data = await asyncio.wait_for(
                        conn.queue.get(),
                        timeout=SSE_KEEPALIVE_INTERVAL_S,
                    )
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("sse_stream_error", extra={"conn": conn.id})
        finally:
            realtime_manager.disconnect(conn)
            logger.info("sse_disconnected", extra={"conn": conn.id})

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
