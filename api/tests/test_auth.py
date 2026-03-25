"""Tests for API key authentication dependency."""

from __future__ import annotations

import secrets
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.dependencies.auth import verify_api_key


class TestVerifyApiKey:
    """Tests for verify_api_key dependency."""

    @pytest.fixture
    def mock_request(self) -> MagicMock:
        """Create a mock FastAPI request."""
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.url.path = "/api/test"
        return request

    @pytest.fixture
    def mock_request_no_client(self) -> MagicMock:
        """Create a mock request with no client info."""
        request = MagicMock()
        request.client = None
        request.url.path = "/api/test"
        return request

    @pytest.mark.asyncio
    async def test_valid_api_key_accepted(self, mock_request: MagicMock) -> None:
        """Valid API key returns the key."""
        test_key = "a" * 32  # Valid 32-char key
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = test_key

            result = await verify_api_key(mock_request, test_key)

            assert result == test_key

    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self, mock_request: MagicMock) -> None:
        """Invalid API key raises 401 Unauthorized."""
        configured_key = "correct_key_" + "x" * 20
        provided_key = "wrong_key_" + "y" * 22

        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = configured_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(mock_request, provided_key)

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "Invalid API key"
            assert exc_info.value.headers == {"WWW-Authenticate": "ApiKey"}

    @pytest.mark.asyncio
    async def test_missing_api_key_rejected(self, mock_request: MagicMock) -> None:
        """Missing API key raises 401 Unauthorized."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = "configured_key_" + "x" * 18

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(mock_request, None)

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "Missing API key"
            assert exc_info.value.headers == {"WWW-Authenticate": "ApiKey"}

    @pytest.mark.asyncio
    async def test_empty_string_api_key_rejected(self, mock_request: MagicMock) -> None:
        """Empty string API key raises 401 Unauthorized."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = "configured_key_" + "x" * 18

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(mock_request, "")

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "Missing API key"

    @pytest.mark.asyncio
    async def test_dev_mode_no_api_key_configured(
        self, mock_request: MagicMock
    ) -> None:
        """When no API key configured (dev mode), requests are allowed."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = None
            mock_settings.environment = "development"

            result = await verify_api_key(mock_request, None)

            assert result == ""

    @pytest.mark.asyncio
    async def test_dev_mode_empty_api_key_configured(
        self, mock_request: MagicMock
    ) -> None:
        """When API key is empty string (dev mode), requests are allowed."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.environment = "development"

            result = await verify_api_key(mock_request, None)

            assert result == ""

    @pytest.mark.asyncio
    async def test_dev_mode_logs_warning(self, mock_request: MagicMock) -> None:
        """Dev mode logs a warning about unauthenticated request."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = None
            mock_settings.environment = "development"

            with patch("app.dependencies.auth.logger") as mock_logger:
                await verify_api_key(mock_request, None)

                mock_logger.warning.assert_called_once_with(
                    "API_KEY not configured - allowing unauthenticated request (dev mode)"
                )

    @pytest.mark.asyncio
    async def test_production_no_api_key_returns_500(
        self, mock_request: MagicMock
    ) -> None:
        """Production environment without API key configured returns 500."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = None
            mock_settings.environment = "production"

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(mock_request, None)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Server authentication misconfigured"

    @pytest.mark.asyncio
    async def test_staging_no_api_key_returns_500(
        self, mock_request: MagicMock
    ) -> None:
        """Staging environment without API key configured returns 500."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = None
            mock_settings.environment = "staging"

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(mock_request, None)

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == "Server authentication misconfigured"

    @pytest.mark.asyncio
    async def test_missing_key_logs_warning_with_context(
        self, mock_request: MagicMock
    ) -> None:
        """Missing API key logs warning with client IP and path."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = "configured_key_" + "x" * 18

            with patch("app.dependencies.auth.logger") as mock_logger:
                with pytest.raises(HTTPException):
                    await verify_api_key(mock_request, None)

                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert call_args[0][0] == "Missing API key"
                assert call_args[1]["extra"]["client_ip"] == "127.0.0.1"
                assert call_args[1]["extra"]["path"] == "/api/test"

    @pytest.mark.asyncio
    async def test_invalid_key_logs_warning_with_context(
        self, mock_request: MagicMock
    ) -> None:
        """Invalid API key logs warning with client IP and path."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = "correct_key_" + "x" * 20

            with patch("app.dependencies.auth.logger") as mock_logger:
                with pytest.raises(HTTPException):
                    await verify_api_key(mock_request, "wrong_key")

                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert call_args[0][0] == "Invalid API key attempt"
                assert call_args[1]["extra"]["client_ip"] == "127.0.0.1"
                assert call_args[1]["extra"]["path"] == "/api/test"

    @pytest.mark.asyncio
    async def test_no_client_info_logs_unknown_ip(
        self, mock_request_no_client: MagicMock
    ) -> None:
        """When request has no client info, logs 'unknown' for IP."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = "configured_key_" + "x" * 18

            with patch("app.dependencies.auth.logger") as mock_logger:
                with pytest.raises(HTTPException):
                    await verify_api_key(mock_request_no_client, None)

                call_args = mock_logger.warning.call_args
                assert call_args[1]["extra"]["client_ip"] == "unknown"


