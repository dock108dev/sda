# Infrastructure And Local Development

Docker Compose is the supported local runtime.

The `prod` profile and Caddy assets are retained as inactive architecture
history. They are not a supported deployment path while the repository is in
maintenance-only mode.

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
| `prod` | Historical production-shaped runtime; inactive and unsupported |
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

The host-mapped API, web, Postgres, and observability ports are bound to
`127.0.0.1` in compose. Caddy was the public-edge design for the historical
production runtime; no active target is maintained by this repository.

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

Health endpoint meanings:

- `/health`: API process liveness only.
- `/healthz`: API liveness plus database and Redis component checks; database
  failure returns `503`, Redis failure is reported in the payload while the
  endpoint can still return `200`.
- `/ready`: strict database and Redis readiness; either failure returns `503`.

## Migrations

Run local-development migrations explicitly:

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
These backup and restore examples are for an operator-controlled local runtime,
not an active production service.
