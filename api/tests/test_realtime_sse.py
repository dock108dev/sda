"""Tests for realtime/sse.py — SSE endpoint."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.realtime.manager import SSEConnection
from app.realtime.models import MAX_CHANNELS_PER_CONNECTION
from app.realtime.sse import sse_endpoint


def _run(coro):
    """Run a coroutine to completion without requiring pytest-asyncio."""
    return asyncio.run(coro)


class TestSSEEndpoint:
    """Tests for the SSE endpoint handler."""

    @patch("app.realtime.sse.realtime_manager")
    @patch("app.realtime.sse.verify_sse_api_key")
    @patch("app.realtime.sse.is_valid_channel")
    def test_invalid_channels_returns_400_json(self, mock_valid, mock_auth, mock_mgr):
        mock_auth.return_value = None
        mock_valid.return_value = False

        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        response = _run(sse_endpoint(request, channels="invalid:channel", _auth=None))
        assert response.status_code == 400
        assert response.media_type == "application/json"
        assert json.loads(response.body) == {
            "type": "error",
            "message": "No valid channels",
        }

    @patch("app.realtime.sse.realtime_manager")
    @patch("app.realtime.sse.verify_sse_api_key")
    def test_too_many_channels_returns_400_json(self, mock_auth, mock_mgr):
        mock_auth.return_value = None

        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)
        channels = ",".join(
            f"game:{i}:summary" for i in range(MAX_CHANNELS_PER_CONNECTION + 1)
        )

        response = _run(sse_endpoint(request, channels=channels, _auth=None))

        assert response.status_code == 400
        assert response.media_type == "application/json"
        assert json.loads(response.body) == {
            "type": "error",
            "message": "Too many channels",
        }

    @patch("app.realtime.sse.realtime_manager")
    @patch("app.realtime.sse.verify_sse_api_key")
    @patch("app.realtime.sse.is_valid_channel")
    def test_valid_channels_streams(self, mock_valid, mock_auth, mock_mgr):
        mock_auth.return_value = None
        mock_valid.return_value = True

        request = MagicMock()
        # Disconnect after receiving initial subscription
        call_count = [0]
        async def fake_disconnect():
            call_count[0] += 1
            return call_count[0] > 1  # True on second call
        request.is_disconnected = fake_disconnect

        async def run():
            response = await sse_endpoint(
                request, channels="game:1:summary", last_seq=None, last_epoch=None, _auth=None
            )
            body = b""
            async for chunk in response.body_iterator:
                body += chunk.encode() if isinstance(chunk, str) else chunk
                if b"subscribed" in body:
                    break
            return response, body

        response, body = _run(run())

        assert response.status_code == 200
        assert response.media_type == "text/event-stream"
        assert b"subscribed" in body

    def test_sse_connection_queue(self):
        """SSEConnection properly enqueues events."""

        async def run():
            conn = SSEConnection()
            await conn.send_event('{"type": "test"}')
            msg = conn.queue.get_nowait()
            assert json.loads(msg)["type"] == "test"

        _run(run())

    def test_sse_connection_overflow(self):
        """SSEConnection raises OverflowError on queue full."""

        async def run():
            conn = SSEConnection()
            # Fill the queue
            for i in range(200):
                await conn.send_event(f'{{"i": {i}}}')
            try:
                await conn.send_event('{"overflow": true}')
            except OverflowError:
                return
            raise AssertionError("expected OverflowError")

        _run(run())
