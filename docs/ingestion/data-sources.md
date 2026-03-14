# Data Sources & Ingestion

This document describes where data comes from and how it's ingested.

## Overview

| Data Type | Source | Leagues | Update Frequency |
|-----------|--------|---------|------------------|
| Boxscores | NBA API (cdn.nba.com) | NBA | Post-game |
| Boxscores | CBB Stats API | NCAAB | Post-game |
| Boxscores | NHL API | NHL | Post-game |
| Boxscores | MLB Stats API (statsapi.mlb.com) | MLB | Post-game |
| Play-by-Play | NBA API / NHL API / CBB API / MLB Stats API | NBA, NHL, NCAAB, MLB | Post-game |
| Play-by-Play (Live) | League APIs | NBA, NHL, NCAAB, MLB | During game (5 min polling) |
| Odds (pre-game) | The Odds API | NBA, NHL, NCAAB, MLB | Every 60s (pre-game lines) |
| Odds (live) | The Odds API | NBA, NHL, NCAAB, MLB | Every 15-45s during live games (via live orchestrator) |
| Social | X/Twitter | NBA, NHL, NCAAB, MLB | 24-hour game window |

## Boxscores & Player Stats

### Source
- **NBA**: NBA API (`cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json`)
- **NHL**: NHL API (`api-web.nhle.com/v1/gamecenter/{game_id}/boxscore`)
- **NCAAB**: CBB Stats API (`/games/teams`, `/games/players`) with date range batching
- **MLB**: MLB Stats API (`statsapi.mlb.com/api/v1/game/{game_pk}/boxscore`) — batter and pitcher stats

### NCAAB Team Mapping
NCAAB boxscore ingestion requires `cbb_team_id` in `sports_teams.external_codes` to match games to the CBB API.

**How it's populated:**
- Team data (including `cbb_team_id`) is seeded by the baseline Alembic migration from `seed_data.sql`
- New teams are added by updating `seed_data.sql` and creating a new migration

**If games aren't getting boxscores:**
1. Check `sports_teams` has `external_codes.cbb_team_id` populated
2. If a team is missing, add it to `seed_data.sql` and create a migration
3. Re-run migrations if needed

### Data Collected
- Team stats (points, rebounds, assists, etc.)
- Player stats (minutes, points, shooting percentages, etc.)
- Final scores

### Storage
- `sports_team_boxscores` - Team-level stats (JSONB)
- `sports_player_boxscores` - Player-level stats (JSONB)
- `sports_games` - Final scores updated

### Timing
- Scraped after game status changes to `final`
- Automatic ingestion runs daily at 08:30 UTC (3:30 AM EST)
- Manual scraping available via Admin UI

## Play-by-Play

### NBA (Official NBA API)

**Source:** `cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json`

NBA uses the official NBA API for PBP ingestion. The scraper matches games using `source_game_key` and fetches PBP from the CDN.

**Parsing:**
- Each JSON action becomes a `NormalizedPlay`
- `play_index`: `period * 10000 + actionNumber` for stable ordering
- Clock parsed from ISO-8601 format (e.g., `PT11M22.00S` → `11:22`)
- `play_type`, `team_abbreviation`, `player_id`, `player_name` from action payload

**Storage:** `sports_game_plays`

**Implementation:** `scraper/sports_scraper/services/pbp_nba.py` → `ingest_pbp_via_nba_api`

### NCAAB (CBB Stats API)

**Source:** CBB Stats API (`/plays/game/{game_id}`)

NCAAB uses the CBB Stats API for play-by-play ingestion. Games are matched via `external_ids.cbb_game_id` in `sports_games`.

**Parsing:**
- Each API play becomes a `NormalizedPlay`
- `play_index`: `period * 10000 + sequence` for stable ordering
- Event types mapped via `ncaab_constants.py`
- Player and team attribution from API payload

**Storage:** `sports_game_plays`

**Implementation:** `scraper/sports_scraper/services/pbp_ncaab.py` → `ingest_pbp_via_ncaab_api`

### NHL (Official NHL API)

**Source:** `api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play`

NHL uses the official NHL API for ALL data (schedule, PBP, boxscores).

**Parsing:**
- Period and time from play data
- Event types mapped to normalized play types
- Player attribution when available

**Storage:** `sports_game_plays`

