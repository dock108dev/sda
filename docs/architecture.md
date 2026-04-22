# Architecture Overview

## System Purpose

Sports Data Admin is the **centralized sports data hub for all Dock108 apps**.

**Primary Functions:**
- Automated ingestion from multiple sports data sources
- Normalization and storage in unified PostgreSQL database
- REST API serving data to all Dock108 sports products
- Timeline generation combining PBP and social events
- Admin UI for data management and monitoring

**Scope:** Multi-sport (NBA, NHL, NCAAB, MLB, NFL), multi-consumer (all Dock108 apps)

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

- **Sports:** NBA, NHL, NCAAB, MLB, NFL
- **Sources:** NBA CDN API (cdn.nba.com — boxscores + PBP, current season), Basketball Reference (NBA historical), NHL API (api-web.nhle.com — boxscores + PBP), CBB API (collegebasketballdata.com — NCAAB historical + boxscores + PBP), NCAA API (ncaa-api.henrygd.me — NCAAB live only), MLB Stats API (boxscores + PBP + Statcast), ESPN API (NFL boxscores + PBP), nflverse (NFL advanced stats), MoneyPuck (NHL advanced stats), DataGolf API (golf), The Odds API (all leagues), X/Twitter
- **Data Types:** Play-by-play, box scores, odds, social media
- **Scheduling:** Celery task queue with Redis
- **Output:** Normalized data to PostgreSQL

### 2. REST API (`api/`)
**Purpose:** Serve data to all Dock108 apps

- **Framework:** FastAPI
- **Database:** PostgreSQL (async SQLAlchemy)
- **Endpoints:** Games, plays, box scores, odds, social, teams, FairBet (odds + parlay + live)
- **Realtime:** WebSocket and SSE feeds for live game updates (scores, PBP, odds changes)
- **Authentication:** JWT-based auth for downstream apps (`app/dependencies/roles.py`), password hashing (`app/security.py`), signup/login/password-reset/magic-link endpoints (`app/routers/auth.py`), async email delivery (`app/services/email.py`)
- **Roles:** Three-tier access — guest (no token), user (authenticated), admin (developer). Controlled by `AUTH_ENABLED` flag.
- **Admin Endpoints:** Scraper management, data browser, user management (`app/routers/admin/users.py`)
- **Server-Side Services:** Status flags (`game_status.py`), date sections (`date_section.py`), FairBet display helpers (`fairbet_display.py`), odds table builder (`odds_table.py`), stat normalization (`stat_normalization.py`), stat annotations (`stat_annotations.py`), play timeline enrichment (`play_tiers.py`), period labels (`period_labels.py`), derived metrics (`derived_metrics.py`)

### 3. Analytics Engine (`api/app/analytics/`)
**Purpose:** Predictive modeling, simulation, and matchup analysis

- **Simulation:** Multi-sport Monte Carlo game simulation (MLB, NBA, NHL, NCAAB). Each sport has a dedicated simulator: MLB (plate-appearance level), NBA/NCAAB (possession-based), NHL (shot-based with shootout). Supports team-level and lineup-aware modes (MLB) with per-batter probability distributions.
- **Models:** ML models per sport — MLB (plate appearance, pitch, batted ball, run expectancy), NBA/NCAAB (possession, game), NHL (shot, game). Rule-based defaults when no trained model is loaded.
- **Features:** Feature extraction pipeline with DB-backed configurable loadouts (MLB, NBA, NHL, NCAAB feature builders registered in `FeatureBuilder`)
- **Inference:** Model registry, activation controls, inference caching, auto-reload on model changes
- **Ensemble:** Weighted probability combination from multiple providers
- **Training:** Async Celery-based training pipeline — dataset building, label extraction, model evaluation, joblib artifact generation
- **Experiments:** Parameter sweep training with combinatorial grid of algorithms, rolling windows, test splits, and feature loadouts
- **Game Theory:** Kelly Criterion bet sizing, Nash Equilibrium strategy optimization, portfolio optimization, minimax game tree solver
- **API:** `/api/analytics/*` endpoints for team profiles, simulation, model management, feature loadout CRUD, training jobs, experiments, ensemble config, game theory

See [Analytics](analytics.md) for details.

### 4. Admin UI (`web/`)
**Purpose:** Data management and monitoring

