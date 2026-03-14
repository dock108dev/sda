# Infrastructure & Local Development

Docker configuration and local setup for the sports-data-admin stack.

## Quick Start (Docker)

```bash
cd infra
cp .env.example .env  # Edit credentials

# Development
docker compose --profile dev up -d --build

# Production
docker compose --profile prod up -d --build
```

**URLs:**
- Admin UI: http://localhost:3000
- API Docs: http://localhost:8000/docs
- Health: http://localhost:8000/healthz

## Profiles

| Profile | Use Case |
|---------|----------|
| `dev` | Local development |
| `prod` | Production (same services, pulls pre-built GHCR images) |

Both profiles run the same set of services.

## Services

| Service | Port | Description |
|---------|------|-------------|
| postgres | 5432 | PostgreSQL database |
| redis | 6379 | Redis for Celery queue |
| api | 8000 | FastAPI backend |
| api-worker | -- | Celery worker for API tasks (pipeline, flow generation) |
| scraper | -- | Celery worker for data ingestion |
| scraper-beat | -- | Celery scheduler (see [Data Sources](../ingestion/data-sources.md) for full schedule) |
| social-scraper | -- | Social media scraper (X/Twitter) -- live tasks only (`social-scraper` queue) |
| social-bulk | -- | Bulk social collection worker (`social-bulk` queue) -- isolated from live tasks |
| migrate | -- | One-shot Alembic migration runner |
| web | 3000 | Next.js admin UI |
| backup | -- | Daily backup service |
| log-relay | -- | Docker log relay sidecar |

### Log Relay Sidecar

Container log viewing is provided by a dedicated `log-relay` sidecar instead of mounting the Docker socket into the API container. The sidecar is the **only** container with Docker socket access and has no database credentials, API keys, or external network access (internal network only). It exposes a single `GET /logs?container=X&lines=N` endpoint on port 9999 with a hardcoded container allowlist. The API calls this sidecar over HTTP to serve the `GET /logs` endpoint.

## Files

| File | Description |
|------|-------------|
| `docker-compose.yml` | All services with dev/prod profiles |
| `api.Dockerfile` | FastAPI service |
| `scraper.Dockerfile` | Celery worker with Playwright |
| `web.Dockerfile` | Next.js admin UI |
| `scripts/backup.sh` | Database backup script |
| `scripts/restore.sh` | Database restore script |
| `backups/` | Local backup storage |
| `.env.example` | Environment template |

## Commands

```bash
# Start/stop
docker compose --profile dev up -d --build
docker compose --profile dev down

# View logs
docker compose logs -f api
docker compose logs -f scraper

# Restart a service
docker compose restart api

# Rebuild and restart
docker compose --profile dev up -d --build api

# Stop and delete volumes (WARNING: deletes data)
docker compose --profile dev down -v
```

## Migrations

Alembic migrations are run explicitly (not on every API startup). Use the dedicated
`migrate` service or run Alembic in the API container.

Migration files live in `api/alembic/versions/`. The schema starts from a single
baseline migration plus a seed migration that populates reference data (leagues,
teams, social accounts, compact mode thresholds).

```bash
# Recommended (explicit) migration job
docker compose --profile dev run --rm migrate

# Check current version
docker exec sports-api alembic current

# Run pending migrations manually
docker exec sports-api alembic upgrade head

# Create a new migration
docker exec sports-api alembic revision -m "describe change"
```

### Adding Reference Data

To add new teams, leagues, or social handles:
1. Add the INSERT to `api/alembic/versions/seed_data.sql` (for fresh installs)
2. Create a new migration that applies the change to existing databases

## Database Backup & Restore

### Automatic Backups (Production)

When running with `--profile prod`, the backup service automatically:
- Creates a compressed SQL dump daily
- Stores backups in `infra/backups/`
- Keeps only the last 7 days of backups
- Maintains a `latest.sql.gz` symlink

### Manual Backup

```bash
docker exec sports-postgres /scripts/backup.sh
ls -la infra/backups/
```

### Restore from Backup

```bash
# Restore from latest (destructive)
CONFIRM_DESTRUCTIVE=true docker exec sports-postgres /scripts/restore.sh

# Restore from specific backup
CONFIRM_DESTRUCTIVE=true docker exec sports-postgres /scripts/restore.sh /backups/sports_20260108_120000.sql.gz
```

### Offsite Backup

```bash
# Copy to S3
aws s3 sync infra/backups/ s3://your-bucket/sports-backups/

# Copy to remote server
rsync -avz infra/backups/ user@backup-server:/backups/sports/
```

## Data Migration

### Import Existing Data

If you have data in a host Postgres and want to migrate to Docker:

```bash
# 1. Export from host Postgres
pg_dump -h localhost -U dock108 dock108 > data_export.sql

# 2. Start the Docker stack
docker compose --profile dev up -d

# 3. Wait for postgres to be ready
docker compose logs -f postgres  # Wait for "ready to accept connections"

# 4. Import into Docker postgres
cat data_export.sql | docker exec -i sports-postgres psql -U sports -d sports

# 5. Verify
docker exec sports-postgres psql -U sports -d sports -c "SELECT COUNT(*) FROM sports_games;"
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_DB` | Yes | Database name |
| `POSTGRES_USER` | Yes | Database user |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `POSTGRES_PORT` | No | Host port for postgres (default: 5432) |
| `REDIS_PASSWORD` | No | Redis password |
| `ENVIRONMENT` | No | `development` or `production` |
| `RUN_MIGRATIONS` | No | Run Alembic on startup (dev-only; default false) |
| `API_KEY` | Prod/Staging | API authentication key (min 32 chars) |
| `JWT_SECRET` | Prod | Secret key for signing JWTs (`openssl rand -hex 32`) |
| `JWT_EXPIRE_MINUTES` | No | Token lifetime in minutes (default: 1440 = 24h) |
| `AUTH_ENABLED` | No | Set `false` to bypass role checks (default: `true`) |
| `SMTP_HOST` | No | SMTP server hostname — emails are logged when unset. Gmail: `smtp.gmail.com`, SendGrid: `smtp.sendgrid.net` |
| `SMTP_PORT` | No | SMTP port (default: 587) |
| `SMTP_USER` | No | SMTP username (Gmail: your email, SendGrid: `apikey`) |
| `SMTP_PASSWORD` | No | SMTP password (Gmail: [app password](https://myaccount.google.com/apppasswords), requires 2FA) |
| `SMTP_USE_TLS` | No | Use STARTTLS (default: `true`) |
| `MAIL_FROM` | No | Sender address (default: `noreply@scrolldownsports.com`). Gmail requires this to match `SMTP_USER` |
| `FRONTEND_URL` | No | Base URL for email links (default: `http://localhost:3000`) |
| `OPENAI_API_KEY` | No | OpenAI key for AI enrichment (game flow narratives) |
| `OPENAI_MODEL_CLASSIFICATION` | No | OpenAI model for play classification (default: `gpt-4o-mini`) |
| `OPENAI_MODEL_SUMMARY` | No | OpenAI model for narrative rendering (default: `gpt-4o`) |
| `ODDS_API_KEY` | No | The Odds API key |
| `CBB_STATS_API_KEY` | No | CBB Stats API key (NCAAB boxscore ingestion) |
| `X_AUTH_TOKEN` | No | X/Twitter auth cookie |
| `X_CT0` | No | X/Twitter CSRF cookie |
| `X_BEARER_TOKEN` | No | X/Twitter bearer token (alternative to cookie auth) |
| `NEXT_PUBLIC_SPORTS_API_URL` | Yes | API URL for frontend |
| `SPORTS_API_INTERNAL_URL` | No | Internal API URL for server-side fetches in Docker |
| `ALLOWED_CORS_ORIGINS` | Prod | Allowed CORS origins |
| `CONFIRM_DESTRUCTIVE` | No | Required for restore/reset scripts |

## Health Checks

All services have health checks configured:

```bash
# Check all service health
docker compose ps

# Check specific service
docker inspect --format='{{.State.Health.Status}}' sports-api
```

The API container health check calls `GET /healthz`, which performs a lightweight database connectivity check and returns `503` when the database is unavailable. Use the same endpoint for deploy verification.

---

## Local Services (Without Docker)

For development without Docker, run each service manually.

### 1. Database Setup

```bash
cd api && alembic upgrade head
```

### 2. API

```bash
cd api
pip install -r requirements.txt

export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/sports"
export REDIS_URL="redis://localhost:6379/2"
export ENVIRONMENT="development"

uvicorn main:app --reload --port 8000
```

### 3. Scraper (Celery Worker)

```bash
cd scraper
uv sync

export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/sports"
export REDIS_URL="redis://localhost:6379/2"

celery -A sports_scraper.celery_app.app worker --loglevel=info --queues=sports-scraper
```

### 4. Web Admin

```bash
cd web
pnpm install

export NEXT_PUBLIC_SPORTS_API_URL=http://localhost:8000
pnpm dev
```

---

## Development Workflow

```bash
# Make code changes...

# Restart affected service
docker compose restart api        # For API changes
docker compose restart web        # For web changes
docker compose restart scraper    # For scraper changes

# Run tests
docker compose exec api pytest tests/ -v
```

---

## Troubleshooting

### Services won't start

```bash
docker system df            # Check Docker resources
docker compose down -v      # Clean up and rebuild
docker compose up -d --build
```

### Database connection errors

```bash
docker compose ps postgres
docker compose logs postgres
```

### API won't start

```bash
docker logs sports-api
# Common issues:
# - Database not ready: wait for postgres healthcheck
# - Migration error: check Alembic version mismatch
# - Import error: rebuild the container
```

### Port already in use

```bash
lsof -i :8000  # or :3000, :5432, etc.
```

### Scraper returns empty results

For social scraping:
1. Check X cookies are valid (they expire)
2. Verify `X_AUTH_TOKEN` and `X_CT0` in `.env`
3. Rebuild scraper: `docker compose up -d --build scraper`

### Restoring a DB backup

The `infra/scripts/restore.sh` script is destructive and requires `CONFIRM_DESTRUCTIVE=true`.

```bash
CONFIRM_DESTRUCTIVE=true docker exec sports-postgres /scripts/restore.sh /backups/sports_YYYYMMDD.sql.gz
```

For production troubleshooting, see [Operator Runbook](runbook.md).

---

## See Also

- [Architecture](../architecture.md) - System architecture and data flow
- [Deployment](deployment.md) - Production deployment
- [Operator Runbook](runbook.md) - Production operations