**Implementation:** `scraper/sports_scraper/live/nhl.py`

**Play Index Calculation:**
- Live feeds use `period * 10000 + actionNumber` for stable ordering
- Guarantees chronological order even with late updates

**Clock Parsing:**
- NBA: `PT11M22.00S` → `11:22`
- NHL: Clock extracted from play data

## MLB Advanced Stats (Statcast-derived)

### Source
MLB Stats API `playByPlay` endpoint (same data source as PBP, different aggregation).

### Data Collected
Team-level and player-level advanced batting stats computed from pitch-level Statcast data:

**Plate discipline:** zone swing rate, outside swing rate, zone contact rate, outside contact rate (zones 1-9 = strike zone, zones 11-14 = outside)

**Quality of contact:** average exit velocity, hard-hit rate (launch speed >= 95 mph), barrel rate (>= 98 mph + MLB barrel angle formula)

Both team-level aggregates and per-batter breakdowns are computed and stored.

### Timing
- Dispatched automatically when a game transitions to FINAL (60-second countdown)
- Also triggerable on-demand via admin Control Panel (`ingest_mlb_advanced_stats`)

### Storage
- `mlb_game_advanced_stats` — Two rows per game (home + away), with raw counts and derived percentages
- `mlb_player_advanced_stats` — One row per batter per game, with same stat columns plus player identification
- `sports_games.last_advanced_stats_at` — Timestamp of last ingestion

### Implementation
- Computation: `scraper/sports_scraper/live/mlb_statcast.py`
- Ingestion service: `scraper/sports_scraper/services/mlb_advanced_stats_ingestion.py`
- Celery task: `scraper/sports_scraper/jobs/mlb_advanced_stats_tasks.py`

## Odds

### Source
The Odds API (v4): `https://api.the-odds-api.com`

### Endpoints
- **Live**: `/sports/{sport}/odds` — Today and future games (mainlines)
- **Historical**: `/historical/sports/{sport}/odds` — Past dates
- **Event props**: `/sports/{sport}/events/{event_id}/odds` — Player/team props per event

### Markets

**Mainline:** `h2h` (moneyline), `spreads` (point spread), `totals` (over/under)

**Props (NBA/NCAAB):** `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_points_rebounds_assists`, `player_blocks`, `player_steals`, `team_totals`, `alternate_spreads`, `alternate_totals`

**Props (NHL):** `player_points`, `player_goals`, `player_assists`, `player_shots_on_goal`, `player_total_saves`, `team_totals`, `alternate_spreads`, `alternate_totals`

**Props (MLB):** `batter_hits`, `batter_total_bases`, `batter_rbis`, `batter_runs_scored`, `batter_home_runs`, `batter_stolen_bases`, `pitcher_strikeouts`, `pitcher_outs`, `pitcher_hits_allowed`, `pitcher_walks`, `pitcher_earned_runs`, `team_totals`, `alternate_spreads`, `alternate_totals`

### Sync Schedule

| Task | Cadence | Markets |
|------|---------|---------|
| `sync_mainline_odds` | Every 60s | h2h, spreads, totals |
| `sync_prop_odds` | Every 60s | Player/team props, alternates |

Configuration: `scraper/sports_scraper/celery_app.py`

### Bookmakers
- 13 included books participate in display and EV computation (DraftKings, FanDuel, BetMGM, Caesars, Pinnacle, 888sport, William Hill, Betfair Exchange, Betfair Sportsbook, Ladbrokes, Paddy Power, William Hill (UK), BetRivers)
- 4 excluded books (offshore, prediction markets) are filtered at query time (BetOnline.ag, Bovada, Kalshi, Polymarket)
- **All books are still ingested and persisted** — exclusion is query-time only
- Full lists: `api/app/services/ev_config.py` → `INCLUDED_BOOKS`, `EXCLUDED_BOOKS`

### Game Matching

Odds snapshots must be matched to a `SportsGame` row. Strategy:

1. **Cache lookup** — In-memory LRU cache (512 entries) avoids repeated queries
2. **Exact team ID match** — Home/away and swapped (Odds API sometimes reverses)
3. **Name-based match:**
   - **NBA/NHL:** Case-insensitive exact match against canonical and raw API names
   - **NCAAB:** Multi-strategy fuzzy matching with manual overrides, normalized token overlap (requires 2+ overlapping tokens for multi-token names to prevent false matches on shared words like "State"), and substring matching with length-ratio guard
