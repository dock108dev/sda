"""Tests for realtime/ws.py — WebSocket endpoint."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketState

from app.realtime.ws import websocket_endpoint


class TestWebsocketEndpoint:
    @pytest.mark.asyncio
    @patch("app.realtime.ws.verify_ws_api_key", return_value=False)
    async def test_rejects_unauthorized(self, mock_auth):
        ws = AsyncMock()
        await websocket_endpoint(ws)
        ws.close.assert_called_once_with(code=4401, reason="Unauthorized")
        ws.accept.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_accepts_and_processes_subscribe(self, mock_auth, mock_mgr):
        ws = AsyncMock()
        mock_mgr.subscribe.return_value = True

        # After receiving one message, raise disconnect
        from fastapi import WebSocketDisconnect
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "subscribe", "channels": ["game:1:summary"]}),
            WebSocketDisconnect(),
        ])
        ws.client_state = WebSocketState.CONNECTED

        await websocket_endpoint(ws)
        ws.accept.assert_called_once()
        mock_mgr.subscribe.assert_called_once()
        ws.send_json.assert_any_call({"type": "subscribed", "channels": ["game:1:summary"]})

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_subscribe_rejected_channels(self, mock_auth, mock_mgr):
        from fastapi import WebSocketDisconnect
        ws = AsyncMock()
        mock_mgr.subscribe.return_value = False

        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "subscribe", "channels": ["game:1:summary"]}),
            WebSocketDisconnect(),
        ])

        await websocket_endpoint(ws)
        # Rejected channel should appear
        call_args = [c[0][0] for c in ws.send_json.call_args_list]
        subscribe_resp = next(r for r in call_args if r.get("type") == "subscribed")
        assert subscribe_resp["rejected"] == ["game:1:summary"]

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_unsubscribe(self, mock_auth, mock_mgr):
        from fastapi import WebSocketDisconnect
        ws = AsyncMock()

        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "unsubscribe", "channels": ["game:1:summary"]}),
            WebSocketDisconnect(),
        ])

        await websocket_endpoint(ws)
        mock_mgr.unsubscribe.assert_called_once()
        call_args = [c[0][0] for c in ws.send_json.call_args_list]
        assert any(r.get("type") == "unsubscribed" for r in call_args)

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_invalid_json(self, mock_auth, mock_mgr):
        from fastapi import WebSocketDisconnect
        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            "not json{{{",
            WebSocketDisconnect(),
        ])
        await websocket_endpoint(ws)
        call_args = [c[0][0] for c in ws.send_json.call_args_list]
        assert any(r.get("type") == "error" for r in call_args)

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_message_too_large(self, mock_auth, mock_mgr):
        from fastapi import WebSocketDisconnect
        ws = AsyncMock()
        big_msg = "x" * (256 * 1024 + 1)
        ws.receive_text = AsyncMock(side_effect=[big_msg, WebSocketDisconnect()])
        await websocket_endpoint(ws)
        call_args = [c[0][0] for c in ws.send_json.call_args_list]
        assert any("too large" in str(r.get("message", "")) for r in call_args)

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_unknown_message_type(self, mock_auth, mock_mgr):
        from fastapi import WebSocketDisconnect
        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "bogus"}),
            WebSocketDisconnect(),
        ])
        await websocket_endpoint(ws)
        call_args = [c[0][0] for c in ws.send_json.call_args_list]
        assert any("Unknown type" in str(r.get("message", "")) for r in call_args)

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_channels_not_array(self, mock_auth, mock_mgr):
        from fastapi import WebSocketDisconnect
        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "subscribe", "channels": "not_list"}),
            WebSocketDisconnect(),
        ])
        await websocket_endpoint(ws)
        call_args = [c[0][0] for c in ws.send_json.call_args_list]
        assert any("array" in str(r.get("message", "")) for r in call_args)

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_pong_is_noop(self, mock_auth, mock_mgr):
        from fastapi import WebSocketDisconnect
        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "pong"}),
            WebSocketDisconnect(),
        ])
        await websocket_endpoint(ws)
        # Should not error, disconnect is clean
        mock_mgr.disconnect.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.realtime.ws.realtime_manager")
    @patch("app.realtime.ws.verify_ws_api_key", return_value=True)
    async def test_generic_exception_disconnects(self, mock_auth, mock_mgr):
        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=RuntimeError("boom"))
        await websocket_endpoint(ws)
        mock_mgr.disconnect.assert_called_once()
