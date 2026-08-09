# Architecture

Sports Data Admin is the backend and admin control plane for Scroll Down Sports
catch-up data. The repository is maintenance-only and has no active deployment.
Current runtime relevance is defined by:

- `api/main.py` for mounted API routes,
- `scraper/sports_scraper/celery_app.py` for scheduled worker behavior,
- `infra/docker-compose.yml` for running services.

Files outside those boundaries can be importable for tests, migrations, or
future work without being part of the active runtime.

## Runtime Shape

```text
External league feeds
        |
        v
scraper Celery beat/worker: calendar stubs + live PBP/stats
        |
        v
PostgreSQL: games, plays, player stats, team stats, materialized card feeds
        |
        v
FastAPI: consumer catch-up API plus admin/operator routes
        |
        v
Next.js admin UI and Scroll Down clients
```

Redis is used for Celery broker/backend, task locks, the global task hold flag,
rate-limit/cache paths, and the non-production realtime test emitter. The API
reads PostgreSQL directly. OpenAI is optional and is used only to polish catch-up
context copy or generated card-feed narrative where the relevant code path
explicitly requests it.

## API

Authoritative entrypoint: `api/main.py`.

Active mounted route families:

- `/api/v1/*`: consumer-safe game list/detail/summary routes.
- `/api/admin/sports/*`: catch-up admin routes plus diagnostics, jobs, teams,
  logs, scraper runs, timeline, pipeline, play-by-play, resolution, coverage,
  and season-audit endpoints.
- `/api/admin/*`: platform stats, task hold/trigger controls, circuit breaker
  status, quality review/summary, and non-production realtime test emission.
- `/api/social/*`: manual social post and account CRUD over existing database
  records.
- `/health`, `/healthz`, `/ready`, and `/metrics`: operational endpoints.

Consumer and admin catch-up list/detail routes share the same implementation.
The difference is the key dependency: `/api/v1/*` uses consumer scope and
`/api/admin/sports/*` uses admin scope.

## Scraper

Authoritative Celery app: `scraper/sports_scraper/celery_app.py`.

Two tasks are routed and beat-scheduled:

- `poll_game_calendars`, every 15 minutes, queue `sports-scraper`
- `poll_live_pbp`, every 5 minutes, queue `sports-scraper`

`poll_game_calendars` creates or updates lightweight future game stubs across
the supported schedule feeds. `poll_live_pbp` refreshes play-by-play, player box
scores, team box scores, status, and score fields for games near the active
catch-up window. `poll_live_pbp` uses a Redis lock to avoid overlapping runs.
Worker startup marks interrupted scrape/job runs so previous crashes do not
permanently block new work.

`refresh_card_feeds` is included and routed for explicit local Celery use and
is retained in the historical deployment procedure. It is not beat-scheduled.
Other `@shared_task` definitions can exist in historical modules without being
active unless they are included, routed, and scheduled by the current Celery
app or dispatched by a mounted API route.

## Web

The web app is a Next.js admin UI. Browser API calls go through `/proxy/*`; the
proxy injects `SPORTS_API_KEY` server-side and protects `/admin/*` and
`/proxy/*` with Basic auth in production/staging or whenever `ADMIN_PASSWORD` is
set.

The web directory still contains pages for dormant product areas. Those pages
do not make the corresponding backend routers active.

## Infrastructure

Authoritative compose file: `infra/docker-compose.yml`.

Application services:

- `api`
- `scraper`
- `scraper-beat`
- `web`
- `migrate`
- `postgres`
- `redis`
- `backup`
- `log-relay`

Optional observability services are available only with the `observability`
profile:

- `otel-collector`
- `prometheus`
- `grafana`

## Not Active

The current FastAPI entrypoint does not mount separate product routers for
auth, onboarding, club management, FairBet, odds/model-odds, golf, simulator,
analytics experiments, or product realtime streams. The current Celery beat app
does not schedule social scraping, odds, golf, analytics, simulator, training,
or realtime orchestration jobs.

Commerce, billing, and payment webhook runtime code has been removed. Historical
migrations remain as database history.

## CI Boundary

GitHub Actions still runs broad tests, lint, build, dependency audit, secret
scan, SQL interpolation checks, schema/type synchronization checks, and
container builds with `push: false`. Passing CI does not mean every historical
module is active runtime or that the application is deployable; the
runtime boundary is the mounted API, scheduled Celery task, and compose service
set above.
