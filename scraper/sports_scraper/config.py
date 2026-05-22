"""
Typed settings for the Sports Data scraper service.

Uses Pydantic Settings to load configuration from environment variables
with validation and type safety. Settings are loaded from the root .env
file to maintain consistency across all services.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .validate_env import validate_env


class ScraperConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["sports_reference"])
    request_timeout_seconds: int = 20
    max_concurrency: int = 4
    # Polite scraping: 5-9 second random delays between requests
    min_request_delay: float = 5.0
    max_request_delay: float = 9.0
    rate_limit_wait_seconds: int = 60  # Wait longer on 429
    jitter_range: float = 0.5
    day_delay_min: float = 1.0
    day_delay_max: float = 2.0
    error_delay_min: float = 5.0
    error_delay_max: float = 10.0
    # HTML cache directory for storing scraped pages locally
    html_cache_dir: str = "./game_data"
    force_cache_refresh: bool = False


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    In Docker, environment variables are passed directly via docker-compose.
    For local development, loads from root .env file (../../.env) to maintain
    consistency with other services. All settings are validated by Pydantic.
    """

    model_config = SettingsConfigDict(
        # Try to load from root .env file (for local dev), but don't fail if it doesn't exist
        # In Docker, env vars are passed directly via environment section
        env_file=Path(__file__).resolve().parents[3] / ".env",  # Root .env file
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # Ignore empty env vars
        extra="allow",  # Allow extra env vars without validation errors
    )

    database_url: str = Field(..., alias="DATABASE_URL")

    @field_validator("database_url", mode="before")
    @classmethod
    def convert_async_to_sync(cls, v: str) -> str:
        """
        Convert asyncpg URL to psycopg URL for synchronous SQLAlchemy.

        The root .env file uses asyncpg (for FastAPI), but Celery workers
        need synchronous psycopg. This validator automatically converts
        the URL so we can keep a single DATABASE_URL in the .env file.
        """
        if isinstance(v, str) and "asyncpg" in v:
            return v.replace("asyncpg", "psycopg")
        return v

    # Redis configuration - can be set via REDIS_URL or constructed from components
    redis_url: str = Field("redis://localhost:6379/2", alias="REDIS_URL")
    redis_host: str = Field("localhost", alias="REDIS_HOST")
    redis_password: str | None = Field(None, alias="REDIS_PASSWORD")
    redis_db: int = Field(2, alias="REDIS_DB")

    @model_validator(mode="after")
    def _build_redis_url(self) -> Settings:
        """
        Build Redis URL from components if REDIS_HOST is set to a non-localhost value.
        This handles Docker environments where we pass REDIS_HOST=redis and REDIS_PASSWORD separately.
        """
        # If redis_host is not localhost, construct the URL from components
        if self.redis_host != "localhost":
            if self.redis_password:
                self.redis_url = (
                    f"redis://:{self.redis_password}@{self.redis_host}:6379/{self.redis_db}"
                )
            else:
                self.redis_url = f"redis://{self.redis_host}:6379/{self.redis_db}"
        return self

    cbb_stats_api_key: str | None = Field(None, alias="CBB_STATS_API_KEY")
    environment: str = Field("development", alias="ENVIRONMENT")
    log_level: str | None = Field(None, alias="LOG_LEVEL")
    scraper_config: ScraperConfig = Field(default_factory=ScraperConfig)
    api_internal_url: str = Field("http://api:8000", alias="API_INTERNAL_URL")
    api_key: str | None = Field(None, alias="API_KEY")
    scraper_html_cache_dir_override: str | None = Field(None, alias="SCRAPER_HTML_CACHE_DIR")
    scraper_force_cache_refresh_override: bool | None = Field(
        None, alias="SCRAPER_FORCE_CACHE_REFRESH"
    )

    @model_validator(mode="after")
    def _apply_scraper_overrides(self) -> Settings:
        """
        Allow top-level env vars (SCRAPER_HTML_CACHE_DIR / SCRAPER_FORCE_CACHE_REFRESH)
        to override the nested scraper config without requiring double-underscore syntax.
        """
        if self.scraper_html_cache_dir_override:
            self.scraper_config.html_cache_dir = self.scraper_html_cache_dir_override
        if self.scraper_force_cache_refresh_override is not None:
            self.scraper_config.force_cache_refresh = bool(
                self.scraper_force_cache_refresh_override
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return cached settings instance.

    Settings are cached to avoid re-parsing environment variables
    on every access. This is safe because environment variables
    don't change during runtime.
    """
    validate_env()
    return Settings()


# Global settings instance - import this in other modules
settings = get_settings()
