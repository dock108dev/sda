# Infrastructure And Local Development

Docker Compose is the supported local runtime.

## Quick Start

```bash
cd infra
cp .env.example .env
docker compose --profile dev up -d --build
```

Local URLs:

- Web: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

## Profiles

| Profile | Purpose |
| --- | --- |
| `dev` | Local development |
| `prod` | Production runtime |
| `observability` | Optional OTel, Prometheus, and Grafana |

## Services

| Service | Port | Purpose |
| --- | --- | --- |
| `postgres` | host-bound `127.0.0.1:${POSTGRES_PORT:-5432}` | PostgreSQL |
| `redis` | internal only | Celery broker/backend and task hold |
| `api` | `8000` | FastAPI catch-up API |
| `scraper` | none | Celery worker running `poll_live_pbp` |
| `scraper-beat` | none | Celery beat scheduler |
| `migrate` | none | Alembic migration runner |
| `web` | `3000` | Local admin/client web app |
| `backup` | none | PostgreSQL backup service |
| `log-relay` | internal `9999` | Docker log relay sidecar |

Observability services are only created with the `observability` profile:

- `otel-collector`: OTLP receiver on `4317` and `4318`, Prometheus scrape
  endpoint on `8889`
- `prometheus`: metrics UI on `9090`
- `grafana`: dashboard UI on `3001`

## Common Commands

```bash
docker compose --profile dev up -d --build
docker compose --profile dev down
docker compose logs -f api
docker compose logs -f scraper
docker compose --profile dev run --rm migrate
```

## Migrations

Run migrations explicitly:

```bash
docker compose --profile dev run --rm migrate
```

Migration files live in `api/alembic/versions/`. The default migrate service
runs `infra/scripts/migrate_safely.py`, which sets the global task hold, drains
in-flight worker transactions, runs Alembic, and clears the hold on exit.

## Backups

```bash
docker exec sports-postgres /scripts/backup.sh
CONFIRM_DESTRUCTIVE=true docker exec sports-postgres /scripts/restore.sh /backups/latest.sql.gz
```

Restores are destructive and require `CONFIRM_DESTRUCTIVE=true`.
