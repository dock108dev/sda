"""Tests for realtime/auth.py — API key validation for WS and SSE."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.realtime.auth import _check_api_key, verify_sse_api_key, verify_ws_api_key


class TestCheckApiKey:
    @patch("app.realtime.auth.settings")
    def test_no_key_configured_dev_allows(self, mock_settings):
        mock_settings.api_key = ""
        mock_settings.environment = "development"
        assert _check_api_key(None, client_label="test") is True

    @patch("app.realtime.auth.settings")
    def test_no_key_configured_prod_denies(self, mock_settings):
        mock_settings.api_key = ""
        mock_settings.environment = "production"
        assert _check_api_key(None, client_label="test") is False

    @patch("app.realtime.auth.settings")
    def test_no_key_configured_staging_denies(self, mock_settings):
        mock_settings.api_key = ""
        mock_settings.environment = "staging"
        assert _check_api_key(None, client_label="test") is False

    @patch("app.realtime.auth.settings")
    def test_valid_key(self, mock_settings):
        mock_settings.api_key = "secret123"
        assert _check_api_key("secret123", client_label="test") is True

    @patch("app.realtime.auth.settings")
    def test_invalid_key(self, mock_settings):
        mock_settings.api_key = "secret123"
        assert _check_api_key("wrong", client_label="test") is False

    @patch("app.realtime.auth.settings")
    def test_missing_key_when_configured(self, mock_settings):
        mock_settings.api_key = "secret123"
        assert _check_api_key(None, client_label="test") is False


class TestVerifyWsApiKey:
    @pytest.mark.asyncio
    @patch("app.realtime.auth.settings")
    async def test_from_query_param(self, mock_settings):
        mock_settings.api_key = "key123"
        ws = MagicMock()
        ws.query_params = {"api_key": "key123"}
        ws.headers = {}
        ws.client = MagicMock()
        ws.client.host = "127.0.0.1"
        assert await verify_ws_api_key(ws) is True

    @pytest.mark.asyncio
    @patch("app.realtime.auth.settings")
    async def test_from_header(self, mock_settings):
        mock_settings.api_key = "key123"
        ws = MagicMock()
        ws.query_params = {}
        ws.headers = {"x-api-key": "key123"}
        ws.client = MagicMock()
        ws.client.host = "127.0.0.1"
        assert await verify_ws_api_key(ws) is True

    @pytest.mark.asyncio
    @patch("app.realtime.auth.settings")
    async def test_no_client(self, mock_settings):
        mock_settings.api_key = ""
        mock_settings.environment = "development"
        ws = MagicMock()
        ws.query_params = {}
        ws.headers = {}
        ws.client = None
        assert await verify_ws_api_key(ws) is True


class TestVerifySseApiKey:
    @pytest.mark.asyncio
    @patch("app.realtime.auth.settings")
    async def test_valid_key(self, mock_settings):
        mock_settings.api_key = "ssekey"
        request = MagicMock()
        request.query_params = {"api_key": "ssekey"}
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        # Should not raise
        await verify_sse_api_key(request)

    @pytest.mark.asyncio
    @patch("app.realtime.auth.settings")
    async def test_invalid_key_raises(self, mock_settings):
        mock_settings.api_key = "ssekey"
        request = MagicMock()
        request.query_params = {}
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        with pytest.raises(HTTPException) as exc_info:
            await verify_sse_api_key(request)
        assert exc_info.value.status_code == 401
