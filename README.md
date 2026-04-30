# Sports Data Admin

Centralized sports data platform for Dock108 applications: ingestion, normalization, and serving for odds, play-by-play, box scores, social signals, and admin workflows.

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

- Infrastructure and runtime setup: `docs/ops/infra.md`
- Deployment runbook: `docs/ops/deployment.md`
- Operational procedures: `docs/ops/runbook.md`

## Repository Layout

- `api/` FastAPI backend and services
- `scraper/` Celery ingestion workers and narrative pipeline
- `web/` Next.js admin UI
- `packages/` shared TypeScript types and UI primitives
- `infra/` Docker and deployment assets
- `docs/` full technical documentation

## Further documentation

Start at [`docs/index.md`](docs/index.md). For large-module inventory and lint conventions, see [`docs/file-size-inventory.md`](docs/file-size-inventory.md).

Key references:

| Topic | Doc |
|-------|-----|
| Env vars & settings | [`docs/env-and-config.md`](docs/env-and-config.md) |
| Celery schedules & queues | [`docs/scheduler-and-jobs.md`](docs/scheduler-and-jobs.md) |
| Ops (Docker, deploy, runbook) | [`docs/ops/`](docs/ops/) |
| API contract | [`docs/api.md`](docs/api.md) |
