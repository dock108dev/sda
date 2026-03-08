# Architecture Overview

## System Purpose

Sports Data Admin is the **centralized sports data hub for all Dock108 apps**.

**Primary Functions:**
- Automated ingestion from multiple sports data sources
- Normalization and storage in unified PostgreSQL database
- REST API serving data to all Dock108 sports products
- Timeline generation combining PBP and social events
- Admin UI for data management and monitoring

**Scope:** Multi-sport (NBA, NHL, NCAAB, MLB), multi-consumer (all Dock108 apps)

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INGESTION                                          │
│                                                                             │
│  [External Sources]  ──scrape──▶  [Scraper]  ──persist──▶  [PostgreSQL]    │
│  League APIs, Odds API           Celery/uv       │         Normalized      │
│                                                  ▼                         │
│                                              [Redis]                       │
│                                         Task queue + live odds             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SERVING                                            │
│                                                                             │
│  [PostgreSQL + Redis]  ──▶  [REST API]  ──▶  [Dock108 Apps]               │
│                              FastAPI          All products                  │
│                              + WS/SSE         Realtime feeds               │
│                                                                             │
│  [PostgreSQL]  ──▶  [Admin UI]  ──▶  [Operators]                           │
│                     Next.js          Data management                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Data Scraper (`scraper/`)
**Purpose:** Automated ingestion from external sources

- **Sports:** NBA, NHL, NCAAB, MLB
- **Sources:** NBA API (boxscores + PBP via cdn.nba.com), NHL API (boxscores + PBP), CBB Stats API (NCAAB boxscores + PBP), MLB Stats API (boxscores + PBP), The Odds API, X/Twitter
- **Data Types:** Play-by-play, box scores, odds, social media
- **Scheduling:** Celery task queue with Redis
- **Output:** Normalized data to PostgreSQL

### 2. REST API (`api/`)
**Purpose:** Serve data to all Dock108 apps

- **Framework:** FastAPI
- **Database:** PostgreSQL (async SQLAlchemy)
- **Endpoints:** Games, plays, box scores, odds, social, teams, FairBet (odds + parlay + live)
- **Realtime:** WebSocket and SSE feeds for live game updates (scores, PBP, odds changes)
- **Admin Endpoints:** Scraper management, data browser
- **Server-Side Services:** Status flags (`game_status.py`), date sections (`date_section.py`), FairBet display helpers (`fairbet_display.py`), odds table builder (`odds_table.py`), stat normalization (`stat_normalization.py`), stat annotations (`stat_annotations.py`), play timeline enrichment (`play_tiers.py`), period labels (`period_labels.py`), derived metrics (`derived_metrics.py`)

### 3. Analytics Engine (`api/app/analytics/`)
**Purpose:** Predictive modeling, simulation, and matchup analysis

- **Simulation:** Monte Carlo game simulation with pluggable probability sources (rule-based, ML, ensemble, pitch-level)
- **Models:** Sport-specific ML models (plate appearance, game outcome, pitch outcome, batted ball, run expectancy)
- **Features:** Feature extraction pipeline with DB-backed configurable loadouts per sport/model type
- **Inference:** Model registry, activation controls, inference caching, auto-reload on model changes
- **Ensemble:** Weighted probability combination from multiple providers
- **Training:** Async Celery-based training pipeline — dataset building, label extraction, model evaluation, joblib artifact generation
- **API:** `/api/analytics/*` endpoints for team/player profiles, matchup analysis, simulation, model management, feature loadout CRUD, training jobs, ensemble config, MLB advanced models

See [ANALYTICS.md](ANALYTICS.md) for details.

### 4. Admin UI (`web/`)
**Purpose:** Data management and monitoring

- **Framework:** React + TypeScript + Next.js
- **Features:**
  - Game browser with structured status indicators (present/missing/stale/not applicable)
  - Control Panel for on-demand Celery task dispatch (ingestion, odds, social, flows, timelines, utility)
  - Job run monitoring via RunsDrawer (IDE-style bottom panel, available on all admin pages)
  - Cross-book odds comparison (FairBet viewer)
  - Container log viewer
  - Game detail with boxscores, player stats, odds, social, PBP, flow, and pipeline runs

### 5. Database (PostgreSQL)
**Purpose:** Single source of truth

- **Schema:** Normalized across sports
- **Tables:** games, plays, box scores, odds, social posts, teams
- **Migrations:** Alembic (see `api/alembic/versions/`)
- **Access:** Async SQLAlchemy ORM

