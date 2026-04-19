# Architecture

## Overview

Monorepo with four top-level runtime areas:

```
sda/
├── api/         FastAPI app (consumer + admin HTTP, WebSocket, SSE)
├── scraper/     Celery worker tree (ingestion, odds, social, flow pipeline)
├── web/         Next.js app (admin UI, consumer-facing game views)
├── packages/    Shared TS libraries (js-core, ui, ui-kit)
└── infra/       Docker Compose, Caddyfile, entrypoints, backups
```

Two process trees share one Postgres + one Redis:
- **API tree** — user-facing. Routes, auth, realtime fanout, analytics endpoints.
- **Scraper tree** — Celery workers consuming queues: `sports-scraper`, `social-scraper`, `social-bulk`, `training`.

Ingestion and generation run as Celery tasks; API is stateless and does not block on external sources.

## Key Components

### `api/` — FastAPI

- **Routers** split by domain: games, odds, flow, social, pipeline admin, analytics, auth. Consumer game flow endpoint is live at `/api/v1/`; remaining data endpoints live under `/api/admin/sports/`. Phase 2 completes the full consumer/admin split.
- **Services** — pipeline orchestration, data-freshness computation, EV analysis, auth providers.
- **Analytics** — model registry, feature configs, training jobs, backtesting, experiment framework, Monte Carlo simulation across MLB/NBA/NHL/NCAAB. Lives in `api/app/analytics/`. Parallel workstream, not yet load-bearing for consumer experience.
- **Realtime** — in-memory pub/sub manager with WebSocket + SSE endpoints, sequence tracking, first-subscriber callbacks, DB poller (to be replaced by `LISTEN/NOTIFY` in Phase 5).
- **DB layer** — SQLAlchemy 2.0 async models, Alembic migrations with squash strategy.
- **Auth** — API key + JWT, constant-time compare, role-based access, per-endpoint rate limits.

### `scraper/` — Celery

- **Sports ingestion** — per-sport boxscore + PBP fetchers, daily sweep for stale-status repair.
- **Odds pipeline** — multi-book ingestion from The Odds API, closing-line capture on LIVE transition, FairBet EV analysis with configurable devigging, Redis 15s TTL cache, credit quota tracking.
- **Social ingestion** — Playwright-driven X scraping with session cookies, rate-limited at 300 req/15min, circuit breaker, tweet→game phase mapping.
- **Flow pipeline** — dispatches 8-stage narrative pipeline tasks to the API service layer; produces `SportsGameFlow` with blocks as the primary consumer output.
- **Advanced stats** — MoneyPuck ZIP (NHL), nflverse parquet (NFL) ingestion; batch cadence.

### `web/` — Next.js

- **App router** with server components for initial render, client components for interactive views.
- **Consumer views** — game list with filters, game detail, `CollapsedGameFlow`, `ExpandableSocialSections`.
- **Admin views** — pipeline controls, stage inspection, bulk generation, odds/FairBet dashboards.
- **Frontend guardrails** — `guardrails.ts` enforces block count (3–7), max 5 embedded tweets, word/read-time limits. Constants are verified in sync with backend `validate_blocks.py`.

### `packages/`

- **`js-core`** — shared types, API client, date/score helpers.
- **`ui`** and **`ui-kit`** — design-system primitives consumed by `web/`.

### `infra/`

- Docker Compose for local + prod (API, scraper, web, Postgres, Redis, Caddy, log-relay).
- Caddyfile for TLS + reverse proxy.
- Entrypoint scripts handle migrations on API boot.

## Data Flow

### Game ingestion
1. Celery beat (or event trigger) enqueues per-sport fetch.
2. Fetcher hits provider, normalizes to internal schema, writes `Game` + `Boxscore` + `Play` rows.
3. `Game.status` transition (e.g. LIVE→FINAL) fires ORM hook → downstream tasks (flow generation, closing-line capture).
4. Daily sweep task repairs stale statuses and gap-fills missing games.

### Odds pipeline
1. Live orchestrator dispatches per-game odds poll every 15–45 s based on game state.
2. Raw book odds written to Postgres; consensus + EV computed; latest snapshot cached in Redis with 15 s TTL.
3. On LIVE transition, pre-game closing line is captured to a separate table for historical EV.
4. Credit-quota tracker records API spend; alerts fire on budget burn projections (Phase 4).

