# Sports Data Admin

**Centralized sports data hub for all Dock108 apps.**

Automated ingestion, normalization, and serving of sports data. Provides play-by-play, box scores, odds, and social media for NBA, NHL, NCAAB, MLB, and NFL.

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

For manual setup, see [docs/ops/infra.md](docs/ops/infra.md#local-services-without-docker).

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
api/          FastAPI backend + analytics engine + ML models
scraper/      Multi-sport data scraper (Celery workers)
web/          Admin UI (Next.js)
infra/        Docker Compose, Dockerfiles, env config
docs/         Documentation
```

## Documentation

| Guide | Description |
|-------|-------------|
| [docs/index.md](docs/index.md) | Full documentation index |
| [docs/architecture.md](docs/architecture.md) | System architecture |
| [docs/ops/infra.md](docs/ops/infra.md) | Infrastructure & local development |
| [docs/api.md](docs/api.md) | API reference |
| [docs/analytics.md](docs/analytics.md) | Analytics & ML engine |
| [docs/ops/deployment.md](docs/ops/deployment.md) | Deployment guide |
| [docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md) | Production audit & remediation |
| [docs/changelog.md](docs/changelog.md) | Release changelog |

## Contributing

See [docs/architecture.md](docs/architecture.md) for system architecture and key principles.
