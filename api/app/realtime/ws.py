"""WebSocket endpoint for realtime subscriptions.

URL: /v1/ws
Auth: X-API-Key header or api_key query param
Protocol: JSON messages (subscribe/unsubscribe)
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .auth import verify_ws_api_key
from .manager import WSConnection, realtime_manager
from .models import is_valid_channel

logger = logging.getLogger(__name__)

router = APIRouter()

WS_PING_INTERVAL_S = 25
MAX_MESSAGE_SIZE = 256 * 1024  # 256 KB


@router.websocket("/v1/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket realtime endpoint."""
    # Auth check before accepting
    if not await verify_ws_api_key(websocket):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    conn = WSConnection(websocket)
    logger.info("ws_connected", extra={"conn": conn.id})

    # Keepalive ping task
    async def _ping_loop() -> None:
        try:
            while True:
                await asyncio.sleep(WS_PING_INTERVAL_S)
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json({"type": "ping"})
        except asyncio.CancelledError:
            pass  # expected on shutdown
        except Exception as exc:
            logger.debug("ws_ping_loop_error", extra={"error": str(exc)})

    ping_task = asyncio.create_task(_ping_loop())

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_MESSAGE_SIZE:
                await websocket.send_json({"type": "error", "message": "Message too large"})
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type")
            channels = msg.get("channels", [])

            if not isinstance(channels, list):
                await websocket.send_json({"type": "error", "message": "channels must be an array"})
                continue

            if msg_type == "subscribe":
                subscribed = []
                rejected = []
                for ch in channels:
                    if not isinstance(ch, str):
                        continue
                    if not is_valid_channel(ch):
                        rejected.append(ch)
                        continue
                    ok = realtime_manager.subscribe(conn, ch)
                    if ok:
                        subscribed.append(ch)
                    else:
                        rejected.append(ch)

                resp: dict = {"type": "subscribed", "channels": subscribed}
                if rejected:
                    resp["rejected"] = rejected
                await websocket.send_json(resp)

            elif msg_type == "unsubscribe":
                for ch in channels:
                    if isinstance(ch, str):
                        realtime_manager.unsubscribe(conn, ch)
                await websocket.send_json({"type": "unsubscribed", "channels": channels})

            elif msg_type == "pong":
                pass  # Client keepalive response — no action needed

            else:
                await websocket.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("ws_disconnected", extra={"conn": conn.id})
    except Exception:
        logger.exception("ws_error", extra={"conn": conn.id})
    finally:
        ping_task.cancel()
        try:
            await asyncio.wait_for(ping_task, timeout=1.0)
        except (TimeoutError, asyncio.CancelledError):
            pass
        realtime_manager.disconnect(conn)
