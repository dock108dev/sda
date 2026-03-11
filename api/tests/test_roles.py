"""Tests for role-based access control dependencies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from app.dependencies.roles import (
    create_access_token,
    decode_access_token,
    require_admin,
    require_user,
    resolve_role,
)


class TestCreateAccessToken:
    """Tests for JWT token creation."""

    def test_creates_valid_jwt(self) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expire_minutes = 60

            token = create_access_token(user_id=1, role="user")

        payload = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        assert payload["sub"] == "1"
        assert payload["role"] == "user"
        assert "exp" in payload
        assert "iat" in payload

    def test_admin_role_in_token(self) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expire_minutes = 60

            token = create_access_token(user_id=42, role="admin")

        payload = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        assert payload["sub"] == "42"
        assert payload["role"] == "admin"

    def test_expiry_is_set_correctly(self) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expire_minutes = 120

            token = create_access_token(user_id=1, role="user")

        payload = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
        delta = exp - iat
        assert timedelta(minutes=119) < delta <= timedelta(minutes=121)


class TestDecodeAccessToken:
    """Tests for JWT token decoding."""

    def test_valid_token_decoded(self) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expire_minutes = 60

            token = create_access_token(user_id=5, role="admin")
            payload = decode_access_token(token)

        assert payload["sub"] == "5"
        assert payload["role"] == "admin"

    def test_expired_token_raises(self) -> None:
        secret = "test-secret-key"
        payload = {
            "sub": "1",
            "role": "user",
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        token = jwt.encode(payload, secret, algorithm="HS256")

        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.jwt_secret = secret
            mock_settings.jwt_algorithm = "HS256"

            with pytest.raises(jwt.ExpiredSignatureError):
                decode_access_token(token)

    def test_invalid_token_raises(self) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"

            with pytest.raises(jwt.PyJWTError):
                decode_access_token("not-a-valid-token")


class TestResolveRole:
    """Tests for resolve_role dependency."""

    @pytest.fixture
    def mock_request(self) -> MagicMock:
        request = MagicMock()
        request.state = MagicMock()
        return request

    @pytest.mark.asyncio
    async def test_no_credentials_returns_guest(self, mock_request: MagicMock) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.auth_enabled = True

            role = await resolve_role(mock_request, credentials=None)

        assert role == "guest"

    @pytest.mark.asyncio
    async def test_auth_disabled_returns_admin(self, mock_request: MagicMock) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.auth_enabled = False

            role = await resolve_role(mock_request, credentials=None)

        assert role == "admin"

    @pytest.mark.asyncio
    async def test_valid_user_token(self, mock_request: MagicMock) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.auth_enabled = True
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expire_minutes = 60

            token = create_access_token(user_id=10, role="user")
            creds = MagicMock()
            creds.credentials = token

            role = await resolve_role(mock_request, credentials=creds)

        assert role == "user"
        assert mock_request.state.user_id == 10
        assert mock_request.state.user_role == "user"

    @pytest.mark.asyncio
    async def test_valid_admin_token(self, mock_request: MagicMock) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.auth_enabled = True
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expire_minutes = 60

            token = create_access_token(user_id=1, role="admin")
            creds = MagicMock()
            creds.credentials = token

            role = await resolve_role(mock_request, credentials=creds)

        assert role == "admin"

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self, mock_request: MagicMock) -> None:
        secret = "test-secret-key"
        payload = {
            "sub": "1",
            "role": "user",
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        token = jwt.encode(payload, secret, algorithm="HS256")

        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.auth_enabled = True
            mock_settings.jwt_secret = secret
            mock_settings.jwt_algorithm = "HS256"

            creds = MagicMock()
            creds.credentials = token

            with pytest.raises(HTTPException) as exc_info:
                await resolve_role(mock_request, credentials=creds)

            assert exc_info.value.status_code == 401
            assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self, mock_request: MagicMock) -> None:
        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.auth_enabled = True
            mock_settings.jwt_secret = "test-secret-key"
            mock_settings.jwt_algorithm = "HS256"

            creds = MagicMock()
            creds.credentials = "garbage-token"

            with pytest.raises(HTTPException) as exc_info:
                await resolve_role(mock_request, credentials=creds)

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_role_defaults_to_user(self, mock_request: MagicMock) -> None:
        secret = "test-secret-key"
        payload = {
            "sub": "1",
            "role": "superuser",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        token = jwt.encode(payload, secret, algorithm="HS256")

        with patch("app.dependencies.roles.settings") as mock_settings:
            mock_settings.auth_enabled = True
            mock_settings.jwt_secret = secret
            mock_settings.jwt_algorithm = "HS256"

            creds = MagicMock()
            creds.credentials = token

            role = await resolve_role(mock_request, credentials=creds)

        assert role == "user"


class TestRequireUser:
    """Tests for require_user dependency."""

    @pytest.mark.asyncio
    async def test_guest_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await require_user(role="guest")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_user_accepted(self) -> None:
        role = await require_user(role="user")
        assert role == "user"

    @pytest.mark.asyncio
    async def test_admin_accepted(self) -> None:
        role = await require_user(role="admin")
        assert role == "admin"


class TestRequireAdmin:
    """Tests for require_admin dependency."""

    @pytest.mark.asyncio
    async def test_guest_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(role="guest")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_user_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(role="user")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_accepted(self) -> None:
        role = await require_admin(role="admin")
        assert role == "admin"