- **Framework:** React + TypeScript + Next.js
- **Features:**
  - Game browser with structured status indicators (present/missing/stale/not applicable)
  - Control Panel for on-demand Celery task dispatch (ingestion, odds, social, flows, timelines, utility)
  - Job run monitoring via RunsDrawer (IDE-style bottom panel, available on all admin pages)
  - Cross-book odds comparison: pre-game (`/admin/fairbet/odds`) and dedicated live odds page (`/admin/fairbet/live`) with auto-refresh, multi-game view, and game scoreboard strips
  - Analytics section (5 pages): Simulator (multi-sport Monte Carlo with sport selector — MLB/NBA/NHL/NCAAB), Models (registry, loadouts, training, performance), Batch Sims (multi-sport), Experiments (parameter sweeps, multi-sport), Profiles (team scouting, multi-sport)
  - Container log viewer
  - Game detail with boxscores, player stats, odds, social, PBP, flow, and pipeline runs

### 5. Club Provisioning Domain (`api/app/routers/` — clubs, commerce, billing, onboarding, webhooks)
**Purpose:** Multi-tenant self-serve club provisioning for golf pool operators

- **Onboarding:** Public "claim your club" form (`POST /api/onboarding/club-claims`) kicks off a two-phase flow: prospect submits interest → operator initiates Stripe checkout → webhook confirms payment → claim token exchanged for account
- **Commerce:** Stripe checkout session creation (`POST /api/v1/commerce/checkout`); three plans — Starter ($29/mo), Pro ($99/mo), Enterprise ($299/mo)
- **Webhooks:** Idempotent Stripe webhook handler (`POST /api/webhooks/stripe`) using `processed_stripe_events` as a dedup table (`ON CONFLICT DO NOTHING`)
- **Clubs:** Public club lookup (`GET /api/v1/clubs/{slug}`) returns club info and active pools, used by public entry pages
- **Billing:** Stripe Customer Portal self-service (`POST /api/v1/billing/portal`) for club owners to manage subscriptions
- **Club Memberships:** Invite-based RBAC (`api/app/routers/club_memberships.py`) — owner/admin roles, `club_memberships` table
- **Club Branding:** `PUT /api/v1/clubs/{id}/branding` — gated by plan; stores `branding_json` JSONB in the clubs table
- **Entitlements:** `EntitlementService` (`api/app/services/entitlement.py`) centralizes all plan limits; raises `EntitlementError` (→ 403), `SeatLimitError` (→ 402), `SubscriptionPastDueError` (→ 402)
- **Pool Lifecycle:** `TransitionError` (→ 409) raised when a pool state machine guard fails

### 6. Database (PostgreSQL)
**Purpose:** Single source of truth

- **Schema:** Normalized across sports
- **Tables:** games, plays, box scores, odds, social posts, teams, clubs, memberships, Stripe commerce tables
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

See [Gameflow Contract](gameflow/contract.md) for the authoritative specification.

See [Gameflow Pipeline](gameflow/pipeline.md) for implementation details.

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

See [Timeline Assembly](gameflow/timeline-assembly.md) for the assembly recipe.
See [Timeline Validation](gameflow/timeline-validation.md) for validation rules.

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
- `mlb_pitcher_game_stats` - Per-game pitching stats (IP, K, BB, ERA, etc.)
- `mlb_player_fielding_stats` - Per-game fielding stats (errors, assists, putouts, position) from boxscore data
- `team_social_posts` - Social media content (mapped to games via `mapping_status`)
- `users` - User accounts for downstream app authentication (email, password_hash, role, is_active)

### Analytics & ML Tables
- `analytics_feature_configs` - Feature loadouts (named feature sets with enabled/weight per sport/model_type)
- `analytics_training_jobs` - ML training job tracking (status, metrics, artifact path)
- `analytics_backtest_jobs` - Model backtest execution and results
- `analytics_batch_sim_jobs` - Batch Monte Carlo simulation jobs
- `analytics_prediction_outcomes` - Prediction vs actual outcome tracking for calibration
- `analytics_degradation_alerts` - Model quality degradation alerts
- `analytics_experiment_suites` - A/B experiment suites (groups of strategy variants)
- `analytics_experiment_variants` - Individual variants within an experiment suite
- `analytics_replay_jobs` - Historical replay jobs for strategy comparison

### Golf Tables (DataGolf)
- `golf_players` - Player catalog with DataGolf IDs and DFS site mappings
- `golf_tournaments` - Tournament definitions (event, course, dates, purse, status)
- `golf_leaderboard` - Live/final leaderboard (position, scores, SG, probabilities)
- `golf_rounds`, `golf_player_stats`, `golf_tournament_odds`, `golf_tournament_fields`, `golf_dfs_projections`
- `golf_pools` - Country club pool definitions (RVCC, Crestmont variants)
- `golf_pool_entries`, `golf_pool_entry_picks` - Pool entries and golfer selections
- `golf_pool_entry_scores`, `golf_pool_entry_score_players` - Materialized scoring results
- `golf_pool_buckets`, `golf_pool_bucket_players`, `golf_pool_score_runs` - Bucket config and audit trail

