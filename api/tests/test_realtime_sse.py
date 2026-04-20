"""Tests for realtime/sse.py — SSE endpoint."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.realtime.manager import SSEConnection
from app.realtime.sse import sse_endpoint


class TestSSEEndpoint:
    """Tests for the SSE endpoint handler."""

    @pytest.mark.asyncio
    @patch("app.realtime.sse.realtime_manager")
    @patch("app.realtime.sse.verify_sse_api_key")
    @patch("app.realtime.sse.is_valid_channel")
    async def test_invalid_channels_returns_400(self, mock_valid, mock_auth, mock_mgr):
        mock_auth.return_value = None
        mock_valid.return_value = False

        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        response = await sse_endpoint(request, channels="invalid:channel", _auth=None)
        assert response.status_code == 400

    @pytest.mark.asyncio
    @patch("app.realtime.sse.realtime_manager")
    @patch("app.realtime.sse.verify_sse_api_key")
    @patch("app.realtime.sse.is_valid_channel")
    async def test_valid_channels_streams(self, mock_valid, mock_auth, mock_mgr):
        mock_auth.return_value = None
        mock_valid.return_value = True

        request = MagicMock()
        # Disconnect after receiving initial subscription
        call_count = [0]
        async def fake_disconnect():
            call_count[0] += 1
            return call_count[0] > 1  # True on second call
        request.is_disconnected = fake_disconnect

        response = await sse_endpoint(
            request, channels="game:1:summary", last_seq=None, last_epoch=None, _auth=None
        )
        assert response.status_code == 200
        assert response.media_type == "text/event-stream"

        # Consume the generator to verify initial confirmation is sent
        body = b""
        async for chunk in response.body_iterator:
            body += chunk.encode() if isinstance(chunk, str) else chunk
            if b"subscribed" in body:
                break

        assert b"subscribed" in body

    @pytest.mark.asyncio
    async def test_sse_connection_queue(self):
        """SSEConnection properly enqueues events."""
        conn = SSEConnection()
        await conn.send_event('{"type": "test"}')
        msg = conn.queue.get_nowait()
        assert json.loads(msg)["type"] == "test"

    @pytest.mark.asyncio
    async def test_sse_connection_overflow(self):
        """SSEConnection raises OverflowError on queue full."""
        conn = SSEConnection()
        # Fill the queue
        for i in range(200):
            await conn.send_event(f'{{"i": {i}}}')
        with pytest.raises(OverflowError):
            await conn.send_event('{"overflow": true}')
