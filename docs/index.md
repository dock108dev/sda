# Documentation index

## Contributing & hygiene

| Guide | Description |
|-------|-------------|
| [Files over 500 LOC](file-size-inventory.md) | Inventory for optional splits / refactors (not a blocker) |

## Getting started

| Guide | Description |
|-------|-------------|
| [README](../README.md) (repo root) | Clone, Docker quick start, repository layout |
| [Infrastructure & local dev](ops/infra.md) | Docker Compose, services, migrations, backups |
| [Environment & configuration](env-and-config.md) | Where env vars live, API/scraper settings, validation rules |
| [Architecture](architecture.md) | Components, data flow, stack overview |
| [API reference](api.md) | HTTP endpoints, auth, rate limits, response conventions |
| [Roadmap](roadmap.md) | Delivery phases and status |

## Operations

| Guide | Description |
|-------|-------------|
| [Operator runbook](ops/runbook.md) | Production operations and monitoring |
| [Deployment](ops/deployment.md) | Server setup, routing, rollbacks |
| [Scheduler & background jobs](scheduler-and-jobs.md) | Celery beat, queues, hold switch, manual vs automatic work |

## Security & limits

| Guide | Description |
|-------|-------------|
| [Security trust boundaries](security-trust-boundaries.md) | Admin origins, API key vs JWT, realtime, rate limiting |
| [Known limitations](known-limitations.md) | Intentional tradeoffs (Redis fallback, Stripe 202 path, etc.) |

## Data & ingestion

| Guide | Description |
|-------|-------------|
| [Data sources](ingestion/data-sources.md) | External APIs, leagues, ingestion behavior |
| [Odds & FairBet](ingestion/odds-and-fairbet.md) | Odds pipeline through FairBet APIs |
| [EV math](ingestion/ev-math.md) | Devig and conversion formulas |
| [Database integration](database.md) | Querying and schema orientation |
| [DB conventions](conventions/db.md) | Naming patterns used in migrations |

## Game flow & timelines

| Guide | Description |
|-------|-------------|
| [Game flow guide](gameflow/guide.md) | Timeline blocks and mini box scores |
| [Game flow contract](gameflow/contract.md) | Block-based narrative model |
| [Game flow pipeline](gameflow/pipeline.md) | Stages from PBP to narratives |
| [PBP assumptions](gameflow/pbp-assumptions.md) | Technical assumptions for PBP |
| [Timeline assembly](gameflow/timeline-assembly.md) | Merging PBP, social, odds |
| [Timeline validation](gameflow/timeline-validation.md) | Validation rules |
| [Version semantics](gameflow/version-semantics.md) | Story versioning |

## Domains

| Guide | Description |
|-------|-------------|
| [Club provisioning](clubs.md) | Onboarding, Stripe, pools |
| [Analytics engine](analytics.md) | ML, simulation, training, experiments |
| [Analytics downstream](analytics-downstream.md) | Integration notes for consuming apps (`/api/analytics`) |
| [Adding sports](adding-sports.md) | Enabling a new league |

## Audits & history

| Guide | Description |
|-------|-------------|
| [Abend-handling audit](audits/abend-handling.md) | Exception-handling and resilience review |
| [SSOT cleanup](audits/ssot-cleanup.md) | Enum / single-source-of-truth consolidation |
| [Security audit](audits/security-audit.md) | Auth, webhooks, headers, dependency surface |
| [Code cleanup report](audits/cleanup-report.md) | Observability / hardening batch notes |
| [Changelog](changelog.md) | Release-level changes |

---

Documentation is maintained against the **current** codebase. If something disagrees with code or `infra/`, treat **code + compose + CI workflows** as authoritative and file an update.
