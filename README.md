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

For manual setup, see [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md).

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
api/          FastAPI backend
scraper/      Multi-sport data scraper
web/          Admin UI
infra/        Docker, deployment config
docs/         Documentation
packages/     Shared JS libraries (js-core, ui, ui-kit)
scripts/      Backup and deployment scripts
```

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/INDEX.md](docs/INDEX.md) | Full documentation index |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture |
| [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) | Development setup |
| [docs/API.md](docs/API.md) | API reference |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deployment guide |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Release changelog |

## Contributing

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system architecture and key principles.
