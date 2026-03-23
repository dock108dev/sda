"""Fail-fast environment validation for the API service."""

from __future__ import annotations

from functools import lru_cache

from app.utils.validation_base import (
    require_env,
    validate_database_credentials,
    validate_environment_value,
    validate_non_local_url,
)


@lru_cache(maxsize=1)
def validate_env() -> None:
    """Validate required environment variables before the API starts."""
    environment = require_env("ENVIRONMENT")
    validate_environment_value(environment)

    database_url = require_env("DATABASE_URL")

    if environment == "production":
        validate_non_local_url("DATABASE_URL", database_url)
        validate_database_credentials(database_url)

        jwt_secret = require_env("JWT_SECRET")
        if jwt_secret == "dev-jwt-secret-change-in-production":
            raise RuntimeError(
                "JWT_SECRET must not use the insecure default in production."
            )

        allowed_cors = require_env("ALLOWED_CORS_ORIGINS")
        if "localhost" in allowed_cors or "127.0.0.1" in allowed_cors:
            raise RuntimeError(
                "ALLOWED_CORS_ORIGINS must not include localhost in production."
            )