class TestConstantTimeComparison:
    """Tests for constant-time comparison behavior."""

    @pytest.fixture
    def mock_request(self) -> MagicMock:
        """Create a mock FastAPI request."""
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.url.path = "/api/test"
        return request

    @pytest.mark.asyncio
    async def test_uses_secrets_compare_digest(self, mock_request: MagicMock) -> None:
        """Verify secrets.compare_digest is used for comparison."""
        test_key = "a" * 32

        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = test_key

            with patch("app.dependencies.auth.secrets.compare_digest") as mock_compare:
                mock_compare.return_value = True

                await verify_api_key(mock_request, test_key)

                mock_compare.assert_called_once_with(test_key, test_key)

    @pytest.mark.asyncio
    async def test_compare_digest_false_raises_401(
        self, mock_request: MagicMock
    ) -> None:
        """When compare_digest returns False, raises 401."""
        with patch("app.dependencies.auth.settings") as mock_settings:
            mock_settings.api_key = "configured_key"

            with patch("app.dependencies.auth.secrets.compare_digest") as mock_compare:
                mock_compare.return_value = False

                with pytest.raises(HTTPException) as exc_info:
                    await verify_api_key(mock_request, "any_key")

                assert exc_info.value.status_code == 401

    def test_compare_digest_timing_attack_resistance(self) -> None:
        """Verify secrets.compare_digest provides timing attack resistance.

        This test documents that we use the stdlib's constant-time comparison.
        The actual timing properties are guaranteed by the Python stdlib.
        """
        correct_key = "a" * 64
        wrong_key_similar = "a" * 63 + "b"
        wrong_key_different = "b" * 64

        # All comparisons should use constant time regardless of similarity
        # We're testing that secrets.compare_digest is the function being used
        result_correct = secrets.compare_digest(correct_key, correct_key)
        result_similar = secrets.compare_digest(correct_key, wrong_key_similar)
        result_different = secrets.compare_digest(correct_key, wrong_key_different)

        assert result_correct is True
        assert result_similar is False
        assert result_different is False


class TestConfigurationValidation:
    """Tests for API key configuration validation in Settings."""

    @pytest.fixture(autouse=True)
    def isolate_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Isolate tests from environment variables and .env file."""
        # Clear any existing API_KEY from environment
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("ALLOWED_CORS_ORIGINS", raising=False)

    def test_production_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production environment requires API_KEY to be set."""
        from pydantic import ValidationError

        from app.config import Settings

        # Set environment variables directly (Settings reads from env)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("ALLOWED_CORS_ORIGINS", "https://example.com")
        # API_KEY is not set

        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)  # Disable .env file loading

        errors = exc_info.value.errors()
        assert any("API_KEY must be set" in str(e) for e in errors)

    def test_staging_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Staging environment requires API_KEY to be set."""
        from pydantic import ValidationError

        from app.config import Settings

        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.setenv("ALLOWED_CORS_ORIGINS", "https://example.com")

        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)

        errors = exc_info.value.errors()
        assert any("API_KEY must be set" in str(e) for e in errors)

    def test_api_key_minimum_length_32_chars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API key must be at least 32 characters in production."""
        from pydantic import ValidationError

        from app.config import Settings

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("API_KEY", "short_key_only_31_characters_")  # 31 chars
        monkeypatch.setenv("ALLOWED_CORS_ORIGINS", "https://example.com")

        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)

        errors = exc_info.value.errors()
        assert any("at least 32 characters" in str(e) for e in errors)

    def test_api_key_exactly_32_chars_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API key of exactly 32 characters is valid."""
        from app.config import Settings

        valid_key = "a" * 32

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("API_KEY", valid_key)
        monkeypatch.setenv("ALLOWED_CORS_ORIGINS", "https://example.com")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)

        settings = Settings(_env_file=None)

        assert settings.api_key == valid_key

    def test_api_key_longer_than_32_chars_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API key longer than 32 characters is valid."""
        from app.config import Settings

        valid_key = "a" * 64

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("API_KEY", valid_key)
        monkeypatch.setenv("ALLOWED_CORS_ORIGINS", "https://example.com")
        monkeypatch.setenv("JWT_SECRET", "x" * 32)

        settings = Settings(_env_file=None)

        assert settings.api_key == valid_key

    def test_development_allows_no_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Development environment allows missing API_KEY."""
        from app.config import Settings

        monkeypatch.setenv("ENVIRONMENT", "development")

        settings = Settings(_env_file=None)

        assert settings.api_key is None

    def test_development_allows_short_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Development environment allows short API_KEY (for testing)."""
        from app.config import Settings

        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("API_KEY", "short")

        settings = Settings(_env_file=None)

        assert settings.api_key == "short"


class TestApiKeyHeaderName:
    """Tests for API key header configuration."""

    def test_header_name_is_x_api_key(self) -> None:
        """Verify the header name is X-API-Key."""
        from app.dependencies.auth import API_KEY_HEADER

        assert API_KEY_HEADER.model.name == "X-API-Key"

    def test_auto_error_is_false(self) -> None:
        """Verify auto_error is False (we handle errors ourselves)."""
        from app.dependencies.auth import API_KEY_HEADER

        assert API_KEY_HEADER.auto_error is False
