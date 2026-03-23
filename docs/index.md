# Documentation Index

## Getting Started

| Guide | Description |
|-------|-------------|
| [Infrastructure & Local Dev](ops/infra.md) | **Start here:** Docker setup, manual setup, environment variables |
| [Architecture](architecture.md) | System components, data flow, database schema, key principles |
| [API Reference](api.md) | FastAPI endpoints and usage |

## External App Integration

| Guide | Description |
|-------|-------------|
| [Game Flow Guide](gameflow/guide.md) | **Start here:** Compact timeline with blocks and mini box scores |
| [API Reference](api.md) | Full API reference for consuming game data |

## Development

| Guide | Description |
|-------|-------------|
| [Adding New Sports](adding-sports.md) | How to enable a new league |
| [Database Integration](database.md) | Querying the sports database |

## Game Flow Generation

| Guide | Description |
|-------|-------------|
| [Game Flow Contract](gameflow/contract.md) | **Authoritative:** Block-based narrative model (3-7 blocks per game) |
| [Game Flow Pipeline](gameflow/pipeline.md) | 8-stage pipeline from PBP to narratives |
| [PBP Game Flow Assumptions](gameflow/pbp-assumptions.md) | Technical assumptions about PBP data |

## Timeline System

| Guide | Description |
|-------|-------------|
| [Timeline Assembly](gameflow/timeline-assembly.md) | Assembly recipe: PBP + social + odds merged by phase |
| [Timeline Validation](gameflow/timeline-validation.md) | Validation rules (C1-C6 critical, W1-W4 warnings) |

## FairBet & EV

| Guide | Description |
|-------|-------------|
| [Odds & FairBet Pipeline](ingestion/odds-and-fairbet.md) | **Start here:** Full pipeline from ingestion to API consumption |
| [EV Math](ingestion/ev-math.md) | Devig formulas (Shin's method), conversion math, and worked examples |

## Data Ingestion

| Guide | Description |
|-------|-------------|
| [Data Sources](ingestion/data-sources.md) | **Start here:** Where data comes from — NBA, NHL, NCAAB, MLB, NFL (boxscores, PBP, odds, social, advanced stats per sport) |

## Golf

| Guide | Description |
|-------|-------------|
| [Golf Pools](golf-pools.md) | Country club pool feature — RVCC and Crestmont variants, live scoring, CSV import, admin operations |

## Analytics & ML

| Guide | Description |
|-------|-------------|
| [Analytics Engine](analytics.md) | **Start here:** Feature loadouts, model training, experiment sweeps, simulation, calibration, ensemble predictions, and model odds pipeline |
| [Analytics Integration (Downstream)](analytics-downstream.md) | Integration guide for consuming apps — simulation flows, TypeScript types, navigation structure |

## Operations

| Guide | Description |
|-------|-------------|
| [Operator Runbook](ops/runbook.md) | Production operations and monitoring |
| [Deployment](ops/deployment.md) | Server setup, deploy flow, edge routing, rollbacks |
| [Infrastructure & Local Dev](ops/infra.md) | Docker configuration, local setup, environment variables |
| [Changelog](changelog.md) | Recent changes and releases |
