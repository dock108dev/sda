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

## Further Documentation

Start at `docs/index.md` for architecture, API reference, data model guides, ingestion flow, and operations docs.