4. **Game stub creation** — If no match and game within 48 hours, create a stub

Code: `scraper/sports_scraper/persistence/odds.py`, `scraper/sports_scraper/persistence/odds_matching.py`

### Storage

**`sports_game_odds`** — Game-centric historical record
- Two rows per (game, book, market, side): opening line (immutable) + closing line (updated)
- Unique constraint: `(game_id, book, market_type, side, is_closing_line)`

**`fairbet_game_odds_work`** — Bet-centric work table for cross-book comparison
- One row per (game, market, selection, line, book), continuously upserted
- Selection keys use **canonical DB team names** (not Odds API names)
- Validation guard skips team bets where the snapshot's side doesn't match the game's actual teams
- Only populated for non-completed games
- `line_value = 0.0` is sentinel for moneyline

See [Odds & FairBet Pipeline](odds-and-fairbet.md) for the full data flow including EV computation.

### Live Odds (During Games)

When games are live, the **live orchestrator** dispatches per-game odds polling at sport-appropriate cadences:

| Task | Cadence | Markets |
|------|---------|---------|
| `poll_live_odds_mainline` | Every 15s | h2h, spreads, totals (league-batched) |
| `poll_live_odds_props` | Every 45s | Player/team props (per-event) |

**Closing line snapshots** are captured to the `closing_lines` table when a game transitions to LIVE, providing a durable baseline for CLV (closing line value) tracking. Live odds are stored ephemerally in Redis as **aggregated multi-book snapshots** — one key per (game, market) containing all bookmakers — with TTL (6h snapshots, 12h history ring buffer of 300 entries per game/market). This aggregation enables the live +EV pipeline (`GET /api/fairbet/live`) to compute cross-book EV at query time using the same Shin devig / Pinnacle reference logic as pre-game odds.

The live orchestrator (`live_orchestrator_tick`) runs every 5 seconds via Celery Beat and uses Redis scheduling keys to track per-game cadences with jitter. It dispatches work only when live games exist.

**Implementation:**
- Orchestrator: `scraper/sports_scraper/jobs/live_orchestrator.py`
- Live odds tasks: `scraper/sports_scraper/jobs/live_odds_tasks.py`
- Redis store: `scraper/sports_scraper/live_odds/redis_store.py`
- Closing lines: `scraper/sports_scraper/live_odds/closing_lines.py`

### Rate Limiting & Credit Management
- Historical endpoint: 1-second pause every 5 days of iteration
- Pre-game odds polling preserves closing lines in `sports_game_odds`
- Props sync aborts gracefully if API credits drop below 500 (mainlines prioritized)
- Live odds polling uses a token bucket rate limiter with configurable QPS + burst per provider
- Provider request wrapper handles 429 responses with Retry-After parsing and backoff
- Caching: Per-league, per-date JSON files under scraper cache directory

### Implementation (Pre-game)
- Client: `scraper/sports_scraper/odds/client.py`
- Sync: `scraper/sports_scraper/odds/synchronizer.py`
- FairBet upsert: `scraper/sports_scraper/odds/fairbet.py`
- Persistence: `scraper/sports_scraper/persistence/odds.py`
- Game matching: `scraper/sports_scraper/persistence/odds_matching.py`
- Provider rate limiter: `scraper/sports_scraper/utils/provider_request.py`

## Social Media (X/Twitter)

### Source
X/Twitter via Playwright browser automation

### Architecture: Team-Centric Two-Phase Collection

Social collection uses a **team-centric** approach:

**Phase 1 (COLLECT):** Scrape all tweets for teams in a date range
- Tweets saved to `team_social_posts` with `mapping_status='unmapped'`
- Team-centric, not game-centric

**Phase 2 (MAP):** Map unmapped tweets to games
- Maps tweets to games based on team and posting time
- Updates `mapping_status='mapped'` and sets `game_id` on matched tweets in `team_social_posts`

This architecture allows collecting tweets once and mapping to multiple games if needed.

### Schedule

