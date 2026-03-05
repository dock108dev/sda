# Operator Runbook

Production operations guide for sports-data-admin.

## Architecture Overview

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
    Storage[(S3/Storage Box)]
  end

  Admin -->|HTTPS| Caddy --> Web
  Web --> API
  API --> Postgres
  API --> Redis
  Worker --> Postgres
  Worker --> Redis
  Worker --> Storage
  SocialWorker --> Postgres
  SocialWorker --> Redis
  BulkWorker --> Postgres
  BulkWorker --> Redis
```

---

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full deployment flow. Key points:

1. **Deploy trigger:** Merge to `main` or manual workflow dispatch
2. **Change detection:** GitHub Actions detects which services changed
3. **Tests:** Unit tests run before deployment
4. **Build:** Images pushed to GHCR with `latest` and commit-sha tags
5. **Server update:** SSH, pull images, run migrations, restart services

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

### API Health

```bash
curl -f http://localhost:8000/healthz
```

Returns `503` if database connectivity fails. Use for deploy verification.

### Container Health

```bash
docker compose ps
docker inspect --format='{{.State.Health.Status}}' sports-api
```

---

## Migrations

Alembic migrations are run explicitly (not on startup). Migrations live in `api/alembic/versions/`.

The schema is defined in a single baseline migration with reference data (leagues, teams, social handles) seeded from `seed_data.sql`. New migrations chain linearly from the baseline.

```bash
# Run pending migrations (recommended)
docker compose --profile prod run --rm migrate

# Check current version
docker exec sports-api alembic current

# Run manually
docker exec sports-api alembic upgrade head
```

---

## Backups & Restore

### Automatic Backups (Production)

When running with `--profile prod`, the backup service runs daily at 14:00 UTC and:
- Creates a compressed SQL dump
- Stores backups in `infra/backups/`
- Keeps only the last 7 days of backups
- Maintains a `latest.sql.gz` symlink

### Manual Backup

```bash
docker exec sports-postgres /scripts/backup.sh
```

### Offsite Backup (Optional)

Copy backups to external storage:
```bash
# Copy to S3
aws s3 sync infra/backups/ s3://your-bucket/sports-backups/

# Copy to remote server
rsync -avz infra/backups/ user@backup-server:/backups/sports/
```

### Restore

```bash
gzip -cd sports_YYYYMMDDTHHMMSSZ.sql.gz | psql "${DATABASE_URL}"

# Container restore (destructive)
CONFIRM_DESTRUCTIVE=true docker exec sports-postgres /scripts/restore.sh /backups/sports_YYYYMMDD.sql.gz
```

Note: Restore uses `DROP DATABASE ... WITH (FORCE)` on Postgres 16+ so you don't need to stop app containers first.

### Destructive Operation Guardrails

- `init_db` (SQLAlchemy `create_all`) is blocked in production/staging
- `/scripts/restore.sh` requires `CONFIRM_DESTRUCTIVE=true`

---

## Admin Access

### SSH Tunnel Access

For private access without exposing the UI:
```bash
ssh -L 9000:localhost:3000 ops@your-host
```
Then visit `http://localhost:9000`.

---

## CI/CD

See [DEPLOYMENT.md](DEPLOYMENT.md) for GitHub secrets, deploy flow, and rollback strategy.

---

## Environment Variables (Production)

Production secrets live in `infra/.env` on the server (never committed).

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres connection string |
| `REDIS_URL` | Redis connection string |
| `CELERY_BROKER_URL` | Celery broker override |
| `ALLOWED_CORS_ORIGINS` | Comma-separated trusted origins |
| `RATE_LIMIT_REQUESTS` | Rate limit requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | Rate limit window size |
| `ENVIRONMENT` | Must be `production` |

### Startup Validation (Fail-Fast)

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

---

## Troubleshooting

### Container keeps restarting

- Check environment validation errors in logs
- Verify required env vars are set (see [Environment Variables](#environment-variables-production))
- Check database connectivity

For deployment troubleshooting (SSH, GHCR, health checks), see [DEPLOYMENT.md](DEPLOYMENT.md#troubleshooting).

---

## See Also

- [INFRA.md](INFRA.md) - Docker configuration and local development
- [DEPLOYMENT.md](DEPLOYMENT.md) - Full deployment flow and edge routing
