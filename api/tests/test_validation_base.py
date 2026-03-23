"""Tests for validation_base module."""

import pytest


class TestRequireEnv:
    """Tests for require_env function."""

    def test_returns_value(self, monkeypatch):
        """Returns environment variable value."""
        from app.utils.validation_base import require_env

        monkeypatch.setenv("TEST_VAR", "test_value")
        result = require_env("TEST_VAR")
        assert result == "test_value"

    def test_strips_whitespace(self, monkeypatch):
        """Strips whitespace from value."""
        from app.utils.validation_base import require_env

        monkeypatch.setenv("TEST_VAR", "  test_value  ")
        result = require_env("TEST_VAR")
        assert result == "test_value"

    def test_missing_raises(self, monkeypatch):
        """Missing variable raises RuntimeError."""
        from app.utils.validation_base import require_env

        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(RuntimeError, match="required"):
            require_env("MISSING_VAR")

    def test_empty_raises(self, monkeypatch):
        """Empty variable raises RuntimeError."""
        from app.utils.validation_base import require_env

        monkeypatch.setenv("EMPTY_VAR", "")
        with pytest.raises(RuntimeError, match="required"):
            require_env("EMPTY_VAR")

    def test_whitespace_only_raises(self, monkeypatch):
        """Whitespace-only variable raises RuntimeError."""
        from app.utils.validation_base import require_env

        monkeypatch.setenv("WHITESPACE_VAR", "   ")
        with pytest.raises(RuntimeError, match="required"):
            require_env("WHITESPACE_VAR")


class TestValidateEnvironmentValue:
    """Tests for validate_environment_value function."""

    def test_development_valid(self):
        """development is valid."""
        from app.utils.validation_base import validate_environment_value

        # Should not raise
        validate_environment_value("development")

    def test_staging_valid(self):
        """staging is valid."""
        from app.utils.validation_base import validate_environment_value

        # Should not raise
        validate_environment_value("staging")

    def test_production_valid(self):
        """production is valid."""
        from app.utils.validation_base import validate_environment_value

        # Should not raise
        validate_environment_value("production")

    def test_invalid_raises(self):
        """Invalid value raises RuntimeError."""
        from app.utils.validation_base import validate_environment_value

        with pytest.raises(RuntimeError, match="must be one of"):
            validate_environment_value("invalid")


class TestValidateNonLocalUrl:
    """Tests for validate_non_local_url function."""

    def test_remote_url_valid(self):
        """Remote URL is valid."""
        from app.utils.validation_base import validate_non_local_url

        # Should not raise
        validate_non_local_url("DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mydb")

    def test_localhost_raises(self):
        """localhost URL raises RuntimeError."""
        from app.utils.validation_base import validate_non_local_url

        with pytest.raises(RuntimeError, match="must not point to localhost"):
            validate_non_local_url("DATABASE_URL", "postgresql://user:pass@localhost:5432/mydb")

    def test_127_0_0_1_raises(self):
        """127.0.0.1 URL raises RuntimeError."""
        from app.utils.validation_base import validate_non_local_url

        with pytest.raises(RuntimeError, match="must not point to localhost"):
            validate_non_local_url("DATABASE_URL", "postgresql://user:pass@127.0.0.1:5432/mydb")

    def test_missing_hostname_raises(self):
        """URL with missing hostname raises RuntimeError."""
        from app.utils.validation_base import validate_non_local_url

        with pytest.raises(RuntimeError, match="missing hostname"):
            validate_non_local_url("DATABASE_URL", "not-a-url")


class TestValidateDatabaseCredentials:
    """Tests for validate_database_credentials function."""

    def test_custom_credentials_valid(self):
        """Custom credentials are valid."""
        from app.utils.validation_base import validate_database_credentials

        # Should not raise
        validate_database_credentials("postgresql://myuser:mypass@db.example.com:5432/mydb")

    def test_default_credentials_raises(self):
        """Default postgres:postgres credentials raise RuntimeError."""
        from app.utils.validation_base import validate_database_credentials

        with pytest.raises(RuntimeError, match="default credentials"):
            validate_database_credentials("postgresql://postgres:postgres@db.example.com:5432/mydb")

    def test_sports_default_credentials_raises(self):
        """Default sports:sports credentials raise RuntimeError."""
        from app.utils.validation_base import validate_database_credentials

        with pytest.raises(RuntimeError, match="default credentials"):
            validate_database_credentials("postgresql://sports:sports@db.example.com:5432/mydb")

    def test_partial_default_user_valid(self):
        """postgres user with non-default password is valid."""
        from app.utils.validation_base import validate_database_credentials

        # Should not raise
        validate_database_credentials("postgresql://postgres:custom_pass@db.example.com:5432/mydb")

    def test_partial_default_password_valid(self):
        """Non-postgres user with 'postgres' password is valid."""
        from app.utils.validation_base import validate_database_credentials

        # Should not raise
        validate_database_credentials("postgresql://custom_user:postgres@db.example.com:5432/mydb")