Social collection uses four complementary mechanisms:
- **Live collection** (`collect_game_social`): Runs every 30 minutes on the `social-scraper` queue. Targets games with odds but missing or stale (>2h) social data from today and yesterday. Iterates game-by-game with team dedup and configurable inter-game cooldown. Protected by a Redis lock (30 min timeout) to prevent overlap.
- **Tweet mapping** (`map_social_to_games`): Runs every 30 minutes (staggered at :15/:45) to map unmapped tweets in `team_social_posts` to games based on team and posting time.
- **Final-whistle scrape** (`run_final_whistle_social`): Triggered automatically when games transition to FINAL status
- **Daily sweep catch-up**: Runs at **4:00 AM EST** as part of the daily sweep for any missed games. Bulk social tasks (`collect_team_social`, `collect_social_for_league`) are routed to the `social-bulk` queue so they don't starve live collection.

Cooldown and batch sizes are configurable via `SocialConfig` in `scraper/sports_scraper/config.py`. See `scraper/sports_scraper/celery_app.py` for schedule configuration.

### Collection Window
- **Start**: 5:00 AM ET on game day
- **End**: 8:00 AM ET next day

### Accounts
- Official team accounts only (no players, no media)
- Registry: `team_social_accounts` table
- Fallback: `sports_teams.x_handle` column

### Search Strategy
X advanced search: `from:<handle> since:<date> until:<date>`

### Authentication
Requires X session cookies:
- `X_AUTH_TOKEN` - Auth token from logged-in session
- `X_CT0` - CSRF token

**Getting cookies (Safari):**
1. Log into x.com in Safari
2. Develop → Show Web Inspector → Storage → Cookies
3. Copy values for `auth_token` and `ct0`
4. Add to `infra/.env`

**Getting cookies (Chrome/Edge):**
1. Log into x.com
2. DevTools → Application → Cookies → x.com
3. Copy `auth_token` and `ct0` values

Cookies expire periodically. If scraping returns empty results, log into x.com again, copy fresh values, update `.env`, and restart the scraper container.

### Filtering
- **Retweets**: Excluded via `data-testid="socialContext"` check
- **Spoilers**: Posts with scores/results flagged with `reveal_risk` + `reveal_reason`
- **Replies**: May be included if returned by search (not explicitly filtered)

### Spoiler Detection
Conservative patterns in `api/app/utils/reveal_utils.py`:
- Score patterns: `110-105`, `W 110-105`
- Result words: "final", "recap", "highlights"
- Safe patterns whitelisted: "game day", "let's go", etc.

### Deduplication
- Primary: `external_post_id` + `platform`
- Fallback: `post_url`
- Existing posts updated in place (timestamps, text, media, reveal flags)

### Rate Limiting

Multiple layers of rate limiting prevent X from detecting and blocking the scraper:

| Layer | Delay | Purpose |
|-------|-------|---------|
| Per scroll | Random 5–10s | Mimics human reading speed during page scroll |
| Between team requests | Random 30–60s | Polite delay between separate `collect_posts()` calls |
| Between games | Random 30–60s | Cooldown between processing different games |
| Between games (sweep) | Fixed 180s | Extended cooldown for the daily sweep's Social Scrape #2 |
| In-memory limiter | 300 requests / 15 min | Sliding window platform rate limit |
| Circuit breaker | 300s backoff | After 2 consecutive rate-limit errors, abort batch |
| Playwright retry | 120s backoff | On login wall or "Something went wrong", retry up to 2 times |

DB-backed cache: `social_account_polls` prevents repeated polling of the same account within the poll interval.

Configuration: `SocialConfig` in `scraper/sports_scraper/config.py`

### Social Task Queue

Social tasks dispatched from the admin UI are queued with **pre-dispatch visibility**: a `SportsJobRun` record with `status="queued"` is created *before* the Celery task is dispatched. This means:

- Queued tasks appear immediately in the RunsDrawer (no waiting for the worker to pick them up)
- Queued tasks can be canceled before the worker starts them (Celery task is revoked)
- A **FIFO queue cap of 10** prevents queue pileups — when a new task would exceed the cap, the oldest queued task is evicted (canceled with `error_summary="Evicted: social queue exceeded max limit"`)

The pre-generated Celery task ID is stored in the DB record so that cancellation can revoke the correct Redis-queued task. When the worker picks up the task, the record transitions from `"queued"` → `"running"`.

