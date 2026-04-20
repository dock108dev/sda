"""Tests for consumer (v1) API key authentication — ISSUE-010.

Verifies that verify_consumer_api_key enforces consumer-scope isolation:
- Consumer key accepted; admin key rejected (403) when keys differ.
- Does NOT set api_key_verified on request.state (no role escalation).
"""

from __future__ import annotations

import asyncio
import secrets
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.dependencies.consumer_auth import API_KEY_HEADER, verify_consumer_api_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_request(path: str = "/api/v1/test") -> MagicMock:
    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.url.path = path
    request.state = MagicMock()
    return request


def _mock_settings(
    *,
    api_key: str | None = None,
    consumer_api_key: str | None = None,
    environment: str = "development",
) -> MagicMock:
    m = MagicMock()
    m.api_key = api_key
    m.consumer_api_key = consumer_api_key
    m.environment = environment
    return m


# ---------------------------------------------------------------------------
# Core acceptance/rejection
# ---------------------------------------------------------------------------

class TestVerifyConsumerApiKey:
    """Unit tests for verify_consumer_api_key."""

    def test_valid_consumer_key_accepted(self) -> None:
        """Consumer key returns the key string on success."""
        consumer_key = "c" * 40
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(consumer_api_key=consumer_key),
        ):
            result = asyncio.run(verify_consumer_api_key(req, consumer_key))
        assert result == consumer_key

    def test_invalid_key_rejected_401(self) -> None:
        """Wrong API key raises 401."""
        consumer_key = "correct_consumer_" + "x" * 24
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(consumer_api_key=consumer_key),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(req, "wrong_" + "y" * 34))
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid API key"

    def test_missing_key_rejected_401(self) -> None:
        """Missing API key raises 401."""
        consumer_key = "consumer_key_" + "x" * 28
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(consumer_api_key=consumer_key),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(req, None))
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Missing API key"
        assert exc_info.value.headers == {"WWW-Authenticate": "ApiKey"}

    def test_empty_string_key_rejected_401(self) -> None:
        """Empty string API key is treated as missing."""
        consumer_key = "consumer_key_" + "x" * 28
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(consumer_api_key=consumer_key),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(req, ""))
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Missing API key"

    def test_dev_mode_no_key_configured(self) -> None:
        """Dev mode with no key allows unauthenticated requests."""
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(environment="development"),
        ):
            result = asyncio.run(verify_consumer_api_key(req, None))
        assert result == ""

    def test_production_no_key_returns_500(self) -> None:
        """Production without any key configured returns 500."""
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(environment="production"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(req, None))
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Server authentication misconfigured"

    def test_staging_no_key_returns_500(self) -> None:
        """Staging without any key configured returns 500."""
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(environment="staging"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(req, None))
        assert exc_info.value.status_code == 500

    def test_falls_back_to_admin_key_when_no_consumer_key(self) -> None:
        """Single-key setup: admin key serves consumer routes (dev/simple deployments)."""
        admin_key = "admin_only_key_" + "x" * 26
        req = _mock_request()
        # consumer_api_key is None → falls back to api_key
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(api_key=admin_key, consumer_api_key=None),
        ):
            result = asyncio.run(verify_consumer_api_key(req, admin_key))
        assert result == admin_key

    def test_same_value_for_both_keys_accepted(self) -> None:
        """When consumer_api_key == api_key (same value), the key is accepted."""
        shared_key = "shared_key_" + "x" * 30
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(api_key=shared_key, consumer_api_key=shared_key),
        ):
            result = asyncio.run(verify_consumer_api_key(req, shared_key))
        assert result == shared_key

    def test_uses_constant_time_comparison(self) -> None:
        """secrets.compare_digest is used for key comparison."""
        consumer_key = "consumer_" + "k" * 32
        req = _mock_request()
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(consumer_api_key=consumer_key),
        ):
            with patch(
                "app.dependencies.consumer_auth.secrets.compare_digest",
                return_value=True,
            ) as mock_compare:
                asyncio.run(verify_consumer_api_key(req, consumer_key))
            mock_compare.assert_called()


