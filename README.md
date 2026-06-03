# Sports Data Admin

Sports Data Admin is the backend service for Scroll Down Sports catch-up data. It serves compact game lists and normalized game detail feeds built from play-by-play, player stats, team stats, and box scores.

The current runtime is intentionally small:

- FastAPI API at `api/`
- Celery scraper worker and beat scheduler at `scraper/`
- Docker/runtime assets at `infra/`
- Optional local admin web app at `web/`

## Run Locally

```bash
cd infra
cp .env.example .env
docker compose --profile dev up -d --build
```

Local endpoints:

- Admin UI: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/healthz`

## Deployment Basics

Production uses the same compose file with the `prod` profile:

```bash
cd infra
docker compose --profile prod pull --policy always
docker compose --profile prod run --rm migrate
docker compose --profile prod up -d --remove-orphans
```

Set production secrets in `infra/.env`, especially `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `API_KEY`, `JWT_SECRET`, and `ALLOWED_CORS_ORIGINS`.

## Documentation

Start with [`docs/index.md`](docs/index.md).

Useful references:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/api.md`](docs/api.md)
- [`docs/env-and-config.md`](docs/env-and-config.md)
- [`docs/scheduler-and-jobs.md`](docs/scheduler-and-jobs.md)
- [`docs/ops/infra.md`](docs/ops/infra.md)
- [`docs/ops/security.md`](docs/ops/security.md)
- [`docs/maintenance/oversized-files.md`](docs/maintenance/oversized-files.md)
