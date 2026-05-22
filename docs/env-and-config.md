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
| `ALLOWED_CORS_ORIGINS` | CORS middleware |
| `OPENAI_API_KEY` | Optional context sentence polishing |

Scraper settings live in `scraper/sports_scraper/config.py`.

| Variable | Active use |
| --- | --- |
| `DATABASE_URL` | Celery worker database access |
| `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB` | Celery broker/backend and task locks |
| `CBB_STATS_API_KEY` | NCAAB game and stats ingestion |
| `SCRAPER_HTML_CACHE_DIR` | Optional scraper cache path |
| `SCRAPER_FORCE_CACHE_REFRESH` | Optional cache bypass |

## Removed Configuration

The service is catch-up-only by construction. These old switches and secrets are not used by the active runtime:

- `SDA_CATCHUP_ONLY`
- `SCRAPER_CATCHUP_ONLY`
- `ODDS_API_KEY`
- `DATAGOLF_API_KEY`
- `X_AUTH_TOKEN`
- `X_CT0`
- `X_BEARER_TOKEN`
- `SCRAPER_ROLE`

## Validation

- `api/app/validate_env.py` validates production API requirements.
- `scraper/sports_scraper/validate_env.py` validates the catch-up worker's core database and Redis requirements.
- `Settings.validate_runtime_settings()` rejects production/staging API startup when `API_KEY` is missing.

## Non-Active Accepted Keys

Some settings remain accepted by Pydantic because historical modules still import the shared settings class. Examples include email, Stripe, frontend, odds, and FairBet-related values. They are not part of the mounted catch-up API or scheduled worker path.
