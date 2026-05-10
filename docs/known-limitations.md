# Known limitations & intentional tradeoffs

Behaviors that are **by design** or **operational caveats** — each point maps to code or config you can inspect.

## Configuration

- **Unknown environment variables:** API `Settings` uses Pydantic `extra="ignore"`. Misspelled optional keys are ignored without error ([`api/app/config.py`](../api/app/config.py)).
- **`AUTH_ENABLED=false`:** Resolves all JWT-role paths to admin in development; **blocked** in production/staging by `validate_runtime_settings`.

## Rate limiting

- **`RATE_LIMIT_USE_REDIS`:** On Redis errors, middleware falls back to **in-memory** sliding windows — limits are **per API process**, not global across replicas ([`api/app/middleware/rate_limit.py`](../api/app/middleware/rate_limit.py)). Prometheus counter `rate_limit_redis_fallback_total` tracks fallbacks.

## Realtime

- **`API_KEY` unset:** SSE/WebSocket allow anonymous access only when `ENVIRONMENT` is **not** `production` or `staging` ([`api/app/realtime/auth.py`](../api/app/realtime/auth.py)).
- **Redis bridge:** If `RealtimeManager` publishes without a Redis streams bridge in production/staging, a one-shot error is logged — normal startup wires the bridge in app lifespan ([`api/main.py`](../api/main.py) lifespan).

## Webhooks

- **Stripe handler:** Database errors on the synchronous path enqueue Celery retry and return **HTTP 202** — Stripe sees acceptance; processing continues asynchronously ([`api/app/routers/webhooks.py`](../api/app/routers/webhooks.py)).

## Odds polling (deliberately paused)

- **Pregame and golf odds polling are off by default.** Three flags in
  [`scraper/sports_scraper/config_sports.py`](../scraper/sports_scraper/config_sports.py)
  default to `False`: `PREGAME_ODDS_ENABLED`, `GOLF_ODDS_ENABLED`,
  `LIVE_ODDS_ENABLED`. While off:
  - `sync_mainline_odds` and `sync_prop_odds` are not registered with
    Celery beat — no automatic refresh of `fairbet_game_odds_work`.
  - `golf_sync_odds` is not registered with beat (golf leaderboard
    polling is unaffected).
  - `live_orchestrator_tick` runs but `live_odds_tasks` short-circuit on
    the runtime guard.
  - `/api/fairbet/odds` and `/api/fairbet/live` continue to serve
    whatever is in the work table / Redis as of the last refresh before
    the flags were turned off.
- Flip a flag to `True` and restart the scraper to resume scheduling.
  See [Scheduler & background jobs](scheduler-and-jobs.md#pregame--golf-odds-gating).

## Dependency scanning

- **GitHub Actions:** The advisory `pip-audit` + `pnpm audit` job uses `continue-on-error: true` — findings do not block merges ([`.github/workflows/backend-ci-cd.yml`](../.github/workflows/backend-ci-cd.yml)).

## Intentionally not documented here

- Per-league ingestion edge cases — see [Data sources](ingestion/data-sources.md).
- ML / analytics caveats — see [Analytics](analytics.md).
