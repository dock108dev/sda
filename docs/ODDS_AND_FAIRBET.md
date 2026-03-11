# Odds & FairBet Pipeline

How odds enter the system, get matched to games, populate the FairBet work table, and are served to downstream apps with EV annotations.

**Audience:** Developers consuming `GET /api/fairbet/odds`, `GET /api/fairbet/live`, or working on the odds pipeline.

---

## Table of Contents

1. [Data Flow Overview](#data-flow-overview)
2. [Odds Ingestion](#odds-ingestion)
3. [Game Matching](#game-matching)
4. [FairBet Work Table & Selection Keys](#fairbet-work-table--selection-keys)
5. [EV Computation](#ev-computation)
6. [API Consumption Guide](#api-consumption-guide)
7. [Live +EV (In-Game Odds)](#live-ev-in-game-odds)
8. [Known Limitations](#known-limitations)

---

## Data Flow Overview

```
The Odds API (v4)
      │
      ▼
OddsAPIClient  ───────────────  Celery tasks:
  .fetch_mainlines()              sync_mainline_odds (every 60s)
  .fetch_event_props()            sync_prop_odds     (every 60s)
      │
      ▼
NormalizedOddsSnapshot
  (book, market, side, price, teams, game_date)
      │
      ▼
upsert_odds()  ─── Match snapshot to a SportsGame ───
      │              via team IDs, then name-based
      │              fallback (NCAAB: fuzzy matching)
      │
      ├─▶ sports_game_odds         (historical, per-market-state)
      │     Opening line: INSERT … ON CONFLICT DO NOTHING
      │     Closing line: INSERT … ON CONFLICT DO UPDATE
      │
      └─▶ fairbet_game_odds_work   (ephemeral, bet-centric work table)
            Selection keys built from DB team names
            One row per (game, market, selection, line, book)
                        │
                        ▼
              GET /api/fairbet/odds
                EV annotation at query time
                  ├─ evaluate_ev_eligibility()
                  ├─ compute_ev_for_market()  (Pinnacle devig)
                  └─ _try_extrapolated_ev()   (fallback)
                        │
                        ▼
              FairbetOddsResponse → Downstream apps
```

---

## Odds Ingestion

### Celery Tasks

Two tasks run on separate cadences:

| Task | Cadence | Markets | Description |
|------|---------|---------|-------------|
| `sync_mainline_odds` | Every 60s | h2h, spreads, totals | All leagues, today + tomorrow |
| `sync_prop_odds` | Every 60s | Player/team props, alternates | All leagues, pregame events |

Both tasks run continuously with no quiet window.

Configuration: `scraper/sports_scraper/celery_app.py`

### API Client

`scraper/sports_scraper/odds/client.py` — `OddsAPIClient`

- **Live endpoint**: `/sports/{sport}/odds` — today and future games
- **Historical endpoint**: `/historical/sports/{sport}/odds` — past dates
- **Props endpoint**: `/sports/{sport}/events/{event_id}/odds` — per-event props

Responses are normalized into `NormalizedOddsSnapshot` objects before persistence.

### Persistence: Two Tables

Each snapshot is persisted to two separate tables with different purposes:

**`sports_game_odds`** — Historical record (game-centric)
- Two rows per (game, book, market, side): opening line + closing line
- Opening line: `INSERT … ON CONFLICT DO NOTHING` (preserves first-seen price)
- Closing line: `INSERT … ON CONFLICT DO UPDATE` (tracks latest price)
- Unique constraint: `(game_id, book, market_type, side, is_closing_line)`

**`fairbet_game_odds_work`** — FairBet work table (bet-centric)
- One row per (game, market, selection, line, book), continuously upserted
- Only populated for non-completed games (`status NOT IN ('final', 'completed')`)
- Selection keys use **canonical DB team names**, not the Odds API names
- See [FairBet Work Table & Selection Keys](#fairbet-work-table--selection-keys)

Code: `scraper/sports_scraper/persistence/odds.py`, `scraper/sports_scraper/odds/fairbet.py`

---

## Game Matching

When an odds snapshot arrives, it must be matched to a `SportsGame` row. The matching strategy uses a priority cascade:

### 1. Cache Lookup

In-memory LRU cache (512 entries) keyed by `(league_code, game_day, min(home_team_id, away_team_id), max(home_team_id, away_team_id))`. Avoids repeated DB queries for the same game.

### 2. Exact Match by Team IDs

Query `sports_games` for exact team ID match (home/away) within the game day window. Also tries swapped teams (Odds API sometimes reverses home/away).

### 3. Name-Based Matching

When team IDs don't match (common for new games or NCAAB), falls back to name matching.

**Non-NCAAB (NBA, NHL):** Exact case-insensitive name match against both the canonical name and the raw API name. Supports swapped teams.

**NCAAB:** Multi-strategy fuzzy matching, because NCAAB team names vary wildly across data sources (e.g., "Illinois State Redbirds" vs "Illinois St" vs "Illinois State").

NCAAB matching steps:
1. **Manual mapping table** — Hardcoded overrides for known variations (e.g., `"St. John's Red Storm" → "St. John's (NY)"`)
2. **Normalized name matching** — Remove stopwords, compare tokens
3. **Substring matching** — With 80% length-ratio guard to prevent short-string false matches
4. **Token overlap** — Requires 2+ overlapping non-stopword tokens when both names have 2+ tokens. Only falls back to 1-token threshold when one name is a single token (e.g., "Illinois" matching "Illinois State")
5. **Subset matching** — Only allowed when the subset has 2+ tokens (prevents single-token sets like `{"state"}` from matching unrelated teams)

**Why the threshold matters:** Many NCAAB teams share the word "State" — "Illinois State", "Youngstown State", "South Dakota State". Without the 2-token threshold, "Illinois State" would incorrectly match "Youngstown State" based on the single overlapping token "state".

Code: `scraper/sports_scraper/persistence/odds_matching.py`

### 4. Game Stub Creation

If no match is found and the game date is within 48 hours, a stub `SportsGame` is created with the odds event's team info and external IDs. This ensures odds are never silently dropped.

### Match Results

| Result | Meaning |
|--------|---------|
| `PERSISTED` | Game matched, odds written to both tables |
| `SKIPPED_NO_MATCH` | No game found and stub creation not applicable |
| `SKIPPED_LIVE` | Game is live — odds skipped to preserve pre-game closing lines |

---

## FairBet Work Table & Selection Keys

### Purpose

The `fairbet_game_odds_work` table is a denormalized work table optimized for **cross-book comparison**. Unlike `sports_game_odds` (which stores one row per market state per book), the FairBet table stores one row per bet definition per book, keyed by a normalized `selection_key`.

### Selection Key Format

```
{entity_type}:{entity_slug}
```

**Examples:**

| Bet Type | Side | Selection Key |
|----------|------|---------------|
| Moneyline on Lakers | Los Angeles Lakers | `team:los_angeles_lakers` |
| Spread on Celtics | Boston Celtics | `team:boston_celtics` |
| Total over | Over | `total:over` |
| Total under | Under | `total:under` |
| LeBron points over | Over | `player:lebron_james:over` |
| LeBron points under | Under | `player:lebron_james:under` |

The same `selection_key` can appear with different `market_key` values:
- `game_id=1, market_key="h2h", selection_key="team:los_angeles_lakers"` (moneyline)
- `game_id=1, market_key="spreads", selection_key="team:los_angeles_lakers"` (spread)

### Selection Keys Use DB Team Names

Selection keys are built using the **canonical team names from the database** (`sports_teams.name`), not the team names from the Odds API snapshot. This prevents wrong team names from entering the work table when a game is matched incorrectly.

For example, if the Odds API sends "Illinois State Redbirds" but the matched game's DB teams are "Youngstown State" and "Cleveland State", the selection key will use the DB names — and a validation guard will detect the mismatch and skip the upsert.

### Validation Guard

For team bets (moneyline/spread), after building the selection key with DB team names, the system checks whether the key matches either of the game's actual teams. If the Odds API's `side` (team name) doesn't match either DB team, the fairbet upsert is skipped and a warning is logged:

```
fairbet_skip_team_mismatch: game_id=123, selection_key=team:illinois_st_redbirds,
  home_team=Youngstown State, away_team=Cleveland State, snapshot_side=Illinois St Redbirds
```

This guard catches cases where fuzzy game matching produced a false positive.

Code: `scraper/sports_scraper/odds/fairbet.py` — `upsert_fairbet_odds()`

### Table Schema

```
fairbet_game_odds_work
├── game_id        (FK → sports_games)     ─┐
├── market_key     (h2h, spreads, totals)   │ Composite PK
├── selection_key  (team:lakers, total:over) │
├── line_value     (spread/total; 0.0 for ML)│
├── book           (DraftKings, Pinnacle)   ─┘
├── price          (American odds, e.g., -110)
├── observed_at    (when snapshot was captured)
├── market_category (mainline, player_prop, etc.)
├── player_name    (for player props)
└── updated_at     (auto-updated on upsert)
```

**Note:** `line_value = 0.0` is the sentinel for moneyline bets (no line).

---

## EV Computation

EV is computed **at query time** inside `GET /api/fairbet/odds`. Nothing is persisted.

### Pipeline

1. **Query** `fairbet_game_odds_work` for future, non-completed games
2. **Group** by `(game_id, market_key, abs(line_value))` into candidate buckets
3. **Pair** opposite sides within each bucket (e.g., Lakers spread vs Celtics spread)
4. **Gate** each pair through `evaluate_ev_eligibility()` (4 checks)
5. **Devig** Pinnacle's prices via Shin's method to derive true probability (see [EV Math](EV_LIFECYCLE.md) for formula)
6. **Calculate** EV% for every book: `EV% = (decimal_odds × true_prob − 1) × 100`
7. **Sanity check** fair odds against median book price
8. **Annotate** each book entry with `ev_percent`, `implied_prob`, `is_sharp`

### Eligibility Gate (4 Checks)

| Check | Failure Reason | Description |
|-------|---------------|-------------|
| Strategy exists | `no_strategy` | No config for this (league, market_category) pair |
| Sharp book present | `reference_missing` | Pinnacle not on both sides of the market |
| Freshness | `reference_stale` | Pinnacle data older than staleness limit |
| Min qualifying books | `insufficient_books` | Fewer than 3 non-excluded books on a side |

### Strategy Configuration

| League | Category | Confidence | Staleness Limit | Fair Odds Divergence |
|--------|----------|------------|----------------|---------------------|
| NBA | mainline | high | 1 hour | 150 |
| NHL | mainline | high | 1 hour | 150 |
| NCAAB | mainline | medium | 30 min | 200 |
| MLB | mainline | high | 1 hour | 150 |
| All | player_prop | low | 30 min | 250 |
| All | team_prop | medium | 30 min | 200 |
| All | alternate | low | 30 min | 300 |
| All | period | disabled | — | — |
| All | game_prop | disabled | — | — |

Config: `api/app/services/ev_config.py`

### Extrapolation Fallback

When Pinnacle doesn't have the exact line but has a nearby reference, the system extrapolates using logit-space shifting:

- Finds the closest Pinnacle reference line for the same (game, market base)
- Computes a half-point shift in logit space
- Applies a per-sport slope (e.g., NBA spreads: 0.12 logits per half-point)
- Confidence degrades: 1-2 half-points → medium, 3+ → low

### Excluded Books

4 books are excluded from display and EV computation at query time (BetOnline.ag, Bovada, Kalshi, Polymarket). They are still ingested and persisted. Exclusion list: `api/app/services/ev_config.py` → `EXCLUDED_BOOKS`.

For the detailed mathematical walkthrough (Shin's formula, conversion formulas, worked examples), see [EV Math](EV_LIFECYCLE.md).

---

## API Consumption Guide

### Endpoints

```
GET /api/fairbet/odds
POST /api/fairbet/parlay/evaluate
```

**Base path:** `/api/fairbet`

**Authentication:** `X-API-Key` header required.

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | string | — | Filter by league code (`NBA`, `NHL`, `NCAAB`, `MLB`) |
| `market_category` | string | — | Filter by category (`mainline`, `player_prop`, `team_prop`, `alternate`) |
| `exclude_categories` | string[] | — | Exclude specific categories |
| `game_id` | int | — | Filter to a single game |
| `book` | string | — | Filter to a specific sportsbook (Pinnacle always retained) |
| `player_name` | string | — | Filter by player name (partial, case-insensitive) |
| `min_ev` | float | — | Minimum EV% threshold |
| `has_fair` | bool | — | `true` = only bets with fair odds, `false` = only bets without |
| `sort_by` | string | `ev` | Sort: `ev`, `game_time`, `market` |
| `limit` | int | 100 | Results per page (1–500) |
| `offset` | int | 0 | Pagination offset |

**Scope:** Only returns pregame games (future start time, not final/completed). Excluded books are filtered automatically.

### Response

```json
{
  "bets": [
    {
      "game_id": 123,
      "league_code": "NBA",
      "home_team": "Los Angeles Lakers",
      "away_team": "Boston Celtics",
      "game_date": "2026-01-31T19:00:00Z",
      "market_key": "spreads",
      "selection_key": "team:los_angeles_lakers",
      "line_value": -3.5,
      "market_category": "mainline",
      "player_name": null,
      "description": null,
      "true_prob": 0.5432,
      "reference_price": -118,
      "opposite_reference_price": 108,
      "ev_confidence_tier": "high",
      "ev_disabled_reason": null,
      "ev_method": "pinnacle_devig",
      "has_fair": true,
      "explanation_steps": [
        {
          "step_number": 1,
          "title": "Convert odds to implied probability",
          "description": "Each side's American odds are converted to an implied win probability.",
          "detail_rows": [
            { "label": "This side", "value": "-118 → 54.1%", "is_highlight": false },
            { "label": "Other side", "value": "+108 → 48.1%", "is_highlight": false },
            { "label": "Total", "value": "102.2%", "is_highlight": false }
          ]
        },
        {
          "step_number": 2,
          "title": "Identify the vig",
          "description": "The total implied probability exceeds 100% — the excess is the bookmaker's margin (vig).",
          "detail_rows": [
            { "label": "Total implied", "value": "102.2%", "is_highlight": false },
            { "label": "Should be", "value": "100.0%", "is_highlight": false },
            { "label": "Vig (margin)", "value": "2.2%", "is_highlight": true }
          ]
        },
        {
          "step_number": 3,
          "title": "Remove the vig (Shin's method)",
          "description": "Shin's method accounts for favorite-longshot bias, allocating more vig correction to longshots than favorites.",
          "detail_rows": [
            { "label": "Shin parameter (z)", "value": "0.0215", "is_highlight": false },
            { "label": "Fair probability", "value": "54.3%", "is_highlight": true },
            { "label": "Fair odds", "value": "-119", "is_highlight": false }
          ]
        },
        {
          "step_number": 4,
          "title": "Calculate EV at best price",
          "description": "Expected value measures the average profit per dollar wagered at the best available price.",
          "detail_rows": [
            { "label": "Best price", "value": "-110 (DraftKings)", "is_highlight": false },
            { "label": "EV", "value": "+2.15%", "is_highlight": true }
          ]
        }
      ],
      "books": [
        {
          "book": "DraftKings",
          "price": -110,
          "observed_at": "2026-01-31T18:00:00Z",
          "ev_percent": 2.15,
          "implied_prob": 0.5238,
          "is_sharp": false,
          "ev_method": "pinnacle_devig",
          "ev_confidence_tier": "high"
        },
        {
          "book": "Pinnacle",
          "price": -118,
          "observed_at": "2026-01-31T18:00:00Z",
          "ev_percent": null,
          "implied_prob": 0.5414,
          "is_sharp": true,
          "ev_method": "pinnacle_devig",
          "ev_confidence_tier": "high"
        }
      ]
    }
  ],
  "total": 245,
  "books_available": ["BetMGM", "Caesars", "DraftKings", "FanDuel", "Pinnacle"],
  "market_categories_available": ["mainline", "player_prop", "team_prop"],
  "games_available": [
    {
      "game_id": 123,
      "matchup": "Boston Celtics @ Los Angeles Lakers",
      "game_date": "2026-01-31T19:00:00Z"
    }
  ],
  "ev_diagnostics": {
    "total_pairs": 120,
    "total_unpaired": 5,
    "eligible": 98,
    "no_pair": 5,
    "reference_missing": 12,
    "extrapolated": 8
  }
}
```

### Key Field Semantics

| Field | Meaning |
|-------|---------|
| `selection_key` | Book-agnostic bet identifier. Format: `{entity}:{slug}`. Built from DB team names. |
| `market_key` | Market type from the API: `h2h`, `spreads`, `totals`, or prop key (e.g., `player_points`) |
| `line_value` | Spread or total value. `0` for moneyline. |
| `true_prob` | Fair probability from Pinnacle devig. `null` if EV disabled. |
| `reference_price` | Pinnacle's price for this side (American odds). |
| `ev_percent` | Expected value % vs fair odds. Positive = +EV. `null` if EV disabled. |
| `is_sharp` | `true` for Pinnacle (the sharp reference line). |
| `has_fair` | `true` if EV was successfully computed for this bet. |
| `ev_disabled_reason` | Why EV couldn't be computed (see table below). |
| `ev_confidence_tier` | `high`, `medium`, or `low`. Set per-strategy, not dynamically. |
| `explanation_steps` | Step-by-step math walkthrough (see [Explanation Steps](#explanation-steps)). `null` if not enriched. |
| `ev_diagnostics` | Aggregate stats on EV computation for the current query. |
| `books_available` | All sportsbooks present in the current filtered result set. |
| `games_available` | Dropdown-friendly list of pregame games: `{game_id, matchup, game_date}`. |

### Display Fields (Server-Computed)

The API enriches each `BetDefinition` and `BookOdds` with display-ready fields so clients don't need to maintain formatting logic:

| Field | Level | Meaning |
|-------|-------|---------|
| `fair_american_odds` | Bet | Fair odds in American format from `true_prob` |
| `selection_display` | Bet | Human-readable label: "LAL -3.5", "Over 215.5", "LeBron James Over 25.5" |
| `market_display_name` | Bet | Human-readable market: "Spread", "Player Points", "Moneyline" |
| `best_book` | Bet | Book with the highest EV% |
| `best_ev_percent` | Bet | Highest EV% across all books |
| `confidence_display_label` | Bet | "Sharp", "Market", or "Thin" |
| `ev_method_display_name` | Bet | "Pinnacle Devig" or "Pinnacle Extrapolated" |
| `ev_method_explanation` | Bet | Sentence explaining the derivation method |
| `explanation_steps` | Bet | Step-by-step math walkthrough with detail rows (see below) |
| `book_abbr` | Book | Short abbreviation: "DK", "FD", "PIN", etc. |
| `price_decimal` | Book | Decimal odds equivalent |
| `ev_tier` | Book | `"strong_positive"` (≥5%), `"positive"` (≥0%), `"negative"`, `"neutral"` |

The response also includes `ev_config` with global display thresholds:
```json
{
  "ev_config": {
    "min_books_for_display": 3,
    "ev_color_thresholds": { "strong_positive": 5.0, "positive": 0.0 }
  }
}
```

### Explanation Steps

The `explanation_steps` field provides a pre-computed math walkthrough so clients can render the derivation without reimplementing devig logic. Each step has a `step_number`, `title`, `description`, and `detail_rows` (label/value pairs with an `is_highlight` flag for emphasis).

Four dispatch paths based on `ev_method` and `ev_disabled_reason`:

| Condition | Path | Steps |
|-----------|------|-------|
| `ev_disabled_reason` is set | Not available | 1 step: human-readable disabled reason |
| `ev_method = "pinnacle_devig"` | Paired devig | 3-4: implied conversion → vig → Shin's devig → EV (if best book) |
| `ev_method = "pinnacle_extrapolated"` | Extrapolated | 3-4: implied conversion → vig → logit extrapolation → EV (if best book) |
| `true_prob` is set (other method) | Fallback | 1-2: fair probability → EV (if best book) |
| All null | Not available | 1 step: generic not-available message |

**Detail row highlights:** Rows with `is_highlight: true` are the key results the client should visually emphasize (e.g., vig percentage, fair probability, EV%).

Code: `api/app/services/fairbet_display.py` — `build_explanation_steps()`

### Parlay Evaluation

`POST /api/fairbet/parlay/evaluate` accepts 2-20 legs with `trueProb` (and optional `confidence`) and returns the combined fair probability, fair American odds, and geometric mean confidence. See [API.md](API.md#post-parlayevaluate) for request/response schema.

### EV Disabled Reasons

| Reason | Meaning |
|--------|---------|
| `no_strategy` | No EV config for this (league, market_category) — e.g., `period`, `game_prop` |
| `no_pair` | No valid opposite side found for pairing |
| `entity_mismatch` | Cannot pair opposite sides (different players/entities) |
| `reference_missing` | Pinnacle not present on one or both sides |
| `reference_stale` | Pinnacle data exceeds staleness limit |
| `insufficient_books` | Fewer than 3 qualifying books on one side |
| `fair_odds_outlier` | Devigged fair odds diverge too far from book median |

### Typical Consumer Patterns

**Show all +EV bets:**
```
GET /api/fairbet/odds?min_ev=0&has_fair=true&sort_by=ev
```

**Filter to a single game:**
```
GET /api/fairbet/odds?game_id=123
```

**Mainline odds for NBA:**
```
GET /api/fairbet/odds?league=NBA&market_category=mainline
```

**Player props with EV:**
```
GET /api/fairbet/odds?market_category=player_prop&has_fair=true
```

---

## Live +EV (In-Game Odds)

Live odds use the same EV pipeline as pre-game but operate entirely on ephemeral Redis data — nothing is persisted to the database.

### Architecture

```
The Odds API (live events)
      │
      ▼
Live Orchestrator (5s tick)
  ├─ poll_live_odds_mainline (every 15s)
  └─ poll_live_odds_props    (every 45s)
      │
      ▼
Aggregated Redis Snapshots
  Key: live:odds:{league}:{game_id}:{market_key}
  Value: { books: { "DraftKings": [...], "Pinnacle": [...] }, last_updated_at: ... }
  TTL: 6h snapshots, 12h history ring buffer (300 entries)
      │
      ▼
GET /api/fairbet/live/games?league=...
  └─ discover_live_game_ids() → scan Redis keys → [(league, game_id), ...]
        │
        ▼
GET /api/fairbet/live?game_id=...
  ├─ read_all_live_snapshots_for_game() → all markets for a game
  ├─ Build bets_map from multi-book snapshots
  ├─ _annotate_pair_ev()       (Shin devig on Pinnacle)
  ├─ _try_extrapolated_ev()    (fallback)
  ├─ Enrich with display fields
  └─ Return FairbetLiveResponse
```

### How It Differs From Pre-Game

| Aspect | Pre-Game | Live |
|--------|----------|------|
| Source | `fairbet_game_odds_work` (PostgreSQL) | Redis snapshots |
| Selection keys | Canonical DB team names | Built from Odds API names via `_build_selection_key()` |
| Persistence | FairBet work table continuously upserted | Nothing persisted |
| Refresh | On each odds sync (~60s) | 15–45s polling via live orchestrator |
| Scope | All upcoming non-completed games | Per-game (`/live?game_id=`) or all live games (`/live/games` discovery) |

### Redis Snapshot Format

Each snapshot key holds all bookmakers for one (game, market):

```json
{
  "last_updated_at": 1741209600.0,
  "league": "NBA",
  "game_id": 123,
  "market_key": "spread",
  "books": {
    "DraftKings": [{"selection": "home", "line": -3.5, "price": -110}],
    "Pinnacle": [{"selection": "home", "line": -3.5, "price": -108}],
    "FanDuel": [{"selection": "home", "line": -3.5, "price": -112}]
  }
}
```

The scraper aggregates all bookmakers before writing a single snapshot per (game, market) — this is critical for cross-book EV computation.

### API: `GET /api/fairbet/live/games`

Discover all games that currently have live odds data in Redis.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | string | — | Filter by league code |

**Response:** `LiveGameInfo[]`

```json
[
  {
    "game_id": 123,
    "league_code": "NBA",
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics",
    "game_date": "2026-03-08T19:00:00Z",
    "status": "LIVE"
  }
]
```

Implementation: Scans Redis for `live:odds:*` keys via `discover_live_game_ids()`, extracts unique `(league, game_id)` pairs, enriches with game info from the DB, and **filters to only return games with live status** (`in_progress`, `live`, `halftime`). Games with `pregame`, `final`, or other non-live statuses are excluded even if they still have stale odds data in Redis.

### API: `GET /api/fairbet/live`

Returns EV-annotated live odds for a single game. Same `BetDefinition` shape as pre-game with identical EV fields, display enrichment, and explanation steps.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `game_id` | int | **required** | Game ID |
| `market_category` | string | — | Filter by category |
| `sort_by` | string | `ev` | Sort: `ev`, `market` |

**Response:** `FairbetLiveResponse` — same structure as `FairbetOddsResponse` scoped to a single game, plus `last_updated_at` and `ev_diagnostics`.

### Frontend

Live odds have a **dedicated page** at `/admin/fairbet/live` (route: `FAIRBET_LIVE`). The page:
- Discovers all games with live odds via `GET /api/fairbet/live/games`
- Fetches live odds for each game in parallel via `GET /api/fairbet/live?game_id=...`
- Displays all live games grouped by game with a scoreboard header strip (league, matchup, status, last update, bet count)
- Full filtering: League, Category, Sort, Hide Alternates
- Auto-refreshes every 15 seconds with a visual indicator
- Uses the same `BetCard` UI as pregame (cross-book pricing, fair odds, EV badges, derivation popovers, sharp book indicators)

The pregame FairBet odds page (`/admin/fairbet/odds`) is pregame-only.

Code:
- Scraper tasks: `scraper/sports_scraper/jobs/live_odds_tasks.py`
- Redis store: `scraper/sports_scraper/live_odds/redis_store.py`
- API endpoint: `api/app/routers/fairbet/live.py`
- API Redis reader: `api/app/services/live_odds_redis.py`
- Frontend page: `web/src/app/admin/fairbet/live/page.tsx`
- Frontend API client: `web/src/lib/api/fairbet/index.ts`

---

## Known Limitations

1. **Two-way markets only.** Three-way markets (e.g., soccer draw) are not supported. Markets with 1 or 3+ sides get `ev_disabled_reason = "no_pair"`.

2. **Single sharp book.** Only Pinnacle is used as the EV reference. If Pinnacle doesn't offer a line, EV cannot be computed (unless extrapolation succeeds).

3. **EV not persisted.** EV is computed per-request at query time. No historical EV tracking.

4. **CLV tracking: infrastructure only.** Closing-line snapshots are captured to the `closing_lines` table when games go LIVE, but CLV comparison (closing vs live EV) is not yet computed or exposed via the API.

5. **Static staleness thresholds.** Limits are hardcoded per strategy, not adjusted dynamically based on time-to-game.

6. **NCAAB matching is fuzzy.** Despite the tightened token overlap thresholds, edge cases may still exist for teams with very similar names. The validation guard in `upsert_fairbet_odds` catches cases where the matched game's teams don't match the snapshot's side.

7. **Player props have low confidence.** Pinnacle's prop vig (5-8%) makes devigged probabilities less reliable. Player props can never be `high` confidence tier.

8. **Book lists are manual.** `EXCLUDED_BOOKS` and `INCLUDED_BOOKS` are version-controlled constants in `ev_config.py`, not database-driven.

---

## File Reference

| Component | File |
|-----------|------|
| Odds API client | `scraper/sports_scraper/odds/client.py` |
| Odds synchronizer | `scraper/sports_scraper/odds/synchronizer.py` |
| FairBet selection keys & upsert | `scraper/sports_scraper/odds/fairbet.py` |
| Odds persistence & game matching | `scraper/sports_scraper/persistence/odds.py` |
| NCAAB name matching | `scraper/sports_scraper/persistence/odds_matching.py` |
| Celery task definitions | `scraper/sports_scraper/jobs/odds_tasks.py` |
| Celery beat schedule | `scraper/sports_scraper/celery_app.py` |
| FairBet API endpoint | `api/app/routers/fairbet/odds.py` |
| FairBet parlay endpoint | `api/app/routers/fairbet/parlay.py` |
| EV annotation logic | `api/app/routers/fairbet/ev_annotation.py` |
| EV extrapolation logic | `api/app/routers/fairbet/ev_extrapolation.py` |
| FairBet display helpers | `api/app/services/fairbet_display.py` |
| EV math functions | `api/app/services/ev.py` |
| EV strategy config | `api/app/services/ev_config.py` |
| DB models (odds tables) | `api/app/db/odds.py` |
| Closing line capture | `scraper/sports_scraper/live_odds/closing_lines.py` |
| Live odds Redis store | `scraper/sports_scraper/live_odds/redis_store.py` |
| Live odds polling tasks | `scraper/sports_scraper/jobs/live_odds_tasks.py` |
| Live orchestrator | `scraper/sports_scraper/jobs/live_orchestrator.py` |
| FairBet Live endpoint (per-game + discovery) | `api/app/routers/fairbet/live.py` |
| API Redis reader (incl. `discover_live_game_ids`) | `api/app/services/live_odds_redis.py` |
| Live odds frontend page | `web/src/app/admin/fairbet/live/page.tsx` |
| Pre-game odds frontend page | `web/src/app/admin/fairbet/odds/page.tsx` |
| Frontend API client (FairBet) | `web/src/lib/api/fairbet/index.ts` |
| Provider rate limiter | `scraper/sports_scraper/utils/provider_request.py` |

## See Also

- [EV Math](EV_LIFECYCLE.md) — Devig formulas, Shin's method, and worked examples
- [API Reference](API.md) — Full API endpoint documentation
- [Data Sources](DATA_SOURCES.md) — All data ingestion sources and timing
