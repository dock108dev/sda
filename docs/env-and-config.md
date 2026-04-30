# Environment variables & runtime configuration

This document ties together **where** configuration lives and **how** it is validated. For Docker Compose service names and host ports, see [Infrastructure & local dev](ops/infra.md).

## Docker Compose (`infra/`)

- **Template:** `infra/.env.example` — copy to `infra/.env` for local stacks.
- **Scope:** Database, Redis, API, workers, and web share environment from the same file when using `docker compose` from `infra/`.

## API service (`api/app/config.py`)

The FastAPI app loads **`Settings`** via Pydantic Settings (`pydantic-settings`). Relevant behaviors:

| Behavior | Detail |
|----------|--------|
| **Env file** | Defaults to `api/../../.env` relative to the `app` package (often repo-root `.env` in dev). |
| **Unknown keys** | `model_config.extra = "ignore"` — variables not declared on `Settings` are **silently dropped**. Typos in optional keys do not fail startup. |
| **Production / staging** | `validate_runtime_settings` enforces non-local DB URL shape, `API_KEY` length, `JWT_SECRET`, `ALLOWED_CORS_ORIGINS`, `AUTH_ENABLED`, etc. |

Authoritative field list and defaults: read `Settings` in `api/app/config.py` (each field documents its `alias=` env name).

### Cross-cutting flags (verified in code)

| Concern | Env / mechanism | Notes |
|---------|-----------------|-------|
| Trust forwarded origin | `TRUST_FORWARDED_ORIGIN` | See [Security trust boundaries](security-trust-boundaries.md). |
| Rate limits across replicas | `RATE_LIMIT_USE_REDIS` | Falls back to in-process limits if Redis errors; see [Known limitations](known-limitations.md). |
| OpenTelemetry | `OTEL_EXPORTER_OTLP_ENDPOINT` | No-op when unset (`api/app/otel.py`). Prometheus metrics at `GET /metrics` are separate (`prometheus_client`). |
| Email | `EMAIL_BACKEND`, Resend/SMTP vars | Documented on `Settings`; emails log-only when not configured. |

## Scraper service (`scraper/sports_scraper/config.py`)

Typed **`ScraperSettings`** (and nested models) load from the same environment pattern as the API for shared keys (`DATABASE_URL`, `REDIS_URL`, etc.). Scraper-specific tuning (odds regions, social delays) lives on nested config objects in that module.

## Celery (API vs scraper)

- **Scraper beat / workers:** `scraper/sports_scraper/celery_app.py` — broker/backend from scraper settings (`REDIS_URL`).
- **API tasks (training, batch jobs, etc.):** `api/app/celery_app.py` — separate Celery app; queue names and broker URLs come from API env (`CELERY_BROKER_URL`, `REDIS_URL`, etc.). See [Scheduler & background jobs](scheduler-and-jobs.md).

## CI / validation

- **`api/app/validate_env.py`** — called when settings load; checks required vars for the chosen `ENVIRONMENT`.
- **Production deploys** should still use a checklist for business-critical keys (Odds API, social tokens) even when optional at runtime.