### Narrative pipeline (8 stages)
Runs per `Game` on FINAL transition. Code lives in `api/app/services/pipeline/stages/`.
1. **`NORMALIZE_PBP`** — validate PBP completeness, refuse below threshold.
2. **`GENERATE_MOMENTS`** — segment plays into moment boundaries.
3. **`VALIDATE_MOMENTS`** — validate moment structure against completeness requirements.
4. **`ANALYZE_DRAMA`** — per-segment weights, peak segment, comeback/blowout detection.
5. **`GROUP_BLOCKS`** — deterministic grouping of moments into 3–7 narrative blocks.
6. **`RENDER_BLOCKS`** — 2-pass LLM call (per-block narrative + game-level smoothing) with 3-layer system prompt; embeds ≤5 social posts.
7. **`VALIDATE_BLOCKS`** — structural + factual + quality scoring with PUBLISH/REGENERATE/FALLBACK decision.
8. **`FINALIZE_MOMENTS`** — merge moments + blocks into `SportsGameFlow`, write atomically, emit pub/sub event.

Fallback path: deterministic template if LLM quality score <40 after 2 regens.

### Social ingestion
1. 30-minute collection cadence per team account.
2. Playwright session pulls recent tweets, rate-limited + circuit-broken.
3. Tweet-to-game mapper assigns `game_id` + `game_phase` (pregame/in-game-by-segment/postgame).
4. Spoiler detector flags posts containing scores/results pre-consumer-view.
5. Embed selector (during `RENDER_BLOCKS` pipeline stage) picks relevant posts for narrative blocks.

### Realtime fanout
1. Ingestion writes trigger `LISTEN/NOTIFY` (Phase 5; currently DB poller at 1–5 s).
2. Pub/sub manager dispatches to WebSocket + SSE subscribers.
3. Sequence numbers let clients detect gaps and request backfill.
4. First-subscriber callbacks bound polling cost: no subscribers → no poll.

## State Management

- **Game state** — `GameStatus` enum drives downstream dispatch. Canonical value is `CANCELLED`.
- **Odds dual-persistence** — Postgres (durable history) + Redis (hot read path). Closing line is a one-way latch on LIVE transition.
- **Pipeline state** — `PipelineStage` enum + per-stage output tables. Single SSOT in `api/app/services/pipeline/models.py`; `api/app/db/pipeline.py` re-exports it.
- **Celery task state** — Redis result backend; admin hold mechanism + orphan detection on worker restart.
- **Realtime connection state** — boot epoch + per-channel sequence numbers; clients reconnect and resume from last seen.

## Directory Structure

```
sda/
├── api/
│   ├── app/
│   │   ├── analytics/          ML models, simulation, training, experiments
│   │   ├── routers/            consumer + admin HTTP endpoints
│   │   ├── services/           business logic, EV analysis, freshness
│   │   │   └── pipeline/       8-stage narrative pipeline (stages, orchestration, LLM calls)
│   │   ├── realtime/           pub/sub, WS, SSE, poller
│   │   ├── db/                 SQLAlchemy models, enums, session
│   │   └── dependencies/       FastAPI dependency injection (auth, roles, session)
│   ├── alembic/                migrations
│   ├── tests/
│   └── main.py
├── scraper/
│   ├── sports_scraper/
│   │   ├── jobs/               Celery task definitions (scrape, flow, social, odds)
│   │   ├── live/               live feed clients per sport
│   │   ├── odds/               multi-book ingestion, EV, closing line
│   │   ├── persistence/        game, team, player, odds writers
│   │   ├── services/           core orchestration (scheduler, run manager, phases)
│   │   ├── social/             Playwright scraping, mapper
│   │   └── celery_app.py
│   └── tests/
├── web/
│   └── src/
│       ├── app/                Next.js routes
│       ├── components/         game flow, social sections, admin
│       ├── lib/                API client, guardrails, hooks
│       └── types/
├── packages/
│   ├── js-core/                shared types + API client
│   ├── ui/                     primitives
│   └── ui-kit/                 composed components
├── infra/                      Docker, Caddy, entrypoints
└── docs/
    └── research/               technical research docs (17)
```

## Known Architectural Pressures

- **Consumer/admin boundary** — `/api/v1/` now live for the game flow consumer endpoint. Remaining game data endpoints still live under `/api/admin/sports/`; full split is Phase 2.
- **Score convention** — consumer game flow endpoint uses `ScoreObject {home, away}`. Legacy admin endpoints still return tuple representation; full migration is Phase 2.
- **Flow generation latency** — daily batch schedule means a 10 PM FINAL may not have a flow until next morning. Phase 1 moves generation to event-driven dispatch on FINAL transition.
- **Realtime scaling ceiling** — in-memory pub/sub + DB poller is single-instance. Phase 5 lifts to Redis Streams + LISTEN/NOTIFY.
- **Social fragility** — Playwright + cookie auth is one X change away from breaking. Phase 3 adds health probes; long-term evaluates alternative sources.
- **JSONB catch-alls** — `external_ids`, `external_codes`, `raw_payloads` have no schema validation. Phase 2 adds JSONB CHECK constraints.
