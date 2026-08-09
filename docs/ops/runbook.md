# Runbook

This runbook is for an operator-controlled local development runtime only. The
repository is maintenance-only and has no supported production target.

## Health Checks

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/ready
docker compose --profile dev ps
```

Health endpoint meanings:

- `/health`: process liveness only.
- `/healthz`: checks database and Redis; database failure returns `503`, Redis
  failure is reported in the payload while the endpoint can still return `200`.
- `/ready`: strict readiness; database or Redis failure returns `503`.

## Logs

```bash
docker compose logs -f api
docker compose logs -f scraper
docker compose logs -f scraper-beat
```

## Pause Scheduled Work

Use the admin task hold before risky migrations or restores:

```bash
curl -X PUT http://localhost:8000/api/admin/tasks/hold \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"held": true}'
```

Release it with `{"held": false}`.

## Trigger A Refresh

```bash
curl -X POST http://localhost:8000/api/admin/tasks/trigger \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task_name": "poll_live_pbp", "args": []}'
```

Confirm the worker registered the active task:

```bash
docker compose --profile dev exec scraper \
  celery -A sports_scraper.celery_app.app inspect registered
```

## Migrations

```bash
docker compose --profile dev run --rm migrate
```

## Restore

Restores are destructive:

```bash
CONFIRM_DESTRUCTIVE=true docker exec sports-postgres /scripts/restore.sh /backups/latest.sql.gz
```

Pause scheduled work before restores and release the hold after the API and worker are healthy.
