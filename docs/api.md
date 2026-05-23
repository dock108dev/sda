# API

The API is a FastAPI service centered on Scroll Down catch-up data plus the
operator routes needed to inspect and control that data. Runtime OpenAPI is
available locally at `GET /docs` and `GET /openapi.json`; those docs are
disabled in production and staging.

Authoritative route wiring lives in `api/main.py`. Catch-up list/detail
ownership lives in `api/app/routers/sports/catchup.py`, mounted under
`/api/admin/sports`.

## Authentication

All catch-up routes require `X-API-Key` when `API_KEY` is configured. Development environments without `API_KEY` allow requests and log a warning. Production and staging should always configure `API_KEY`.

```http
GET /api/admin/sports/games HTTP/1.1
Host: localhost:8000
X-API-Key: local-key
```

Health endpoints do not require auth.

## Catch-Up Routes

### `GET /api/admin/sports/games`

Returns games from the catch-up window, defaulting to `-72h` through `+48h` from the current time.

Common query parameters:

- `league`: repeatable league code filter such as `?league=NBA&league=MLB`
- `team`: case-insensitive match against team name, short name, or abbreviation
- `startDate`: inclusive Eastern-date window start
- `endDate`: inclusive Eastern-date window end
- `limit`: page size from 1 to 200, default `100`
- `offset`: zero-based page offset

The response is spoiler-light by design. It includes game identity, teams, date, league, status, capability flags, and short context copy. It does not expose the detail payload's top-level final/current `score`; live games may include `liveSnapshot.score` when play-by-play has already established period and clock state.

Response envelope fields:

- `games`
- `total`
- `nextOffset`
- `withBoxscoreCount`
- `withPlayerStatsCount`
- `withPbpCount`

### `GET /api/admin/sports/games/{game_id}`

Returns the full scroll-down detail payload for one game:

- game metadata and score
- ordered play-by-play
- player stats
- team stats

Clients should reveal this data by scrolling through the game detail, not from the homepage list.

### `GET /api/admin/sports/games/{game_id}/context`

Returns two to three short context sentences explaining why a user might want to catch up on the game. The service uses deterministic local data first.

Optional query parameters:

- `enhance`: when `true`, the service attempts OpenAI polishing and falls back to deterministic copy on any issue.

The response includes `source`, currently `template` or `openai`.

## Mounted Route Boundary

`api/main.py` currently mounts these route families:

- `/api/admin/sports/*`: catch-up list/detail routes plus sports admin
  diagnostics, runs, jobs, timeline, pipeline, play-by-play, resolution,
  coverage, and quality endpoints.
- `/api/admin/*`: platform stats, task hold/trigger controls, circuit breaker
  health, quality review, and the non-production realtime test emitter.
- `/api/social/*`: manual social post and account CRUD over existing database
  records.
- `/api/v1/games/{game_id}/summary`: consumer-safe cached game summary status
  or recap response.
- `/health`, `/healthz`, `/ready`, and `/metrics`: unauthenticated health and
  metrics endpoints.

The catch-up list/detail endpoints are the primary product surface for Scroll
Down clients. The other mounted routes are supporting admin, observability, or
legacy-adjacent data access surfaces; they are not Celery schedules by
themselves.

## Operations Routes

### Health

- `GET /health`
- `GET /healthz` checks API liveness plus database and Redis connectivity, but
  only database failure changes the status to `503`.
- `GET /ready` returns `503` when database or Redis connectivity fails.
- `GET /metrics`

### Task Control

The admin task registry exposes only `poll_live_pbp`. The hold endpoints remain available for migrations and operator safety:

- `GET /api/admin/tasks/hold`
- `PUT /api/admin/tasks/hold`
- `GET /api/admin/tasks/registry`
- `POST /api/admin/tasks/trigger`
- `GET /api/admin/social/session-health`

Trigger body:

```json
{
  "taskName": "poll_live_pbp",
  "args": []
}
```

### Realtime Test Emitter

`POST /api/admin/realtime/test-emit` writes synthetic events to Redis Streams
for load-test harnesses. The endpoint returns `403` in production and staging.
Product realtime subscribe/stream routes are not mounted by the current API.

## Not Supported

The current API does not mount FairBet, odds/model-odds, golf, simulator,
analytics experiment, commerce, billing, onboarding, preferences, auth product,
Stripe webhook, club, or product realtime subscribe/stream routers.
