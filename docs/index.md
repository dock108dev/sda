# Documentation Index

These docs describe the current catch-up-only Sports Data Admin service. Code, compose, and tests are the source of truth when docs drift.

## Start Here

| Guide | Purpose |
| --- | --- |
| [Architecture](architecture.md) | Current service shape and data flow |
| [API](api.md) | Catch-up API contract and health endpoints |
| [Environment & config](env-and-config.md) | Runtime settings and required secrets |
| [Scheduler & jobs](scheduler-and-jobs.md) | Celery queues, beat schedule, and task hold |
| [Infrastructure](ops/infra.md) | Docker services, local setup, migrations, backups |

## Data

| Guide | Purpose |
| --- | --- |
| [Data sources](ingestion/data-sources.md) | External feeds used by the catch-up worker |
| [Database](database.md) | Tables that back games, plays, and stats |
| [DB conventions](conventions/db.md) | Naming and migration conventions |
| [Scroll Down MLB fixtures](testing/scroll-down-mlb-fixtures.md) | Historical regression fixture notes |

## Operations

| Guide | Purpose |
| --- | --- |
| [Deployment](ops/deployment.md) | Production deployment and rollback basics |
| [Runbook](ops/runbook.md) | Common operator checks |
| [Known limitations](known-limitations.md) | Intentional constraints |