Schema is defined in the baseline Alembic migration (`api/alembic/versions/`). Reference data (leagues, teams, social handles) is seeded from `seed_data.sql`.

---

## API Endpoints

### Authentication Endpoints
- `POST /auth/signup` - Create user account, returns JWT
- `POST /auth/login` - Authenticate, returns JWT
- `POST /auth/forgot-password` - Request password reset email
- `POST /auth/reset-password` - Reset password with emailed token
- `POST /auth/magic-link` - Request a magic-link login email
- `POST /auth/magic-link/verify` - Exchange magic-link token for JWT
- `GET /auth/me` - Current user identity and role
- `PATCH /auth/me/email` - Update own email (requires password)
- `PATCH /auth/me/password` - Change own password
- `DELETE /auth/me` - Delete own account (requires password)

### Admin User Management
- `GET /api/admin/users` - List all users
- `POST /api/admin/users` - Create user account
- `PATCH /api/admin/users/{id}/role` - Change user role
- `PATCH /api/admin/users/{id}/active` - Enable/disable user
- `PATCH /api/admin/users/{id}/email` - Change user email
- `PATCH /api/admin/users/{id}/password` - Reset user password
- `DELETE /api/admin/users/{id}` - Delete user

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
- `GET /api/analytics/team-profile` — Team rolling profile with league baselines
- `POST /api/analytics/simulate` — Full Monte Carlo simulation (team-level or lineup-aware)
- `GET /api/analytics/mlb-teams` — MLB teams with stats count (for dropdowns)
- `GET /api/analytics/mlb-roster` — Team roster for lineup selection
- `GET /api/analytics/models/*` — Model registry and activation
- `GET/POST /api/analytics/feature-config*` — Feature loadout CRUD (DB-backed)
- `GET /api/analytics/available-features` — Available features with DB coverage
- `POST /api/analytics/train` — Start async model training (Celery)
- `GET /api/analytics/training-jobs` — Training job listing and status
- `GET/POST /api/analytics/ensemble-config` — Ensemble weight configuration
- `POST /api/analytics/backtest` — Start model backtest (Celery)
- `POST /api/analytics/batch-simulate` — Batch Monte Carlo simulation
- `POST /api/analytics/experiments` — Create experiment suite (parameter sweep)
- `POST /api/analytics/replay` — Start historical replay job

### Golf Endpoints
- `GET /api/golf/tournaments` — Tournament list (filter by tour, season, status)
- `GET /api/golf/tournaments/{event_id}` — Tournament detail with field, leaderboard, rounds
- `GET /api/golf/players` — Player search
- `GET /api/golf/players/{dg_id}` — Player profile and stats
- `GET /api/golf/odds/outrights` — Outright odds by tournament/market/book
- `GET /api/golf/dfs/projections` — DFS salary and projection data
- `GET/POST /api/golf/pools` — Pool CRUD (RVCC, Crestmont variants)
- `POST /api/golf/pools/{id}/entries` — Submit pool entry
- `GET /api/golf/pools/{id}/leaderboard` — Materialized pool standings
- See [API Reference](api.md) for full endpoint reference

### FairBet Endpoints
- `GET /api/fairbet/odds` — Cross-book odds comparison with EV annotations and display fields (pre-game)
- `POST /api/fairbet/parlay/evaluate` — Parlay evaluation (combined fair probability + odds)
- `GET /api/fairbet/live/games` — Discover all games with live odds in Redis (returns `LiveGameInfo[]` with teams, date, status)
- `GET /api/fairbet/live` — Live in-game +EV odds for a single game from multi-book Redis snapshots (same EV pipeline as pre-game, nothing persisted)

### Realtime Endpoints
- `WS /v1/ws` — WebSocket feed for live game updates (scores, PBP, odds)
- `GET /v1/sse` — SSE feed (same data as WS, alternative transport)
- `GET /v1/realtime/status` — Connected clients, channel subscriptions, and poller stats

FairBet reads from the `fairbet_game_odds_work` table (populated during odds ingestion with canonical DB team names) and annotates each bet with expected value computed at query time using Pinnacle as the sharp reference. Each bet includes server-computed display fields (fair American odds, selection display name, market display name, book abbreviations, confidence labels, EV method explanations) so clients don't need to maintain their own formatting logic.

See [Odds & FairBet Pipeline](ingestion/odds-and-fairbet.md) for the full data flow.
See [API Reference](api.md) for complete endpoint reference.

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

## Configuration SSOTs

### League Configuration (`config_sports.py`)

Centralized per-league feature flags and timing config. Exists in both `api/app/config_sports.py` and `scraper/sports_scraper/config_sports.py` (identical, independent packages). Controls:

