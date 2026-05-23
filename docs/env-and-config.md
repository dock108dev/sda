# Environment And Config

Use `infra/.env.example` as the local template. Do not commit local `.env` files.

## Required Runtime Values

| Variable | Required | Notes |
| --- | --- | --- |
| `POSTGRES_DB` | yes | Database name for Docker Postgres |
| `POSTGRES_USER` | yes | Database user |
| `POSTGRES_PASSWORD` | yes | Database password |
| `REDIS_PASSWORD` | recommended | Redis password |
| `ENVIRONMENT` | yes | `development`, `staging`, or `production` |
| `DATABASE_URL` | set by compose | API and migration database URL |
| `REDIS_URL` | set by compose | Redis URL for API and Celery |
| `API_KEY` | production/staging | Required by catch-up routes |
| `JWT_SECRET` | production/staging | Required by API settings validation |
| `ALLOWED_CORS_ORIGINS` | production/staging | Comma-separated origins |
| `CBB_STATS_API_KEY` | when using NCAAB feeds | Needed by CBB/NCAAB integrations |
| `OPENAI_API_KEY` | optional | Enables AI-enhanced homepage context copy |

## Active Settings

API settings live in `api/app/config.py`.

| Variable | Active use |
| --- | --- |
| `ENVIRONMENT` | Controls docs visibility and production validation |
| `API_KEY` | Protects catch-up and admin task routes |
| `CONSUMER_API_KEY` | Accepted by settings but rejected for admin task routes |
| `DATABASE_URL` | API database access |
| `REDIS_URL` | Rate limiting, task hold, and Celery-compatible Redis access |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Optional Celery Redis overrides; the broker falls back to `REDIS_URL` |
| `ADMIN_ORIGINS` | Admin-origin role resolution |
| `TRUST_FORWARDED_ORIGIN` | Honors `X-Forwarded-Origin` only when explicitly enabled |
| `ALLOWED_CORS_ORIGINS` | CORS middleware |
| `RATE_LIMIT_*`, `ADMIN_RATE_LIMIT_*` | API and admin fixed-window rate limits |
| `OPENAI_API_KEY` | Optional context sentence polishing |
| `OPENAI_MODEL_CLASSIFICATION`, `OPENAI_MODEL_SUMMARY` | Optional OpenAI model overrides; empty strings fall back to code defaults |

Scraper settings live in `scraper/sports_scraper/config.py`.

| Variable | Active use |
| --- | --- |
| `DATABASE_URL` | Celery worker database access |
| `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB` | Celery broker/backend and task locks |
| `CBB_STATS_API_KEY` | NCAAB game and stats ingestion |
| `SCRAPER_HTML_CACHE_DIR` | Optional scraper cache path |
| `SCRAPER_FORCE_CACHE_REFRESH` | Optional cache bypass |

## Removed Configuration

The scheduled worker path is catch-up-only by construction. These old switches
and secrets are not used by the active scheduled worker or mounted catch-up
route path:

- `SDA_CATCHUP_ONLY`
- `SCRAPER_CATCHUP_ONLY`
- `DATAGOLF_API_KEY`
- `X_AUTH_TOKEN`
- `X_CT0`
- `X_BEARER_TOKEN`
- `SCRAPER_ROLE`

`ODDS_API_KEY`, `ODDS_API_REGIONS`, and `ODDS_API_WEEKLY_CAP` are still accepted
by the scraper settings because historical odds modules exist, but no odds task
is routed or beat-scheduled by the active Celery app.

## Validation

- `api/app/validate_env.py` validates API startup requirements and rejects local database URLs in production.
- `scraper/sports_scraper/validate_env.py` validates the catch-up worker's core database and Redis requirements.
- `Settings.validate_runtime_settings()` rejects production/staging API startup when `API_KEY` is missing.
- `infra/.env.example` is the local template; compose derives service-local
  `DATABASE_URL`, `REDIS_URL`, and `CELERY_BROKER_URL` from it.

## Non-Active Accepted Keys

Some settings remain accepted by Pydantic because historical modules still
import shared settings classes. Examples include email, Stripe, frontend, odds,
FairBet, and golf-related values. Accepted does not mean scheduled or mounted:
production relevance is determined by `api/main.py`, `celery_app.py`, and
`infra/docker-compose.yml`.