---

## Game Flow Generation

The game flow system converts play-by-play data into block-based narratives through an 8-stage pipeline.

### Architecture

A game flow consists of **3-7 narrative blocks**, each containing 1-5 sentences (~65 words). Blocks are designed for 60-90 second total read time.

```
NORMALIZE_PBP → GENERATE_MOMENTS → VALIDATE_MOMENTS → ANALYZE_DRAMA → GROUP_BLOCKS → RENDER_BLOCKS → VALIDATE_BLOCKS → FINALIZE_MOMENTS
```

### Pipeline Stages

| Stage | Purpose |
|-------|---------|
| NORMALIZE_PBP | Fetch and normalize PBP with phase assignments |
| GENERATE_MOMENTS | Segment plays into moment boundaries |
| VALIDATE_MOMENTS | Validate moment structure |
| ANALYZE_DRAMA | Use AI to identify dramatic peak and weight quarters |
| GROUP_BLOCKS | Group moments into 3-7 narrative blocks (drama-weighted) |
| RENDER_BLOCKS | Generate block narratives via OpenAI |
| VALIDATE_BLOCKS | Enforce guardrail invariants |
| FINALIZE_MOMENTS | Persist to database |

### Core Concept: Narrative Block

A narrative block contains:
- `block_index`: Position (0-6)
- `role`: Semantic role (SETUP, MOMENTUM_SHIFT, RESPONSE, DECISION_POINT, RESOLUTION)
- `moment_indices`: Which moments are grouped
- `narrative`: 1-5 sentences (~65 words)
- Score and time context

### Key Properties

- **Consumer-focused:** 3-7 blocks, 60-90 second read time
- **Traceability:** Blocks → Moments → Plays
- **Semantic roles:** Each block has a narrative purpose
- **Guardrails enforced:** Hard limits on block count, social post count, word count
- **Social-independent:** Game flow structure identical with/without social data

See [GAMEFLOW_CONTRACT.md](GAMEFLOW_CONTRACT.md) for the authoritative specification.

See [GAMEFLOW_PIPELINE.md](GAMEFLOW_PIPELINE.md) for implementation details.

**Code:** `api/app/services/pipeline/`

---

## Timeline System

The timeline system merges PBP events, social media posts, and odds data into a unified game timeline. Social and odds data are optional — the pipeline works with PBP alone.

### Components

- `api/app/services/timeline_generator.py` - Main orchestration (fetch, build, validate, persist)
- `api/app/services/timeline_events.py` - PBP event building and `merge_timeline_events()`
- `api/app/services/social_events.py` - Social post processing and role assignment
- `api/app/services/odds_events.py` - Odds event processing and movement detection
- `api/app/services/timeline_phases.py` - Phase boundaries and timing calculations
- `api/app/services/timeline_types.py` - Constants (`PHASE_ORDER`), data classes
- `api/app/services/timeline_validation.py` - Validation rules (6 critical, 4 warning)

See [TIMELINE_ASSEMBLY.md](TIMELINE_ASSEMBLY.md) for the assembly recipe.
See [TIMELINE_VALIDATION.md](TIMELINE_VALIDATION.md) for validation rules.

---

## Database Schema

### Core Tables
- `sports_games` - Game metadata
- `sports_game_plays` - Play-by-play events
- `sports_team_boxscores` - Team stats
- `sports_player_boxscores` - Player stats
- `sports_game_odds` - Betting lines (game-centric)
- `fairbet_game_odds_work` - Bet-centric odds for cross-book comparison
- `closing_lines` - Durable closing-line snapshots captured when games go LIVE
- `mlb_game_advanced_stats` - Statcast-derived advanced batting stats per team per game
- `mlb_player_advanced_stats` - Statcast-derived advanced batting stats per batter per game
- `team_social_posts` - Social media content (mapped to games via `mapping_status`)

### Analytics & ML Tables
- `analytics_feature_configs` - Feature loadouts (named feature sets with enabled/weight per sport/model_type)
- `analytics_training_jobs` - ML training job tracking (status, metrics, artifact path)
- `analytics_backtest_jobs` - Model backtest execution and results
- `analytics_batch_sim_jobs` - Batch Monte Carlo simulation jobs
- `analytics_prediction_outcomes` - Prediction vs actual outcome tracking for calibration
- `analytics_degradation_alerts` - Model quality degradation alerts

