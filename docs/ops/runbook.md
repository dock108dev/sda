# Runbook

## Health Checks

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/ready
docker compose --profile dev ps
```

`/healthz` only verifies API liveness. `/ready` checks database connectivity.

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
  -d '{"taskName": "poll_live_pbp"}'
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
