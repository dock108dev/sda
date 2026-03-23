"""Fail-fast environment validation for the scraper/worker service.

NOTE: The functions require_env, validate_environment_value, validate_non_local_url,
and validate_database_credentials are intentionally duplicated from
api/app/utils/validation_base.py. This duplication exists because the scraper
and api are separate Python packages in this monorepo, and the scraper cannot
import from the api without creating a circular dependency.

These implementations MUST remain identical to their api counterparts.
See tests/test_validation_equivalence.py for behavioral equivalence tests.
"""

from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

ALLOWED_ENVIRONMENTS = {"development", "staging", "production"}


def require_env(name: str) -> str:
    """Fetch an environment variable or raise RuntimeError if missing."""
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required and must be set before startup.")
    return value.strip()


def validate_environment_value(environment: str) -> None:
    """Ensure ENVIRONMENT is one of the allowed values."""
    if environment not in ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(ALLOWED_ENVIRONMENTS))
        raise RuntimeError(f"ENVIRONMENT must be one of: {allowed}.")


def validate_non_local_url(name: str, value: str) -> None:
    """Ensure a URL does not point to localhost in production."""
    parsed = urlparse(value)
    host = parsed.hostname
    if not host:
        raise RuntimeError(f"{name} must be a valid URL (missing hostname).")
    if host in {"localhost", "127.0.0.1"}:
        raise RuntimeError(f"{name} must not point to localhost in production.")


def validate_database_credentials(value: str) -> None:
    """Ensure DATABASE_URL does not use default credentials in production."""
    parsed = urlparse(value)
    _DEFAULT_CREDS = {("postgres", "postgres"), ("sports", "sports")}
    if (parsed.username, parsed.password) in _DEFAULT_CREDS:
        raise RuntimeError(
            "DATABASE_URL must not use default credentials in production."
        )


def _validate_social_credentials() -> None:
    bearer_token = os.getenv("X_BEARER_TOKEN")
    auth_token = os.getenv("X_AUTH_TOKEN")
    ct0 = os.getenv("X_CT0")
    if bearer_token:
        return
    if auth_token and ct0:
        return
    raise RuntimeError(
        "Production social scraping requires X_BEARER_TOKEN or X_AUTH_TOKEN + X_CT0."
    )


ALLOWED_SCRAPER_ROLES = {"worker", "beat", "social"}


@lru_cache(maxsize=1)
def validate_env() -> None:
    """Validate required environment variables before the worker starts.

    Uses SCRAPER_ROLE to determine which credentials are required so each
    container only demands the secrets it actually needs.

    Roles:
        worker / beat — scraping worker or scheduler: needs ODDS_API_KEY.
        social        — social-only worker: needs X credentials.
    """
    environment = require_env("ENVIRONMENT")
    validate_environment_value(environment)

    database_url = require_env("DATABASE_URL")
    redis_url = require_env("REDIS_URL")

    if environment == "production":
        validate_non_local_url("DATABASE_URL", database_url)
        validate_database_credentials(database_url)
        validate_non_local_url("REDIS_URL", redis_url)

        role = os.getenv("SCRAPER_ROLE", "worker")
        if role not in ALLOWED_SCRAPER_ROLES:
            allowed = ", ".join(sorted(ALLOWED_SCRAPER_ROLES))
            raise RuntimeError(f"SCRAPER_ROLE must be one of: {allowed}.")

        if role in ("worker", "beat"):
            require_env("ODDS_API_KEY")

        if role == "social":
            _validate_social_credentials()