- Pipeline feature flags (boxscores, odds, social, PBP, timeline)
- Game state machine windows (pregame, postgame, estimated duration)
- Live polling behavior (PBP, boxscore, odds)
- Scheduled ingestion inclusion

To add a new league, see [Adding New Sports](adding-sports.md).

### Datetime Utilities (`utils/datetime_utils.py`)

All date/time conversions go through shared utility functions. Exists in both `api/app/utils/datetime_utils.py` and `scraper/sports_scraper/utils/datetime_utils.py` (independent packages, aligned names).

| Function | Purpose |
|----------|---------|
| `to_et_date(dt)` | UTC datetime → ET calendar date. **Use instead of `.date()` on game datetimes.** |
| `today_et()` | Current date in Eastern Time (midnight boundary) |
| `sports_today_et()` | Current sports day (4 AM ET boundary — scraper only) |
| `start_of_et_day_utc(d)` | ET midnight → UTC. Use as `>=` bound in queries |
| `end_of_et_day_utc(d)` | ET next-midnight → UTC. Use as `<` bound in queries |
| `date_to_utc_datetime(d)` | Date → UTC midnight datetime |

**Critical rule:** Never call `.date()` on a `game_date` field. Use `to_et_date(game_date)` instead. A game at 4 AM UTC is 11 PM ET the previous day — `.date()` returns the wrong calendar date.

### Date/Time Convention

All game dates are stored as UTC timestamps with timezone (`TIMESTAMPTZ`) in PostgreSQL. The system uses Eastern Time (ET) as the canonical sports day boundary for all date matching and queries.

**Core rules:**
- **Storage:** UTC timestamps with timezone in the database (`game_date TIMESTAMPTZ`)
- **Date matching:** Always use `start_of_et_day_utc(d)` and `end_of_et_day_utc(d)` for date range queries
- **Sports day boundary:** 4 AM ET via `sports_today_et()`. Games before 4 AM ET belong to the previous calendar day (e.g., a game at 1 AM ET on Jan 2 is a "Jan 1 game")
- **External API dates:** Always convert with `to_et_date()`, never `.date()`. A UTC midnight date can be off by one calendar day in ET
- **Query pattern:** `WHERE game_date >= start_of_et_day_utc(d) AND game_date < end_of_et_day_utc(d)`

**Why ET?** All major US sports leagues (NBA, NFL, MLB, NHL, NCAAB) operate on Eastern Time schedules. ET is the natural boundary for "today's games."

### Caching

**CBB API (NCAAB):** Responses from the CBB Stats API are cached in a Docker volume (`scraper-cache`) to preserve API quota. Cache behavior:
- Only past-date responses are cached (live data always fetched fresh)
- PBP responses cached per-game after the game is final
- Team/player boxscore responses cached per date range
- Cache is keyed by endpoint + parameters
- Implementation: `scraper/sports_scraper/utils/cache.py` (`APICache`)

**OpenAI responses:** Game flow pipeline caches OpenAI API responses in the `openai_response_cache` database table to avoid redundant calls for the same game.

**HTML cache (Basketball Reference):** NBA historical scraper caches raw HTML pages locally in `./game_data/` to support polite re-scraping.

**Odds cache:** Per-league, per-date JSON files under the scraper cache directory.

### Team Name Normalization

External data sources use inconsistent team names. The system normalizes names before upserting to prevent duplicates.

**Non-NCAAB leagues (NBA, NHL, MLB, NFL):** `normalize_team_name()` maps known variants to canonical names (e.g., "PHX" -> "PHO", "LA Clippers" -> "Los Angeles Clippers") before team lookup. Implemented in `scraper/sports_scraper/normalization/__init__.py`.

**NCAAB:** `_find_team_by_name()` uses fuzzy matching (Levenshtein distance) during upsert because NCAAB has 350+ teams with names that vary across data sources (e.g., "Illinois State Redbirds" vs "Illinois St" vs "Illinois State"). Implemented in `scraper/sports_scraper/persistence/teams.py`.

### Game Population Strategy

All leagues populate game rows from league schedules *before* boxscore ingestion runs. This ensures:
- Games exist in the DB for odds matching (no orphaned odds)
- Boxscore ingestion can match by `source_game_key` instead of fuzzy name matching
- Live polling has game rows to update

Each league has a `populate_*_games_from_schedule()` function that creates game stubs from the league API's schedule endpoint. Additionally, `poll_game_calendars` runs every 15 minutes to catch postseason matchups and schedule changes.

---

## Key Principles

1. **Stability over speed** — Downstream apps depend on this
2. **Predictable schemas** — No silent changes
3. **Zero silent failures** — Log everything
4. **Traceable changes** — Every transformation explainable
5. **Single source of truth** — Normalized data across sports
