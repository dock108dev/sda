# API

The API is a FastAPI service focused on catch-up game data. Runtime OpenAPI is available locally at `GET /docs` and `GET /openapi.json`; those docs are disabled in production and staging.

Authoritative route wiring lives in `api/main.py`. The only mounted product router is `api/app/routers/sports/catchup.py`, mounted under `/api/admin/sports`.

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

## Operations Routes

### Health

- `GET /health`
- `GET /healthz`
- `GET /ready`
- `GET /metrics`

### Task Control

The admin task registry exposes only `poll_live_pbp`. The hold endpoints remain available for migrations and operator safety:

- `GET /api/admin/tasks/hold`
- `PUT /api/admin/tasks/hold`
- `GET /api/admin/tasks/registry`
- `POST /api/admin/tasks/trigger`

Trigger body:

```json
{
  "taskName": "poll_live_pbp",
  "args": [],
  "kwargs": {}
}
```

## Not Supported

The current API does not mount legacy consumer, odds, FairBet, golf, simulator, analytics, social, billing, auth, or realtime product routes.
