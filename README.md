# Sports Data Admin

**Centralized sports data hub for all Dock108 apps.**

Automated ingestion, normalization, and serving of sports data. Provides play-by-play, box scores, odds, and social media for NBA, NHL, NCAAB, and MLB.

## Quick Start

```bash
cd infra
cp .env.example .env
docker compose --profile dev up -d --build
```

**URLs:**
- Admin UI: http://localhost:3000
- API Docs: http://localhost:8000/docs
- Health: http://localhost:8000/healthz

For manual setup, see [docs/INFRA.md](docs/INFRA.md#local-services-without-docker).

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│ External Sources│────▶│   Scraper    │────▶│  PostgreSQL │
│ (League APIs)   │     │ (Celery/uv)  │     │    Hub      │
└─────────────────┘     └──────┬───────┘     └──────┬──────┘
                               │                    │
                        ┌──────▼──────┐             │
                        │    Redis    │             │
                        │ Queue+Cache │             │
                        └─────────────┘             │
                        ┌───────────────────────────┼───────────────────────────┐
                        │                           │                           │
                        ▼                           ▼                           ▼
                 ┌─────────────┐           ┌───────────────┐           ┌─────────────┐
                 │  REST API   │           │  Game Flow    │           │  Admin UI   │
                 │  (FastAPI)  │           │  Pipeline     │           │  (Next.js)  │
                 │  + WS/SSE   │           └───────────────┘           └─────────────┘
                 └──────┬──────┘
                        │
                        ▼
                 ┌─────────────┐
                 │ Dock108 Apps│
                 └─────────────┘
```

## Tech Stack

| Component | Stack |
|-----------|-------|
| API | Python, FastAPI, PostgreSQL |
| Scraper | Python, uv, Celery, Redis |
| Admin UI | React, TypeScript, Next.js |
| Infrastructure | Docker, Caddy |

## Directory Structure

```
api/          FastAPI backend + analytics engine
scraper/      Multi-sport data scraper (Celery workers)
web/          Admin UI (Next.js)
infra/        Docker Compose, Dockerfiles, env config
docs/         Documentation
packages/     Shared JS packages
scripts/      Utility scripts
sql/          Reference SQL queries
```

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/INDEX.md](docs/INDEX.md) | Full documentation index |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture |
| [docs/INFRA.md](docs/INFRA.md) | Infrastructure & local development |
| [docs/API.md](docs/API.md) | API reference |
| [docs/ANALYTICS.md](docs/ANALYTICS.md) | Analytics & ML engine |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deployment guide |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Release changelog |

## Contributing

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system architecture and key principles.
