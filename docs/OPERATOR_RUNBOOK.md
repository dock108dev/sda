# Operator Runbook

Production operations guide for sports-data-admin.

## Architecture

```mermaid
flowchart LR
  subgraph Client
    Admin[Admin Browser]
  end

  subgraph Edge
    Caddy[Caddy\nsports-data-admin.dock108.ai]
  end

  subgraph App
    Web[Admin UI (Next.js)]
    API[FastAPI API]
    Worker[Celery Worker (Scraper)]
    SocialWorker[Social Scraper]
    BulkWorker[Social Bulk]
  end

  subgraph Data
    Postgres[(Postgres)]
    Redis[(Redis)]
  end

  Admin -->|HTTPS| Caddy --> Web
  Web --> API
  API --> Postgres
  API --> Redis
  Worker --> Postgres
  Worker --> Redis
  SocialWorker --> Postgres
  SocialWorker --> Redis
  BulkWorker --> Postgres
  BulkWorker --> Redis
```

---

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full deployment flow including GitHub secrets, edge routing, and rollback strategy.

### Quick Manual Deploy

```bash
ssh root@<server-ip>
cd /opt/sports-data-api/infra

echo $GHCR_TOKEN | docker login ghcr.io -u dock108 --password-stdin
docker compose --profile prod pull
docker compose --profile prod run --rm migrate
docker compose --profile prod up -d
docker compose --profile prod ps
```

---

## Health Checks

```bash
# API health (returns 503 if DB is unavailable)
curl -f http://localhost:8000/healthz

# Container health
docker compose ps
docker inspect --format='{{.State.Health.Status}}' sports-api
```

---

## Backups & Restore

See [INFRA.md](INFRA.md#database-backup--restore) for full backup/restore procedures.

### Quick Reference

```bash
# Manual backup
docker exec sports-postgres /scripts/backup.sh

# Restore (destructive)
CONFIRM_DESTRUCTIVE=true docker exec sports-postgres /scripts/restore.sh /backups/sports_YYYYMMDD.sql.gz
```

Restore uses `DROP DATABASE ... WITH (FORCE)` on Postgres 16+ so you don't need to stop app containers first.

---

## Admin Access

### SSH Tunnel (Private Access)

```bash
ssh -L 9000:localhost:3000 ops@your-host
```

Then visit `http://localhost:9000`.

---

## Startup Validation (Fail-Fast)

Containers validate required environment at startup and exit if misconfigured.

**API required:**
- `ENVIRONMENT` (must be `development`, `staging`, or `production`)
- `DATABASE_URL`
- `ALLOWED_CORS_ORIGINS` (production only, must not include `localhost`)

**Scraper/worker required:**
- `ENVIRONMENT`
- `DATABASE_URL`
- `REDIS_URL`
- `ODDS_API_KEY` (production only)
- `X_BEARER_TOKEN` **or** `X_AUTH_TOKEN` + `X_CT0` (production only)

**Production-only constraints:**
- `DATABASE_URL` and `REDIS_URL` must not point at `localhost`
- `DATABASE_URL` must not use default `postgres:postgres` credentials

For the full environment variable reference, see [INFRA.md](INFRA.md#environment-variables).

### Destructive Operation Guardrails

- `init_db` (SQLAlchemy `create_all`) is blocked in production/staging
- `/scripts/restore.sh` requires `CONFIRM_DESTRUCTIVE=true`

---

## Troubleshooting

### Container keeps restarting

- Check environment validation errors: `docker compose logs <service>`
- Verify required env vars are set (see [Startup Validation](#startup-validation-fail-fast))
- Check database connectivity

For deployment troubleshooting (SSH, GHCR, health checks), see [DEPLOYMENT.md](DEPLOYMENT.md#troubleshooting).

For local development troubleshooting (port conflicts, DB connections), see [INFRA.md](INFRA.md#troubleshooting).

---

## See Also

- [INFRA.md](INFRA.md) - Docker configuration, environment variables, backups
- [DEPLOYMENT.md](DEPLOYMENT.md) - Full deployment flow, edge routing, rollbacks