Schema is defined in the baseline Alembic migration (`api/alembic/versions/`). Reference data (leagues, teams, social handles) is seeded from `seed_data.sql`.

---

## API Endpoints

### Game Data Endpoints
- `GET /api/admin/sports/games` - List games with filtering
- `GET /api/admin/sports/games/{id}` - Full game detail (boxscores, odds, social, PBP, flow)
- `GET /api/admin/sports/games/{id}/flow` - AI-generated game flow
- `GET /api/admin/sports/games/{id}/timeline` - Persisted timeline artifact
- `GET /api/admin/sports/teams` - List teams
- `GET /api/admin/sports/teams/{id}` - Team detail with recent games

### Operations Endpoints
- `POST /api/admin/tasks/trigger` - Dispatch a Celery task by name (Control Panel)
- `GET /api/admin/tasks/registry` - List available tasks and their metadata
- `GET /api/admin/sports/scraper/runs` - List scraper runs
- `GET /api/admin/sports/pipeline/game/{id}` - Pipeline runs for a game
- `POST /api/admin/sports/pipeline/{id}/run-full` - Execute full pipeline
- `GET /api/admin/sports/logs` - Container log viewer

### PBP Inspection Endpoints
- `GET /api/admin/sports/pbp/game/{id}` - PBP events by period
- `GET /api/admin/sports/pbp/game/{id}/detail` - Detailed PBP with resolution stats
- `GET /api/admin/sports/pbp/game/{id}/snapshots` - PBP snapshot history

### Analytics Endpoints
- `GET /api/analytics/team` — Team analytical profile
- `GET /api/analytics/player` — Player analytical profile
- `GET /api/analytics/matchup` — Head-to-head matchup analysis
- `POST /api/analytics/simulate` — Full Monte Carlo simulation
- `POST /api/analytics/live-simulate` — Live game simulation from current state
- `GET /api/analytics/models/*` — Model registry and activation
- `GET/POST /api/analytics/feature-config*` — Feature loadout CRUD (DB-backed)
- `GET /api/analytics/available-features` — Available features with DB coverage
- `POST /api/analytics/train` — Start async model training (Celery)
- `GET /api/analytics/training-jobs` — Training job listing and status
- `GET/POST /api/analytics/ensemble-config` — Ensemble weight configuration
- `POST /api/analytics/backtest` — Start model backtest (Celery)
- `POST /api/analytics/batch-simulate` — Batch Monte Carlo simulation

### FairBet Endpoints
- `GET /api/fairbet/odds` — Cross-book odds comparison with EV annotations and display fields
- `POST /api/fairbet/parlay/evaluate` — Parlay evaluation (combined fair probability + odds)
- `GET /api/fairbet/live` — Live in-game +EV odds computed from multi-book Redis snapshots (same EV pipeline as pre-game, nothing persisted)

### Realtime Endpoints
- `WS /v1/realtime/ws` — WebSocket feed for live game updates (scores, PBP, odds)
- `GET /v1/realtime/sse` — SSE feed (same data as WS, alternative transport)
- `GET /v1/realtime/status` — Connected clients, channel subscriptions, and poller stats

FairBet reads from the `fairbet_game_odds_work` table (populated during odds ingestion with canonical DB team names) and annotates each bet with expected value computed at query time using Pinnacle as the sharp reference. Each bet includes server-computed display fields (fair American odds, selection display name, market display name, book abbreviations, confidence labels, EV method explanations) so clients don't need to maintain their own formatting logic.

See [Odds & FairBet Pipeline](ODDS_AND_FAIRBET.md) for the full data flow.
See [API.md](API.md) for complete endpoint reference.

---

## Tech Stack Details

### Backend
- **Framework:** FastAPI
- **Database:** PostgreSQL 16+
- **ORM:** SQLAlchemy (async)
- **Migrations:** Alembic
- **Task Queue:** Celery + Redis

### Frontend
- **Framework:** Next.js 16+
- **Language:** TypeScript
- **Styling:** CSS Modules
- **API Client:** Fetch API

### Scraper
- **Language:** Python 3.11+
- **Package Manager:** uv
- **HTTP:** httpx
- **Parsing:** BeautifulSoup, lxml

---

## Key Principles

1. **Stability over speed** — Downstream apps depend on this
2. **Predictable schemas** — No silent changes
3. **Zero silent failures** — Log everything
4. **Traceable changes** — Every transformation explainable
5. **Single source of truth** — Normalized data across sports

See the Key Principles section above for coding standards.
