# Environment And Config

Use `infra/.env.example` as the local template. Do not commit local `.env`
files.

The current runtime reads configuration from:

- `api/app/config.py` for FastAPI and the Next.js proxy-facing API behavior,
- `scraper/sports_scraper/config.py` for the Celery worker/beat process,
- `infra/docker-compose.yml` for service-local URLs and container wiring,
- `scripts/lint_env_file.py` for production deploy env-file hygiene.

## Required Runtime Values

| Variable | Required | Notes |
| --- | --- | --- |
| `POSTGRES_DB` | compose | Database name for Docker Postgres. |
| `POSTGRES_USER` | compose | Database user. |
| `POSTGRES_PASSWORD` | compose | Database password. |
| `REDIS_PASSWORD` | recommended | Redis password. |
| `ENVIRONMENT` | yes | `development`, `staging`, or `production`. |
| `DATABASE_URL` | set by compose | API and migration database URL. |
| `REDIS_URL` | set by compose | Redis URL for API and Celery-compatible Redis access. |
| `API_KEY` | production/staging | Admin API key; required by API startup validation. |
| `CONSUMER_API_KEY` | production env lint | Read-only consumer key for `/api/v1/*`; deploy env lint requires it for production files. |
| `JWT_SECRET` | production/staging | Required by API startup validation even though auth product routes are not mounted. |
| `ALLOWED_CORS_ORIGINS` | production/staging | Comma-separated origins; localhost is rejected in production/staging. |
| `ADMIN_PASSWORD` | production web | Basic auth password for `/admin/*` and `/proxy/*`; keep independent from database credentials. |
| `CBB_STATS_API_KEY` | when using NCAAB feeds | Needed by CBB/NCAAB integrations. |
| `OPENAI_API_KEY` | optional | Enables AI-enhanced game context copy when requested. |

## API Settings

| Variable | Active use |
| --- | --- |
| `ENVIRONMENT` | Controls docs visibility and production/staging validation. |
| `API_KEY` | Protects admin routes and is injected by the web proxy as `SPORTS_API_KEY`. |
| `CONSUMER_API_KEY` | Protects `/api/v1/*` when configured and prevents admin-key use on consumer routes. |
| `DATABASE_URL` | API database access. |
| `REDIS_URL` | Rate limiting, task hold reads, cache/metrics paths, and Redis-backed helpers. |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Optional Celery Redis overrides; the broker falls back to `REDIS_URL`. |
| `ADMIN_ORIGINS` | Admin-origin role resolution for trusted admin UI contexts. |
| `TRUST_FORWARDED_ORIGIN` | Honors `X-Forwarded-Origin` only when explicitly enabled. |
| `ALLOWED_CORS_ORIGINS` | CORS middleware. |
| `RATE_LIMIT_*`, `ADMIN_RATE_LIMIT_*` | API and admin fixed-window rate limits. |
| `RATE_LIMIT_USE_REDIS` | Uses Redis buckets for shared rate limits; falls back to memory on Redis errors. |
| `AUTH_ENABLED` | Local/dev JWT bypass; rejected in production/staging when false. |
| `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES` | JWT helpers used by dormant auth/club modules and validation. |
| `EMAIL_BACKEND` | `smtp` or `ses`; anything else is rejected. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS` | SMTP transport settings. |
| `AWS_REGION` | SES region when `EMAIL_BACKEND=ses`. |
| `MAIL_FROM` | Sender address for transactional email. |
| `FRONTEND_URL` | Base URL used in email links. |
| `ONBOARDING_NOTIFICATION_EMAIL` | Recipient for persisted onboarding claim notifications if onboarding is mounted in the future. |
| `OPENAI_API_KEY` | Optional context sentence polishing. |
| `OPENAI_MODEL_CLASSIFICATION`, `OPENAI_MODEL_SUMMARY` | Optional OpenAI model overrides; empty strings fall back to code defaults. |

`RESEND_API_KEY` appears in compose/env examples from an older mail plan, but
the current API email service does not read it. Current supported backends are
SMTP and SES.

## Scraper Settings

| Variable | Active use |
| --- | --- |
| `DATABASE_URL` | Celery worker database access; asyncpg URLs are converted to psycopg. |
| `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB` | Celery broker/backend, task locks, and hold state. |
| `CBB_STATS_API_KEY` | NCAAB game and stats ingestion. |
| `SCRAPER_HTML_CACHE_DIR` | Optional scraper cache path. |
| `SCRAPER_FORCE_CACHE_REFRESH` | Optional cache bypass. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Enables OpenTelemetry export when set. |

The scraper settings still accept historical odds/golf variables because those
modules remain importable, but no odds or golf task is included, routed, or
beat-scheduled by the active Celery app:

- `ODDS_API_KEY`
- `ODDS_API_REGIONS`
- `ODDS_API_WEEKLY_CAP`
- `DATAGOLF_API_KEY`

## Web Settings

| Variable | Active use |
| --- | --- |
| `NEXT_PUBLIC_SPORTS_API_URL` | Browser-visible API URL fallback and build arg. |
| `SPORTS_API_INTERNAL_URL` | Server-side Next.js proxy target inside Docker. |
| `SPORTS_API_KEY` | Admin key injected by the Next.js `/proxy/*` route; compose sets it from `API_KEY`. |
| `ADMIN_PASSWORD` | Basic auth password for `/admin/*` and `/proxy/*` when required. |
| `ENVIRONMENT` | Causes web admin auth to be required in production/staging. |

## Removed Configuration

The scheduled worker path is catch-up-only by construction. These old switches
and secrets are not used by the active scheduled worker or mounted catch-up
route path:

- `SDA_CATCHUP_ONLY`
- `SCRAPER_CATCHUP_ONLY`
- `X_AUTH_TOKEN`
- `X_CT0`
- `X_BEARER_TOKEN`
- `SCRAPER_ROLE`
- `STRIPE_*`

Payment provider configuration is no longer accepted; `STRIPE_*` keys fail
deploy env lint as unknown variables.

## Validation

- `api/app/validate_env.py` validates API startup requirements and rejects
  local database URLs in production.
- `scraper/sports_scraper/validate_env.py` validates the catch-up worker's core
  database and Redis requirements.
- `Settings.validate_runtime_settings()` rejects production/staging API startup
  when `API_KEY` is missing, weak, or paired with unsafe CORS/JWT/auth settings.
- `scripts/lint_env_file.py` rejects unknown deployment env keys and requires
  production env files to include `ALLOWED_CORS_ORIGINS`, `API_KEY`,
  `CONSUMER_API_KEY`, `DATABASE_URL`, `ENVIRONMENT`, `JWT_SECRET`, and
  `REDIS_URL`.
- Compose derives service-local `DATABASE_URL`, `REDIS_URL`, and
  `CELERY_BROKER_URL` from `infra/.env`.

## Runtime Source Of Truth

Production relevance is determined by `api/main.py`,
`scraper/sports_scraper/celery_app.py`, and `infra/docker-compose.yml`.
Environment variables accepted by dormant modules do not make those modules
active.