Implementation: `queue_job_run()`, `activate_queued_job_run()`, `enforce_social_queue_limit()` in `scraper/sports_scraper/services/job_runs.py`

### Storage
- `team_social_posts` table - Collected tweets, mapped to games via `mapping_status='mapped'` and `game_id`
- Fields: `post_url`, `posted_at`, `tweet_text`, `has_video`, `video_url`, `image_url`, `media_type`, `reveal_risk`, `reveal_reason`, `mapping_status`, `game_id`, `game_phase`, `likes_count`, `retweets_count`, `replies_count`

### Implementation
- Team Collector: `scraper/sports_scraper/social/team_collector.py`
- Tweet Mapper: `scraper/sports_scraper/social/tweet_mapper.py`
- Playwright: `scraper/sports_scraper/social/playwright_collector.py`
- Registry: `scraper/sports_scraper/social/registry.py`
- Reveal utils: `api/app/utils/reveal_utils.py` (shared with API)

## Scraper Execution

### Automatic (Scheduled)
- **Scheduler**: Celery Beat
- All tasks run in all environments (local mirrors production)

**Polling (every 60 seconds, staggered 15s apart via countdown):**
- **Game State Updates**: Every 60s — disabled 3–11 AM EST (08–16 UTC)
- **Live PBP + Boxscore Polling**: Every 60s — disabled 3–11 AM EST (08–16 UTC)
- **Mainline Odds Sync**: Every 60s (`sync_mainline_odds`: spreads, totals, moneyline)
- **Prop Odds Sync**: Every 60s (`sync_prop_odds`: player/team props)
- **Game Social Collection**: Every 30 minutes (`collect_game_social`)

**Live orchestrator (every 5 seconds):**
- **Live Orchestrator Tick**: Discovers live/pregame games and dynamically dispatches per-game polling tasks at sport-appropriate cadences (PBP, stats, live odds). Only dispatches work when live games exist.

**Daily (timed):**
- **Ingestion**: 08:30 UTC (3:30 AM ET) — boxscores, PBP
- **Daily Sweep**: 09:00 UTC (4:00 AM ET) — truth repair, social scrape #2, backfill embedded tweets (7-day lookback)
- **Flow Generation**: Staggered by league (30 min apart):
  - 09:30 UTC (4:30 AM ET) — NBA flow generation
  - 10:00 UTC (5:00 AM ET) — NHL flow generation
  - 10:30 UTC (5:30 AM ET) — NCAAB flow generation (capped at 10 games)
  - 11:00 UTC (6:00 AM ET) — MLB flow generation

Configuration: `scraper/sports_scraper/celery_app.py`

### Manual (Admin UI)
- Dispatch any registered Celery task via the Control Panel (`POST /api/admin/tasks/trigger`)
- Tasks include ingestion, odds sync, social collection, flow generation, cache clearing, and more
- Task dispatch is routed to the appropriate Celery queue (`sports-scraper`, `social-scraper`, or `social-bulk`)
- Job run history viewable in the RunsDrawer (bottom panel on all admin pages)

### Execution Flow
```
1. Create SportsScrapRun record (status: pending)
2. Enqueue run_scrape_job task
3. Worker picks up job
4. Fetch data from sources
5. Normalize and persist to database
6. Update run status (completed/failed)
7. Log metrics (games processed, errors)
```

### Error Handling
- Transient errors: Logged, job continues
- Fatal errors: Job marked failed, error_summary recorded
- Partial success: Some games may succeed even if others fail

## Data Quality

### Team Name Normalization
- `scraper/sports_scraper/normalization/__init__.py`
- Maps external team names to canonical database names
- Exhaustive for NBA, partial for NCAAB (by design)

### Validation
- Required fields checked before persistence
- Invalid data logged but not persisted
- Duplicate detection via unique constraints

### Monitoring
- `sports_scrape_runs` table tracks top-level ingestion runs
- `sports_job_runs` table tracks phase-level tasks (odds, ingest, pbp, social, flow generation). Status values: `queued`, `running`, `success`, `error`, `canceled`, `interrupted`
- Logs include game counts, error summaries, duration

## See Also

- [Adding New Sports](../adding-sports.md) - Adding new leagues and scrapers
- [Database Integration](../database.md) - Database schema and queries
- [Operator Runbook](../ops/runbook.md) - Production operations
