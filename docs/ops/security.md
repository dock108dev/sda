# Security And Runtime Boundaries

Sports Data Admin is maintenance-only and has no currently supported deployment
target. The production/staging behaviors below describe code-enforced runtime
boundaries if those modes are exercised in a future authorized project; they do
not claim an active production service.

This document describes the current `sports-data-admin` security boundary as
implemented by `api/main.py`, `web/src/proxy.ts`,
`web/src/app/proxy/[...path]/route.ts`, `api/app/config.py`, and
`infra/docker-compose.yml`.

Historical audit snapshots were removed because they described earlier branch
states and external repositories. Use this file plus the code paths above as the
current reference.

## Runtime Trust Boundaries

| Boundary | Current behavior |
| --- | --- |
| Browser to Next.js admin UI | `/admin/*` and `/proxy/*` require Basic auth in production/staging, or whenever `ADMIN_PASSWORD` is set. |
| Next.js proxy to FastAPI | `/proxy/*` forwards to `SPORTS_API_INTERNAL_URL` or `NEXT_PUBLIC_SPORTS_API_URL` and injects `SPORTS_API_KEY` as `X-API-Key`. |
| FastAPI admin routes | `/api/admin/*`, `/api/admin/sports/*`, and `/api/social/*` require the admin `API_KEY` through `verify_api_key`. |
| FastAPI consumer routes | `/api/v1/*` requires `CONSUMER_API_KEY` when configured, otherwise falls back to `API_KEY` for single-key development/simple deployments. |
| FastAPI health and metrics | `/health`, `/healthz`, `/ready`, and `/metrics` do not require API-key auth. Any future deployment must control exposure at its edge. |
| FastAPI to data stores | API uses PostgreSQL and Redis. Redis supports rate-limit buckets, task hold state, metrics/cache paths, and the non-production realtime test emitter. |
| Celery scraper to providers | The defined beat schedule runs `poll_game_calendars` and `poll_live_pbp` when the runtime is started. They read PostgreSQL, Redis, and league data providers. |

## Key Scope Rules

- `API_KEY` is admin-scoped. It is accepted by admin routes and rejected by
  consumer routes when `CONSUMER_API_KEY` is configured with a different value.
- `CONSUMER_API_KEY` is read-only consumer scope. It is rejected by admin
  routes when it differs from `API_KEY`.
- Development without configured keys is permissive. Production and staging
  reject missing `API_KEY` at API startup.
- `AUTH_ENABLED=false` is local-only. Production and staging reject it during
  settings validation.
- `TRUST_FORWARDED_ORIGIN` must remain false unless the reverse proxy strips
  client-supplied `X-Forwarded-Origin` and injects a trusted value itself.

## Next.js Admin Proxy

The admin web app intentionally uses `/proxy/*` so browser requests never see
the backend API key. The proxy:

- protects every `/proxy/*` request with Basic auth when auth is required,
- strips browser Basic `Authorization` before forwarding to FastAPI,
- drops hop-by-hop headers, `X-Forwarded-Origin`, and browser-supplied
  `X-API-Key`,
- injects `SPORTS_API_KEY` server-side.

Because the proxy injects an admin key, every new proxy path must be treated as
admin-capable unless the target backend route has its own stricter guard.

## Operational Endpoints

`/metrics` is unauthenticated at the FastAPI layer. Compose binds the API port
to `127.0.0.1`, and the historical design used Caddy as the public edge. Any
future deployment must protect `/metrics` at the reverse proxy or network layer.

Health endpoint semantics:

- `/health`: process liveness only.
- `/healthz`: checks database and Redis; database failure returns `503`, Redis
  failure is reported in the payload while the endpoint can still return `200`.
- `/ready`: strict readiness; database or Redis failure returns `503`.

## Disabled Or Dormant Surfaces

The current `api/main.py` does not mount auth product routes, onboarding,
club-management routes, golf, FairBet, odds/model-odds, simulator, analytics
experiments, or product realtime subscribe/stream routes.

Payment/commerce/billing/webhook runtime code has been removed. `STRIPE_*`
environment variables are rejected by production-shaped env lint.

Dormant modules and historical migrations can still exist in the repository.
They are not runtime-relevant unless mounted by `api/main.py`, scheduled by
`scraper/sports_scraper/celery_app.py`, or started by
`infra/docker-compose.yml`.

## Known Security Constraints

- The API still exposes broad admin inspection routes under `/api/admin/*` and
  `/api/admin/sports/*`; keep them behind the admin key and admin web auth.
- Audit writes are best effort and do not block successful requests.
- Redis rate-limit errors fall back to per-process memory buckets, weakening
  global enforcement across multiple API replicas.
- `/api/admin/realtime/test-emit` is for load testing only and returns `403` in
  production/staging.
- Reset, invite, auth, onboarding, golf, analytics, and product realtime modules
  should be reviewed before any future mounting decision.
