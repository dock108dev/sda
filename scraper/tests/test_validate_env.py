"""Tests for catch-up worker environment validation."""

from __future__ import annotations

import os
from unittest.mock import patch

from sports_scraper.validate_env import validate_env


def _prod_base_env() -> dict[str, str]:
    """Minimal env vars that every production worker needs."""
    return {
        "ENVIRONMENT": "production",
        "DATABASE_URL": "postgresql+psycopg://user:secret@db.prod:5432/app",
        "REDIS_URL": "redis://redis.prod:6379/2",
    }


class TestValidateEnvProduction:
    def test_production_requires_only_core_catchup_worker_env(self):
        env = _prod_base_env()
        with patch.dict(os.environ, env, clear=True):
            validate_env.cache_clear()
            validate_env()

    def test_production_validation_has_no_role_or_external_feed_requirements(self):
        env = _prod_base_env()
        with patch.dict(os.environ, env, clear=True):
            validate_env.cache_clear()
            validate_env()


class TestValidateEnvDevelopment:
    """In development mode, role-specific checks are skipped entirely."""

    def test_dev_skips_all_production_checks(self):
        env = {
            "ENVIRONMENT": "development",
            "DATABASE_URL": "postgresql://sports:sports@localhost:5432/sports",
            "REDIS_URL": "redis://localhost:6379/2",
        }
        with patch.dict(os.environ, env, clear=True):
            validate_env.cache_clear()
            validate_env()  # should not raise
