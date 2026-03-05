# Local Development

## Quick Start (Docker)

The easiest way to run the full stack locally.

```bash
cd infra
cp .env.example .env   # Edit credentials as needed
docker compose --profile dev up -d --build
```

**URLs:**
- Admin UI: http://localhost:3000
- API Docs: http://localhost:8000/docs
- Health: http://localhost:8000/healthz

## What's Running

The Docker Compose setup starts:

| Service | Port | Description |
|---------|------|-------------|
| postgres | 5432 | PostgreSQL database |
| redis | 6379 | Redis for Celery queue |
| api | 8000 | FastAPI backend |
| api-worker | — | Celery worker for API tasks (pipeline, flow generation) |
| scraper | — | Celery worker for data ingestion |
| scraper-beat | — | Celery scheduler (see [DATA_SOURCES.md](DATA_SOURCES.md) for full schedule) |
| social-scraper | — | Social media scraper — live tasks only (`social-scraper` queue, concurrency=1) |
| social-bulk | — | Bulk social collection (`social-bulk` queue, concurrency=1) |
| migrate | — | One-shot Alembic migration runner |
| web | 3000 | Next.js admin UI |
| backup | — | Daily backup service |
| log-relay | — | Docker log relay sidecar |

## Verify Everything Works

```bash
# Check all services are running
docker compose ps

# Check API health
curl http://localhost:8000/healthz

# View logs
docker compose logs -f api
docker compose logs -f scraper
```

## Database Migrations

Migrations are run explicitly (not on container startup). On a fresh database, `alembic upgrade head` creates all tables and seeds reference data (leagues, teams, social handles).

```bash
# Run pending migrations (recommended)
docker compose --profile dev run --rm migrate

# Check current version
docker exec sports-api alembic current

# Run manually
docker exec sports-api alembic upgrade head

# Create a new migration
docker exec sports-api alembic revision -m "describe change"
```

## Container Commands

```bash
# View logs
docker compose --profile dev logs -f api
docker compose --profile dev logs -f scraper

# Restart a service
docker compose --profile dev restart api

# Rebuild and restart
docker compose --profile dev up -d --build api

# Stop everything
docker compose --profile dev down

# Stop and remove volumes (WARNING: deletes data)
docker compose --profile dev down -v
```

## Using an Existing Database

By default, Postgres runs inside Docker. To connect to a host Postgres instead, modify the `DATABASE_URL` in your `.env` file and adjust network settings in the compose file.

---

## Local Services (Without Docker)

For development without Docker, run each service manually.

### 1. Database Setup

```bash
# Apply schema and seed data (Alembic handles everything)
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

## Environment Variables

Key variables in `infra/.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| DATABASE_URL | Yes | PostgreSQL connection string |
| REDIS_URL | Yes | Redis for Celery queue |
| POSTGRES_DB | Yes | Database name |
| POSTGRES_USER | Yes | Database user |
| POSTGRES_PASSWORD | Yes | Database password |
| ENVIRONMENT | Yes | `development`, `staging`, or `production` |
| API_KEY | Prod/Staging | API authentication key (min 32 chars). Generate: `openssl rand -hex 32` |
| OPENAI_API_KEY | No | For AI enrichment (moment summaries) |
| ODDS_API_KEY | No | The Odds API key for live odds |
| X_AUTH_TOKEN | No | X auth cookie for social scraping |
| X_CT0 | No | X CSRF cookie for social scraping |
| NEXT_PUBLIC_SPORTS_API_URL | Yes (web) | API base URL for frontend |
| RUN_MIGRATIONS | No | Run Alembic on startup (default: false) |

---

## Development Workflow

```bash
# Make code changes...

# Restart affected service
docker compose restart api        # For API changes
docker compose restart web        # For web changes
docker compose restart scraper  # For scraper changes

# View logs
docker compose logs -f api

# Run tests
docker compose exec api pytest tests/ -v
```

---

## Troubleshooting

### Services won't start

```bash
# Check Docker resources
docker system df

# Clean up and rebuild
docker compose down -v
docker compose up -d --build
```

### Database connection errors

```bash
# Check PostgreSQL is running
docker compose ps postgres
docker compose logs postgres
```

### API won't start

```bash
# Check logs
docker logs sports-api

# Common issues:
# - Database not ready: wait for postgres healthcheck
# - Migration error: check Alembic version mismatch
# - Import error: rebuild the container
```

### Port already in use

```bash
# Find what's using the port
lsof -i :8000  # or :3000, :5432, etc.

# Stop the conflicting service or change ports
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

---

## Next Steps

1. **Explore Admin UI**: http://localhost:3000
2. **Browse API Docs**: http://localhost:8000/docs
3. **Trigger a task**: Use the Control Panel to dispatch Celery tasks on-demand
4. **View data**: Browse games, teams, and timeline artifacts

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture and data flow
- [INFRA.md](INFRA.md) - Docker configuration details
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment
