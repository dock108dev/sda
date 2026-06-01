# Deployment

Production runs the same service set as local development with the `prod` compose profile.

## Deploy

The manual deploy workflow in `.github/workflows/deploy-recent-image.yml` SSHes to the server, syncs the repo, updates Caddy from `infra/Caddyfile`, logs into GHCR, pulls images, runs migrations, starts compose, and waits for the API container health check.

Equivalent manual command shape:

```bash
cd infra
docker compose --profile prod pull --policy always
docker compose --profile prod run --rm migrate
docker compose --profile prod up -d --remove-orphans
```

The full CI/CD workflow in `.github/workflows/backend-ci-cd.yml` can also build, push, and deploy when manually dispatched with `full_deploy=true`.

Both deploy workflows run the Scroll Down card-feed smoke check after the API
container is healthy. The check scans a dated `/api/v1/games` window with
pagination, selects games with play-by-play, then validates
`/api/v1/feed/games/{game_id}/cards` for the frontend contract: cards,
`importance`, `modeEligibility`, `visualImportance`, `leadIn`, and
non-duplicated important-card `stageSetting`.

Deploy first refreshes materialized card feeds for the 72-hour lookback and
72-hour lookahead window, then validates the matching three-day dated window.
The validator skips older PBP candidates whose card feed has not been
materialized and fails only if no materialized feed in the scanned window
passes the frontend contract.

The smoke check intentionally fails when the scanned window has no games with
`hasPbp=true` and `playCount>0`. That is a data-ingestion problem, not a valid
consumer route contract. Run `poll_live_pbp`, backfill the relevant window, or
widen `--lookback-days` for manual diagnosis.

Manual PBP refresh:

```bash
curl -X POST http://localhost:8000/api/admin/tasks/trigger \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task_name": "poll_live_pbp", "args": []}'
```

Equivalent manual verification:

```bash
python3 scripts/validate_scroll_down_feed.py \
  --base-url http://localhost:8000 \
  --env-file infra/.env \
  --lookback-days 3 \
  --lookahead-days 3
```

To also require finalized LLM recap output for selected completed games:

```bash
python3 scripts/validate_scroll_down_feed.py \
  --base-url http://localhost:8000 \
  --env-file infra/.env \
  --game-id 190584 \
  --check-summary \
  --require-summary
```

## Required Secrets

Set these in `infra/.env` or your deployment secret manager:

- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `API_KEY`
- `CONSUMER_API_KEY`
- `JWT_SECRET`
- `ALLOWED_CORS_ORIGINS`
- `OPENAI_API_KEY` when AI context copy is desired
- `CBB_STATS_API_KEY` when NCAAB feeds are enabled

## Rollback

Use the previous image tag and restart the application services:

```bash
IMAGE_TAG=<previous-tag> docker compose --profile prod up -d api scraper scraper-beat web
```

Run migrations only when the rollback plan accounts for schema compatibility.

## CI Workflows

- `backend-ci-cd.yml`: runs backend, scraper, API, web, and repository hygiene checks. Manual `full_deploy=true` builds GHCR images and deploys.
- `deploy-recent-image.yml`: manually deploys an existing image tag, defaulting to `latest`, and always syncs the active Caddy site block from `infra/Caddyfile`.
- `realtime-load-test.yml`: manual load harness for the non-production
  `/api/admin/realtime/test-emit` endpoint and Redis Streams path. It is not
  part of the active catch-up runtime because product realtime subscribe/stream
  routes are not mounted.
