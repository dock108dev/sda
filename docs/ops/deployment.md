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

## Required Secrets

Set these in `infra/.env` or your deployment secret manager:

- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `API_KEY`
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
