"""Tests to ensure scraper validation functions match api/app/utils/validation_base.py.

These functions are intentionally duplicated because scraper and api are separate
Python packages. This test suite catches any divergence in behavior.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from sports_scraper.validate_env import (
    ALLOWED_ENVIRONMENTS as SCRAPER_ALLOWED_ENVIRONMENTS,
)
from sports_scraper.validate_env import (
    require_env as scraper_require_env,
)
from sports_scraper.validate_env import (
    validate_database_credentials as scraper_validate_database_credentials,
)
from sports_scraper.validate_env import (
    validate_environment_value as scraper_validate_environment_value,
)
from sports_scraper.validate_env import (
    validate_non_local_url as scraper_validate_non_local_url,
)


def _load_api_validation_base() -> ModuleType:
    """Dynamically load the API validation_base module."""
    # Navigate from scraper/tests/ up to the repo root, then to api/app/utils/
    # Use resolve() to get absolute path from __file__
    this_file = Path(__file__).resolve()
    # this_file = /path/to/sports-data-admin/scraper/tests/test_validation_equivalence.py
    # We need: /path/to/sports-data-admin/api/app/utils/validation_base.py
    api_validation_path = (
        this_file.parent.parent.parent / "api" / "app" / "utils" / "validation_base.py"
    )
    if not api_validation_path.exists():
        raise FileNotFoundError(f"API validation_base not found at {api_validation_path}")

    spec = importlib.util.spec_from_file_location("api_validation_base", api_validation_path)
    if spec is None or spec.loader is None:
        raise ImportError("Could not create module spec for validation_base")

    module = importlib.util.module_from_spec(spec)
    sys.modules["api_validation_base"] = module
    spec.loader.exec_module(module)
    return module


# Load API module at test collection time
_api_module = _load_api_validation_base()
API_ALLOWED_ENVIRONMENTS = _api_module.ALLOWED_ENVIRONMENTS
api_require_env = _api_module.require_env
api_validate_environment_value = _api_module.validate_environment_value
api_validate_non_local_url = _api_module.validate_non_local_url
api_validate_database_credentials = _api_module.validate_database_credentials


class TestAllowedEnvironmentsEquivalence:
    """Ensure ALLOWED_ENVIRONMENTS constant matches between packages."""

    def test_allowed_environments_match(self) -> None:
        """ALLOWED_ENVIRONMENTS should be identical in both packages."""
        assert SCRAPER_ALLOWED_ENVIRONMENTS == API_ALLOWED_ENVIRONMENTS
        assert {"development", "staging", "production"} == SCRAPER_ALLOWED_ENVIRONMENTS


class TestRequireEnvEquivalence:
    """Ensure require_env behaves identically in both packages."""

    def test_missing_env_raises_same_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both should raise RuntimeError with same message for missing env."""
        monkeypatch.delenv("TEST_MISSING_VAR", raising=False)

        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_require_env("TEST_MISSING_VAR")

        with pytest.raises(RuntimeError) as api_exc:
            api_require_env("TEST_MISSING_VAR")

        assert str(scraper_exc.value) == str(api_exc.value)

    def test_empty_env_raises_same_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both should raise RuntimeError with same message for empty env."""
        monkeypatch.setenv("TEST_EMPTY_VAR", "")

        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_require_env("TEST_EMPTY_VAR")

        with pytest.raises(RuntimeError) as api_exc:
            api_require_env("TEST_EMPTY_VAR")

        assert str(scraper_exc.value) == str(api_exc.value)

    def test_whitespace_env_raises_same_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both should raise RuntimeError for whitespace-only env."""
        monkeypatch.setenv("TEST_WHITESPACE_VAR", "   ")

        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_require_env("TEST_WHITESPACE_VAR")

        with pytest.raises(RuntimeError) as api_exc:
            api_require_env("TEST_WHITESPACE_VAR")

        assert str(scraper_exc.value) == str(api_exc.value)

    def test_valid_env_returns_same_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both should return stripped value for valid env."""
        monkeypatch.setenv("TEST_VALID_VAR", "  some_value  ")

        assert scraper_require_env("TEST_VALID_VAR") == api_require_env("TEST_VALID_VAR")
        assert scraper_require_env("TEST_VALID_VAR") == "some_value"


class TestValidateEnvironmentValueEquivalence:
    """Ensure validate_environment_value behaves identically."""

    @pytest.mark.parametrize("env", ["development", "staging", "production"])
    def test_valid_environments_pass(self, env: str) -> None:
        """Both should accept valid environment values without raising."""
        scraper_validate_environment_value(env)
        api_validate_environment_value(env)

    @pytest.mark.parametrize("env", ["prod", "dev", "test", "local", "PRODUCTION", ""])
    def test_invalid_environments_raise_same_error(self, env: str) -> None:
        """Both should raise RuntimeError with same message for invalid env."""
        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_validate_environment_value(env)

        with pytest.raises(RuntimeError) as api_exc:
            api_validate_environment_value(env)

        assert str(scraper_exc.value) == str(api_exc.value)


class TestValidateNonLocalUrlEquivalence:
    """Ensure validate_non_local_url behaves identically."""

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://user:pass@db.example.com:5432/mydb",
            "redis://redis.example.com:6379",
            "https://api.example.com/v1",
        ],
    )
    def test_valid_urls_pass(self, url: str) -> None:
        """Both should accept non-local URLs without raising."""
        scraper_validate_non_local_url("TEST_URL", url)
        api_validate_non_local_url("TEST_URL", url)

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://user:pass@localhost:5432/mydb",
            "redis://127.0.0.1:6379",
            "http://localhost:8000/api",
        ],
    )
    def test_localhost_urls_raise_same_error(self, url: str) -> None:
        """Both should raise RuntimeError with same message for localhost URLs."""
        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_validate_non_local_url("TEST_URL", url)

        with pytest.raises(RuntimeError) as api_exc:
            api_validate_non_local_url("TEST_URL", url)

        assert str(scraper_exc.value) == str(api_exc.value)

    def test_invalid_url_raises_same_error(self) -> None:
        """Both should raise RuntimeError with same message for invalid URL."""
        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_validate_non_local_url("TEST_URL", "not-a-url")

        with pytest.raises(RuntimeError) as api_exc:
            api_validate_non_local_url("TEST_URL", "not-a-url")

        assert str(scraper_exc.value) == str(api_exc.value)


class TestValidateDatabaseCredentialsEquivalence:
    """Ensure validate_database_credentials behaves identically."""

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://myuser:mypass@db.example.com:5432/mydb",
            "postgresql://postgres:secretpass@db.example.com:5432/mydb",
            "postgresql://admin:postgres@db.example.com:5432/mydb",
        ],
    )
    def test_valid_credentials_pass(self, url: str) -> None:
        """Both should accept non-default credentials without raising."""
        scraper_validate_database_credentials(url)
        api_validate_database_credentials(url)

    def test_default_credentials_raise_same_error(self) -> None:
        """Both should raise RuntimeError with same message for default creds."""
        url = "postgresql://postgres:postgres@db.example.com:5432/mydb"

        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_validate_database_credentials(url)

        with pytest.raises(RuntimeError) as api_exc:
            api_validate_database_credentials(url)

        assert str(scraper_exc.value) == str(api_exc.value)

    def test_sports_default_credentials_raise_same_error(self) -> None:
        """Both should raise RuntimeError for sports:sports default creds."""
        url = "postgresql://sports:sports@db.example.com:5432/mydb"

        with pytest.raises(RuntimeError) as scraper_exc:
            scraper_validate_database_credentials(url)

        with pytest.raises(RuntimeError) as api_exc:
            api_validate_database_credentials(url)

        assert str(scraper_exc.value) == str(api_exc.value)