# ---------------------------------------------------------------------------
# Scope isolation — ISSUE-010 acceptance criteria
# ---------------------------------------------------------------------------

class TestScopeIsolation:
    """Cross-namespace token rejection tests."""

    def test_admin_key_rejected_on_consumer_route(self) -> None:
        """Admin key raises 403 on consumer route when distinct keys are configured."""
        admin_key = "admin_key_secret_" + "a" * 24
        consumer_key = "consumer_key_secret_" + "b" * 21
        req = _mock_request("/api/v1/games")
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(api_key=admin_key, consumer_api_key=consumer_key),
        ):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(verify_consumer_api_key(req, admin_key))
        assert exc_info.value.status_code == 403
        assert "Admin API key is not authorized for consumer routes" in exc_info.value.detail

    def test_consumer_key_still_works_on_consumer_route(self) -> None:
        """Consumer key is accepted on consumer route even with dual-key config."""
        admin_key = "admin_key_secret_" + "a" * 24
        consumer_key = "consumer_key_secret_" + "b" * 21
        req = _mock_request("/api/v1/games")
        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(api_key=admin_key, consumer_api_key=consumer_key),
        ):
            result = asyncio.run(verify_consumer_api_key(req, consumer_key))
        assert result == consumer_key

    def test_does_not_set_api_key_verified_on_state(self) -> None:
        """Consumer auth never sets api_key_verified (prevents admin role escalation)."""
        consumer_key = "consumer_" + "k" * 32
        req = _mock_request()

        # Use a real object so attribute presence is meaningful.
        class State:
            pass
        req.state = State()

        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(consumer_api_key=consumer_key),
        ):
            asyncio.run(verify_consumer_api_key(req, consumer_key))

        assert not getattr(req.state, "api_key_verified", False)

    def test_logs_warning_when_admin_key_used_on_consumer_route(self) -> None:
        """Admin key on consumer route logs a warning with path context."""
        admin_key = "admin_key_secret_" + "a" * 24
        consumer_key = "consumer_key_secret_" + "b" * 21
        req = _mock_request("/api/v1/games")

        with patch(
            "app.dependencies.consumer_auth.settings",
            _mock_settings(api_key=admin_key, consumer_api_key=consumer_key),
        ):
            with patch("app.dependencies.consumer_auth.logger") as mock_logger:
                with pytest.raises(HTTPException):
                    asyncio.run(verify_consumer_api_key(req, admin_key))

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "Admin API key used on consumer route"
            assert call_args[1]["extra"]["path"] == "/api/v1/games"


# ---------------------------------------------------------------------------
# Structural — router-level dependency assignment
# ---------------------------------------------------------------------------

class TestRouterDependencyAssignment:
    """Verify consumer and admin stacks use their own auth dep (ISSUE-010)."""

    def test_v1_router_uses_verify_consumer_api_key(self) -> None:
        """v1 router-level dependencies include verify_consumer_api_key."""
        from fastapi.routing import APIRouter
        from app.routers.v1 import router as v1_router

        dep_callables = {
            dep.dependency
            for dep in (v1_router.dependencies or [])
        }
        assert verify_consumer_api_key in dep_callables, (
            "v1 router must use verify_consumer_api_key, not verify_api_key"
        )

    def test_v1_router_does_not_use_admin_verify_api_key(self) -> None:
        """v1 router must not use the admin verify_api_key dependency."""
        from app.dependencies.auth import verify_api_key
        from app.routers.v1 import router as v1_router

        dep_callables = {
            dep.dependency
            for dep in (v1_router.dependencies or [])
        }
        assert verify_api_key not in dep_callables, (
            "v1 router must not use verify_api_key (admin auth); "
            "use verify_consumer_api_key instead"
        )


# ---------------------------------------------------------------------------
# Header configuration
# ---------------------------------------------------------------------------

class TestConsumerApiKeyHeaderConfig:
    """Consumer auth header configuration."""

    def test_header_name_is_x_api_key(self) -> None:
        assert API_KEY_HEADER.model.name == "X-API-Key"

    def test_auto_error_is_false(self) -> None:
        assert API_KEY_HEADER.auto_error is False
