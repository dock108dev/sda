# API

The API is a FastAPI service with two active product-facing route families:

- `/api/v1/*`: consumer-safe read routes.
- `/api/admin/*`, `/api/admin/sports/*`, and `/api/social/*`: admin and
  operator routes.

Authoritative route wiring lives in `api/main.py`. Runtime OpenAPI is available
locally at `GET /docs` and `GET /openapi.json`; those docs are disabled in
production and staging.

## Authentication

| Route family | Key dependency | Scope |
| --- | --- | --- |
| `/api/v1/*` | `verify_consumer_api_key` | Read-only consumer scope. Uses `CONSUMER_API_KEY` when set, otherwise falls back to `API_KEY`. |
| `/api/admin/*` | `verify_api_key` | Admin scope. Rejects `CONSUMER_API_KEY` when consumer and admin keys differ. |
| `/api/admin/sports/*` | `verify_api_key` | Admin sports and operator scope. |
| `/api/social/*` | `verify_api_key` | Manual social record access. |
| `/health`, `/healthz`, `/ready`, `/metrics` | none | Operational endpoints; protect by network/proxy if public exposure is possible. |

Development without configured keys is permissive and logs warnings. The
production/staging code paths require `API_KEY`; production-shaped env lint also
requires `CONSUMER_API_KEY`. These are validation rules, not deployment setup
instructions.

```http
GET /api/v1/games HTTP/1.1
Host: localhost:8000
X-API-Key: consumer-or-local-key
```

```http
GET /api/admin/sports/games HTTP/1.1
Host: localhost:8000
X-API-Key: admin-key
```

## Consumer Catch-Up Routes

`/api/v1/games` delegates to the same catch-up list implementation as the admin
sports list route, but through the consumer key dependency. Consumer game detail
is only supported through the normalized card feed:
`/api/v1/feed/games/{game_id}/cards`.

### `GET /api/v1/games`

Returns games from the catch-up window, defaulting to `-72h` through `+48h`
from the current time.

Common query parameters:

- `league`: repeatable league code filter such as `?league=NBA&league=MLB`
- `team`: case-insensitive match against team name, short name, or abbreviation
- `startDate`: inclusive Eastern-date window start
- `endDate`: inclusive Eastern-date window end
- `limit`: page size from 1 to 200, default `100`
- `offset`: zero-based page offset

The response is a compact home-list summary. It includes game identity, teams,
date, league, status, capability flags, and short context copy. Detail score,
team stats, and player stats live on the normalized card-feed endpoint.

Response envelope fields:

- `games`
- `total`
- `nextOffset`
- `withBoxscoreCount`
- `withPlayerStatsCount`
- `withPbpCount`

### `GET /api/v1/feed/games/{game_id}/cards`

Returns the SSOT detail payload for one game as normalized narrative cards. The
legacy consumer detail payload at `/api/v1/games/{game_id}` is no longer
supported; admin-only detail remains under `/api/admin/sports/*`.

### `GET /api/v1/games/{game_id}/summary`

Returns the cached generated summary for a completed game when available.
Otherwise it returns a status object such as `RECAP_PENDING`, `PREGAME`,
`IN_PROGRESS`, `POSTPONED`, or `CANCELED`.

## Admin Sports Routes

The admin sports catch-up routes are mounted under `/api/admin/sports`:

- `GET /api/admin/sports/games`
- `GET /api/admin/sports/games/{game_id}`
- `GET /api/admin/sports/games/{game_id}/context`

`/context` returns two to three short context sentences. It uses deterministic
local data by default. When `enhance=true`, it may use OpenAI to polish that
copy and keeps deterministic copy available when polishing is unavailable.

Additional `/api/admin/sports/*` routes support operators and the admin UI:

- card-feed materialization and refresh
- scrape run creation, cancellation, cache clearing, and bulk preview/backfill
- game resync and job cancellation
- teams, team colors, and team social metadata
- timeline generation and inspection
- pipeline run/stage/bulk controls
- play-by-play inspection and resolution diagnostics
- missing-PBP, conflict, season-audit, and Docker log inspection

These routes are admin surfaces. They are not separate scheduled product
runtimes.

## Admin Operations Routes

### Health And Metrics

- `GET /health`: process liveness only.
- `GET /healthz`: checks database and Redis; database failure returns `503`,
  Redis failure is reported in the payload while the endpoint can still return
  `200`.
- `GET /ready`: strict readiness; database or Redis failure returns `503`.
- `GET /metrics`: Prometheus exposition format, unauthenticated at FastAPI.

### Task Control

The admin task registry exposes only `poll_live_pbp`. The calendar-stub task is
beat-scheduled but is not exposed through the admin trigger registry.

- `GET /api/admin/tasks/hold`
- `PUT /api/admin/tasks/hold`
- `GET /api/admin/tasks/registry`
- `POST /api/admin/tasks/trigger`
- `GET /api/admin/social/session-health`

Trigger body:

```json
{
  "task_name": "poll_live_pbp",
  "args": []
}
```

`/api/admin/social/session-health` reads the latest Playwright session health
snapshot from Redis. It does not schedule social collection.

### Realtime Test Emitter

`POST /api/admin/realtime/test-emit` writes synthetic events to Redis Streams
for load-test harnesses. The endpoint returns `403` in production and staging.
Product realtime subscribe/stream routes are not mounted by the current API.

## Not Mounted

The current API does not mount auth product routes, onboarding, preferences,
club-management routes, FairBet, odds/model-odds, golf, simulator, analytics
experiment routes, commerce, billing, payment webhooks, or product realtime
subscribe/stream routers.
