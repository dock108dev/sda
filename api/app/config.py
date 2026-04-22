"""Configuration for the sports-data-admin API."""

from __future__ import annotations

import os
import re
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.validate_env import validate_env


class Settings(BaseSettings):
    """Environment-driven settings with sensible defaults for local/Hetzner."""

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="allow",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/sports",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/2", alias="REDIS_URL")
    celery_broker_url: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(
        default=None, alias="CELERY_RESULT_BACKEND"
    )
    celery_default_queue: str = Field(
        default="sports-scraper", alias="CELERY_DEFAULT_QUEUE"
    )
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str | None = Field(default=None, alias="LOG_LEVEL")
    allowed_cors_origins_raw: str | None = Field(
        default=None, alias="ALLOWED_CORS_ORIGINS"
    )
    admin_origins_raw: str | None = Field(
        default=None, alias="ADMIN_ORIGINS"
    )
    rate_limit_requests: int = Field(default=120, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(
        default=60, alias="RATE_LIMIT_WINDOW_SECONDS"
    )
    fairbet_odds_cache_enabled: bool = Field(
        default=True, alias="FAIRBET_ODDS_CACHE_ENABLED"
    )
    fairbet_odds_cache_ttl_seconds: int = Field(
        default=15, alias="FAIRBET_ODDS_CACHE_TTL_SECONDS"
    )
    fairbet_odds_snapshot_ttl_seconds: int = Field(
        default=60, alias="FAIRBET_ODDS_SNAPSHOT_TTL_SECONDS"
    )

    # Subdomain routing
    subdomain_routing: bool = Field(default=False, alias="SUBDOMAIN_ROUTING")
    base_domain: str = Field(default="localhost", alias="BASE_DOMAIN")

    # API Authentication
    # Required in production - all endpoints except /healthz require this key
    api_key: str | None = Field(default=None, alias="API_KEY")
    # Consumer-scoped API key for /api/v1/ routes. When set, admin and consumer
    # keys are distinct; each is rejected on the other's namespace. When unset,
    # api_key serves both namespaces (single-key fallback for dev/simple setups).
    consumer_api_key: str | None = Field(default=None, alias="CONSUMER_API_KEY")

    # Per-class rate limits enforced by RateLimitMiddleware.
    # Consumer routes (/api/v1/) use rate_limit_requests / rate_limit_window_seconds.
    # Admin routes (/api/admin/) use the tighter limits below.
    admin_rate_limit_requests: int = Field(default=20, alias="ADMIN_RATE_LIMIT_REQUESTS")
    admin_rate_limit_window_seconds: int = Field(default=60, alias="ADMIN_RATE_LIMIT_WINDOW_SECONDS")

    # JWT / User Authentication
    # AUTH_ENABLED=false skips JWT verification (dev-only; rejected in production by validator)
    auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
    jwt_secret: str = Field(
        default="dev-jwt-secret-change-in-production",
        alias="JWT_SECRET",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=1440, alias="JWT_EXPIRE_MINUTES")  # 24h

    # Email — backend selection and transport credentials.
    # EMAIL_BACKEND must be 'smtp' or 'ses'; defaults to 'smtp' for local dev.
    email_backend: str = Field(default="smtp", alias="EMAIL_BACKEND")
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    mail_from: str = Field(
        default="noreply@scrolldownsports.com", alias="MAIL_FROM"
    )
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    frontend_url: str = Field(
        default="http://localhost:3000", alias="FRONTEND_URL"
    )

    # Onboarding — prospect-facing "claim your club" submissions email here.
    # If unset, submissions are persisted but no notification email is sent.
    onboarding_notification_email: str | None = Field(
        default=None, alias="ONBOARDING_NOTIFICATION_EMAIL"
    )

    # Stripe — payment processing for club subscriptions.
    # STRIPE_SECRET_KEY is required for the /api/v1/commerce/checkout endpoint.
    stripe_secret_key: str | None = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_checkout_success_url: str = Field(
        default="http://localhost:3000/onboarding/success?session={CHECKOUT_SESSION_ID}",
        alias="STRIPE_CHECKOUT_SUCCESS_URL",
    )
    stripe_checkout_cancel_url: str = Field(
        default="http://localhost:3000/onboarding/cancel",
        alias="STRIPE_CHECKOUT_CANCEL_URL",
    )
    stripe_webhook_secret: str | None = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")

    # OpenAI Configuration (SSOT for model defaults — docker-compose defers to these)
    # AI is used for interpretation/narration only, never for ordering/filtering
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model_classification: str = Field(
        default="gpt-4o-mini", alias="OPENAI_MODEL_CLASSIFICATION"
    )
    openai_model_summary: str = Field(default="gpt-4o", alias="OPENAI_MODEL_SUMMARY")

    @model_validator(mode="after")
    def _default_empty_openai_models(self) -> Settings:
        """Treat empty-string model names as unset so the Field defaults apply."""
        if not self.openai_model_classification:
            self.openai_model_classification = "gpt-4o-mini"
        if not self.openai_model_summary:
            self.openai_model_summary = "gpt-4o"
        return self

    # Pipeline validation settings

    @property
    def allowed_cors_origins(self) -> list[str]:
        """Allow local dev ports for the web UI."""
        if self.allowed_cors_origins_raw:
            return [
                origin.strip()
                for origin in self.allowed_cors_origins_raw.split(",")
                if origin.strip()
            ]
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:3002",
            "http://127.0.0.1:3002",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    @property
    def cors_origin_regex(self) -> str | None:
        """Regex allowing all subdomains of BASE_DOMAIN when SUBDOMAIN_ROUTING is enabled."""
        if not self.subdomain_routing:
            return None
        return rf"https?://[a-z0-9][a-z0-9-]*\.{re.escape(self.base_domain)}"

    @property
    def admin_origins(self) -> list[str]:
        """Origins that are implicitly treated as admin (the admin UI)."""
        if self.admin_origins_raw:
            return [
                origin.strip()
                for origin in self.admin_origins_raw.split(",")
                if origin.strip()
            ]
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.celery_broker

    @model_validator(mode="after")
    def validate_runtime_settings(self) -> Settings:
        if self.environment in {"production", "staging"}:
            if not self.allowed_cors_origins_raw:
                raise ValueError(
                    "ALLOWED_CORS_ORIGINS must be set for production or staging."
                )
            if any(
                "localhost" in origin or "127.0.0.1" in origin
                for origin in self.allowed_cors_origins
            ):
                raise ValueError(
                    "ALLOWED_CORS_ORIGINS must not include localhost in production or staging."
                )
            if not self.api_key:
                raise ValueError("API_KEY must be set for production or staging.")
            if len(self.api_key) < 32:
                raise ValueError("API_KEY must be at least 32 characters long.")
            if self.jwt_secret == "dev-jwt-secret-change-in-production":
                raise ValueError(
                    "JWT_SECRET must be changed from the default for production or staging."
                )
            if len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters long.")
            if not self.auth_enabled:
                raise ValueError(
                    "AUTH_ENABLED must not be False in production or staging."
                )
        _valid_backends = {"smtp", "ses"}
        if self.email_backend not in _valid_backends:
            raise ValueError(
                f"EMAIL_BACKEND must be one of {sorted(_valid_backends)!r},"
                f" got {self.email_backend!r}"
            )
        if self.rate_limit_requests <= 0 or self.rate_limit_window_seconds <= 0:
            raise ValueError("Rate limit settings must be positive integers.")
        if self.fairbet_odds_cache_ttl_seconds <= 0:
            raise ValueError("FAIRBET_ODDS_CACHE_TTL_SECONDS must be positive.")
        if self.fairbet_odds_snapshot_ttl_seconds <= 0:
            raise ValueError("FAIRBET_ODDS_SNAPSHOT_TTL_SECONDS must be positive.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    validate_env()
    return Settings()


settings = get_settings()

# Source of truth for Stripe plan monthly pricing in cents.
# Keep in sync with the Stripe product catalog — update here first, then Stripe.
PLAN_PRICES: dict[str, int] = {
    "price_starter": 2900,
    "price_pro": 9900,
    "price_enterprise": 29900,
}
