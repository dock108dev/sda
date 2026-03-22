# Advanced Stats Implementation Plan — All Sports

Mirror the MLB Statcast pipeline for NBA, NHL, NFL, and NCAAB. Each sport gets dedicated database tables, a scraper fetcher that pulls from an **external advanced stats source** (separate from our scoreboard/PBP APIs), an ingestion service, Celery task, API schemas, and frontend component.

See `data_sources.md` for full source details per sport.

---

## Reference: MLB Pattern (Already Implemented)

Every sport below replicates this exact flow:

```
External advanced stats source (NOT the scoreboard API)
  -> Scraper Fetcher (pulls + normalizes raw advanced data)
  -> Ingestion Service (upserts to sport-specific DB tables, sets last_advanced_stats_at)
  -> Celery Task (dispatched 60s after game goes final)
  -> API Endpoint (eager-loads, serializes to JSON via game detail)
  -> Frontend Component (renders tables/cards in game detail view)
```

### MLB Files (Reference)

| Layer | File |
|-------|------|
| DB Models | `api/app/db/mlb_advanced.py` |
| Migrations | `api/alembic/versions/20260303_000009_*`, `20260313_000022_*` |
| Fetcher | `scraper/sports_scraper/live/mlb_statcast.py` |
| Ingestion | `scraper/sports_scraper/services/mlb_advanced_stats_ingestion.py` |
| Celery Task | `scraper/sports_scraper/jobs/mlb_advanced_stats_tasks.py` |
| Dispatch | `scraper/sports_scraper/jobs/polling_tasks.py` (`_dispatch_final_actions`) |
| Phase | `scraper/sports_scraper/services/phases/advanced_stats_phase.py` |
| API Schema | `api/app/routers/sports/schemas/mlb_advanced.py` |
| API Endpoint | `api/app/routers/sports/game_detail.py` |
| Frontend | `web/src/app/admin/sports/games/[gameId]/MLBAdvancedStatsSection.tsx` |

### Key MLB Architecture Details

- **Statcast aggregates pitch-level data** from the PBP endpoint: exit velocity, launch angle, pitch zone → hard-hit rate, barrel rate, plate discipline splits
- **4 DB tables**: `mlb_game_advanced_stats` (team-level), `mlb_player_advanced_stats` (batter-level), `mlb_pitcher_game_stats`, `mlb_player_fielding_stats`
- **Unique constraints**: `(game_id, team_id)` for team-level, `(game_id, team_id, player_external_ref)` for player-level
- **Upserts**: PostgreSQL `INSERT...ON CONFLICT DO UPDATE` for idempotency
- **Dispatch**: `_dispatch_final_actions()` fires Celery task with `countdown=60` when game transitions to final
- **Derived rates**: Computed via `_safe_div()` helper (handles None/zero denominator)

---

## NBA Advanced Stats

### Source: stats.nba.com (via `nba_api` library)

Free, no key. 253+ endpoints. Requires browser-like headers (blocks some cloud IPs).
Library: [`swar/nba_api`](https://github.com/swar/nba_api)

### Data to Fetch (Per Game)

| Endpoint | Data |
|----------|------|
| `shotchartdetail` | Every shot: `LOC_X`, `LOC_Y`, `SHOT_DISTANCE`, `SHOT_ZONE_BASIC` (Restricted Area, Paint, Mid-Range, 3PT), `SHOT_ZONE_AREA` (Left/Center/Right), `ACTION_TYPE` (driving layup, pullup 3, etc.), `SHOT_MADE_FLAG` |
| `boxscoreadvancedv3` | Per-player: `TS_PCT`, `EFG_PCT`, `OFF_RATING`, `DEF_RATING`, `NET_RATING`, `USG_PCT`, `PACE`, `PIE` |
| `boxscoreplayertrackingv3` | Per-player: `SPD`, `DIST`, `TCHS` (touches), `PASS`, `CONT_2PT`, `CONT_3PT`, `UCONT_2PT`, `UCONT_3PT`, `PULL_UP_FGA`, `CATCH_SHOOT_FGA` |
| `boxscorehustlev2` | Per-player: `CONTESTED_SHOTS`, `CHARGES_DRAWN`, `DEFLECTIONS`, `LOOSE_BALLS_RECOVERED`, `SCREEN_ASSISTS` |

### DB Tables

**`nba_game_advanced_stats`** (team-level, 2 rows per game):
- Shooting zones: `restricted_area_fga/fgm`, `paint_fga/fgm`, `mid_range_fga/fgm`, `three_pt_fga/fgm`, `above_break_3_fga/fgm`, `corner_3_fga/fgm`
- Efficiency: `off_rating`, `def_rating`, `net_rating`, `pace`, `efg_pct`, `ts_pct`
- Paint/transition: `paint_points`, `fastbreak_points`, `second_chance_points`, `points_off_turnovers`

**`nba_player_advanced_stats`** (player-level):
- Advanced box: `ts_pct`, `efg_pct`, `usg_pct`, `off_rating`, `def_rating`, `net_rating`, `pie`
- Tracking: `speed`, `distance`, `touches`, `time_of_possession`
- Shooting context: `pull_up_fga/fgm`, `catch_shoot_fga/fgm`, `contested_2pt_fga/fgm`, `uncontested_2pt_fga/fgm`
- Hustle: `contested_shots`, `deflections`, `charges_drawn`, `loose_balls_recovered`, `screen_assists`

**`nba_player_shot_zones`** (shot chart aggregates per player per game):
- Per zone (restricted, paint, mid-range, 3PT, corner 3, above-break 3): `fga`, `fgm`, `fg_pct`

### Files to Create

| File | Notes |
|------|-------|
| `api/app/db/nba_advanced.py` | 3 models: team, player, shot zones |
| `api/alembic/versions/YYYYMMDD_add_nba_advanced_stats.py` | Tables + indexes |
| `scraper/sports_scraper/live/nba_advanced.py` | `NBAAdvancedStatsFetcher` — calls stats.nba.com endpoints |
| `scraper/sports_scraper/services/nba_advanced_stats_ingestion.py` | `ingest_advanced_stats_for_game()` |
| `scraper/sports_scraper/jobs/nba_advanced_stats_tasks.py` | Celery task |
| `api/app/routers/sports/schemas/nba_advanced.py` | Pydantic response models |
| `web/.../NBAAdvancedStatsSection.tsx` | Shot zone chart + tracking/hustle tables |

### Implementation Notes

- stats.nba.com blocks some cloud provider IPs — may need to route through proxy or fetch from a non-cloud worker
- `nba_api` Python library handles the request formatting; we just call the endpoint and parse the JSON
- Rate limit: ~1 req/sec is safe; add 1-2s jitter between calls (same pattern as other sports)
- The `shotchartdetail` endpoint returns every shot in the game — this is the NBA equivalent of pitch-level Statcast data
- `boxscoreadvancedv3` gives us pre-computed advanced metrics (TS%, eFG%, ratings) — no need to compute ourselves

---

## NHL Advanced Stats

### Source: MoneyPuck (CSV downloads)

Free, credit required. Pre-computed xGoals model on every shot (124 features per shot).
URL: `https://moneypuck.com/data.htm`
Library: [`nhldata`](https://github.com/TonyAllenPrice/nhldata) (Python)

### Data to Fetch (Per Game)

| Dataset | URL Pattern | Data |
|---------|-------------|------|
| Shot data | `https://peter-tanner.com/moneypuck/downloads/shots_{season}.csv` | Every shot: `xGoal` (expected goal probability), `shotDistance`, `shotAngle`, `shotType`, `shotRush`, `shotRebound`, `speedFromLastEvent`, `distanceFromLastEvent`, `isPlayoffGame`, `team`, `shooterPlayerId`, `goalieIdForShot` |
| Skater game stats | Per-season CSV per team | Per-player per-game: `xGoalsFor`, `xGoalsAgainst`, `corsiFor`, `corsiAgainst`, `fenwickFor`, `fenwickAgainst`, `onIce_shotAttempts`, `gameScore` |

### DB Tables

**`nhl_game_advanced_stats`** (team-level, 2 rows per game):
- Shot quality: `xgoals_for`, `xgoals_against`, `xgoals_pct`
- Possession: `corsi_for`, `corsi_against`, `corsi_pct`, `fenwick_for`, `fenwick_against`, `fenwick_pct`
- Shooting: `shooting_pct`, `save_pct`, `pdo`
- Danger zones: `high_danger_shots_for`, `high_danger_goals_for`, `high_danger_shots_against`, `high_danger_goals_against`

**`nhl_player_advanced_stats`** (skater-level):
- xGoals: `xgoals_for`, `xgoals_against`, `on_ice_xgoals_pct`
- Possession: `corsi_for`, `corsi_against`, `corsi_rel`
- Per-60: `goals_per_60`, `assists_per_60`, `points_per_60`, `shots_per_60`
- Impact: `game_score`, `war_estimate`

**`nhl_goalie_advanced_stats`** (goalie-level):
- xGoals: `xgoals_against`, `goals_saved_above_expected` (GSAx)
- Danger saves: `high_danger_save_pct`, `medium_danger_save_pct`, `low_danger_save_pct`

### Files to Create

| File | Notes |
|------|-------|
| `api/app/db/nhl_advanced.py` | 3 models: team, skater, goalie |
| `api/alembic/versions/YYYYMMDD_add_nhl_advanced_stats.py` | Tables + indexes |
| `scraper/sports_scraper/live/nhl_advanced.py` | `NHLAdvancedStatsFetcher` — downloads + parses MoneyPuck CSVs |
| `scraper/sports_scraper/services/nhl_advanced_stats_ingestion.py` | `ingest_advanced_stats_for_game()` |
| `scraper/sports_scraper/jobs/nhl_advanced_stats_tasks.py` | Celery task |
| `api/app/routers/sports/schemas/nhl_advanced.py` | Pydantic response models |
| `web/.../NHLAdvancedStatsSection.tsx` | xG chart + Corsi/Fenwick + goalie danger zone |

### Implementation Notes

- MoneyPuck publishes season-long shot CSVs — download once per day, filter by game
- Cache the season CSV locally (same `APICache` pattern); re-download daily
- 124 columns per shot — we store a subset (xGoals, distance, angle, type, danger zone, rebound, rush) and aggregate
- Goalie advanced stats are the NHL analog to pitcher advanced stats in MLB
- MoneyPuck's xG model is the gold standard — we don't need to build our own

---

## NFL Advanced Stats

### Source: nflverse (via `nflreadpy`)

Free, CC-BY 4.0. Pre-computed EPA/WPA/CPOE on every play since 1999.
Library: [`nflreadpy`](https://github.com/nflverse/nflreadpy) (Python, uses Polars)

### Data to Fetch (Per Game)

```python
import nflreadpy as nfl
pbp = nfl.load_pbp([2025])  # ~49K plays, includes:
```

| Column | Description |
|--------|-------------|
| `epa` | Expected points added for the play |
| `wpa` | Win probability added for the play |
| `cpoe` | Completion % over expected (pass plays) |
| `air_epa` | EPA from air yards component |
| `yac_epa` | EPA from yards-after-catch component |
| `air_yards` | Depth of target downfield |
| `yards_after_catch` | YAC on completions |
| `xyac_epa` | Expected YAC EPA |
| `success` | 1 if EPA > 0, else 0 |
| `qb_epa` | EPA attributed to QB |
| `rush_attempt`, `pass_attempt` | Play type flags |
| `passer_player_id`, `rusher_player_id`, `receiver_player_id` | Player attribution |
| `posteam`, `defteam` | Team IDs |

### DB Tables

**`nfl_game_advanced_stats`** (team-level, 2 rows per game):
- EPA: `total_epa`, `pass_epa`, `rush_epa`, `epa_per_play`
- WPA: `total_wpa`
- Rates: `success_rate`, `pass_success_rate`, `rush_success_rate`, `explosive_play_rate`
- Context: `avg_cpoe`, `avg_air_yards`, `avg_yac`

**`nfl_player_advanced_stats`** (player-level):
- Passer: `pass_epa`, `epa_per_dropback`, `cpoe`, `air_epa`, `yac_epa`, `wpa`
- Rusher: `rush_epa`, `epa_per_carry`, `rush_success_rate`
- Receiver: `receiving_epa`, `targets`, `air_yards`, `yac`, `target_share`

### Files to Create

| File | Notes |
|------|-------|
| `api/app/db/nfl_advanced.py` | 2 models: team, player |
| `api/alembic/versions/YYYYMMDD_add_nfl_advanced_stats.py` | Tables + indexes |
| `scraper/sports_scraper/live/nfl_advanced.py` | `NFLAdvancedStatsFetcher` — loads nflverse parquet, filters by game |
| `scraper/sports_scraper/services/nfl_advanced_stats_ingestion.py` | `ingest_advanced_stats_for_game()` |
| `scraper/sports_scraper/jobs/nfl_advanced_stats_tasks.py` | Celery task |
| `api/app/routers/sports/schemas/nfl_advanced.py` | Pydantic response models |
| `web/.../NFLAdvancedStatsSection.tsx` | EPA breakdown + success rate charts |

### Implementation Notes

- nflverse data is published as Parquet files on GitHub Releases — download weekly during season
- `nflreadpy` loads into Polars DataFrames — filter by `game_id` to get per-game data
- EPA/WPA/CPOE are **pre-computed by nflverse** — we don't calculate them, just ingest
- Data availability: updated within ~1 hour of game completion during the season
- Player attribution is already done in the data (passer, rusher, receiver IDs)
- `pip install nflreadpy` — new dependency for the scraper

---

## NCAAB Advanced Stats

### Source: Bart Torvik / T-Rank

Free, public. Tempo-free four-factor analytics for every D1 team/game.
URL: `https://barttorvik.com/`
Library: [`toRvik`](https://torvik.sportsdataverse.org/) (R — would need HTTP adaptation for Python)

### Data to Fetch (Per Game)

T-Rank game pages provide per-game four factors and tempo-free stats:

| Metric | Description |
|--------|-------------|
| `adj_oe` | Adjusted offensive efficiency (points per 100 possessions, SOS-adjusted) |
| `adj_de` | Adjusted defensive efficiency |
| `raw_oe` / `raw_de` | Unadjusted offensive/defensive efficiency |
| `pace` | Possessions per 40 minutes |
| `efg_pct` | Effective field goal % (offense and defense) |
| `tov_pct` | Turnover % (offense and defense) |
| `orb_pct` | Offensive rebound % |
| `ft_rate` | Free throw rate (FTA/FGA) |
| Shot splits | At-rim/mid-range/3PT attempts and FG% per zone |

### DB Tables

**`ncaab_game_advanced_stats`** (team-level, 2 rows per game):
- Efficiency: `adj_oe`, `adj_de`, `raw_oe`, `raw_de`, `pace`
- Four factors (offense): `off_efg_pct`, `off_tov_pct`, `off_orb_pct`, `off_ft_rate`
- Four factors (defense): `def_efg_pct`, `def_tov_pct`, `def_orb_pct`, `def_ft_rate`
- Shot distribution: `rim_fga_pct`, `rim_fg_pct`, `mid_fga_pct`, `mid_fg_pct`, `three_fga_pct`, `three_fg_pct`

**`ncaab_player_advanced_stats`** (player-level — if available from source):
- `usage_rate`, `offensive_rating`, `defensive_rating`, `bpm`, `game_score`

### Files to Create

| File | Notes |
|------|-------|
| `api/app/db/ncaab_advanced.py` | 2 models: team, player |
| `api/alembic/versions/YYYYMMDD_add_ncaab_advanced_stats.py` | Tables + indexes |
| `scraper/sports_scraper/live/ncaab_advanced.py` | `NCAABAdvancedStatsFetcher` — fetches Torvik game data |
| `scraper/sports_scraper/services/ncaab_advanced_stats_ingestion.py` | `ingest_advanced_stats_for_game()` |
| `scraper/sports_scraper/jobs/ncaab_advanced_stats_tasks.py` | Celery task |
| `api/app/routers/sports/schemas/ncaab_advanced.py` | Pydantic response models |
| `web/.../NCAABAdvancedStatsSection.tsx` | Four factors table + shot distribution |

### Implementation Notes

- Torvik doesn't have a documented JSON API — may need to scrape structured HTML or reverse-engineer XHR endpoints
- Alternative: `toRvik` R package endpoints may be callable as HTTP URLs
- Alternative: CBB Analytics (`cbbanalytics.com`) if Torvik is too fragile to scrape
- Four factors are the core value — this is what KenPom popularized but Torvik provides free
- Player-level advanced stats may be limited compared to the other sports

---

## Shared Infrastructure Changes

These files need updates to support all 4 new sports:

| File | Change |
|------|--------|
| `api/app/db/sports.py` | Add relationships per sport (e.g., `nba_advanced_stats`, `nhl_advanced_stats`) |
| `api/app/routers/sports/game_detail.py` | Eager-load + serialize per `league_code` |
| `api/app/routers/sports/schemas/games.py` | Add fields to `GameDetailResponse` |
| `api/app/routers/sports/schemas/__init__.py` | Re-export new schemas |
| `scraper/sports_scraper/jobs/polling_tasks.py` | Expand `_dispatch_final_actions()` |
| `scraper/sports_scraper/services/phases/advanced_stats_phase.py` | Add all sports to dispatch |
| `web/src/lib/api/sportsAdmin/types.ts` | Add TypeScript types |
| `web/src/app/admin/sports/games/[gameId]/GameDetailClient.tsx` | Render per-sport sections |

### Extract `_safe_div()` to shared utility

```python
# scraper/sports_scraper/utils/math.py
def safe_div(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 4)
```

---

## Implementation Order

| Phase | Sport | Complexity | Reason |
|-------|-------|-----------|--------|
| 1 | **NBA** | Medium | `nba_api` is well-documented; shot chart data is the richest after Statcast |
| 2 | **NHL** | Medium | MoneyPuck CSVs are simple to parse; xG is pre-computed |
| 3 | **NFL** | Low-Medium | nflverse data is pre-computed EPA/WPA; just download + filter |
| 4 | **NCAAB** | Higher | Torvik has no official API; may require scraping or alternative source |

---

## New Dependencies

| Package | Sport | Purpose |
|---------|-------|---------|
| `nba_api` | NBA | Python client for stats.nba.com endpoints |
| `nflreadpy` | NFL | Python port of nflreadr for nflverse data |
| `polars` | NFL | DataFrame library (nflreadpy dependency) |
| `nhldata` | NHL | MoneyPuck CSV downloader (optional — could also just use httpx + csv) |

---

## Verification Per Sport

1. **Migration**: `alembic upgrade head` — tables created
2. **Fetcher test**: Mock API response, verify parsing produces correct aggregates
3. **Integration test**: Trigger ingestion for a known final game, verify rows in DB
4. **API test**: `GET /games/{id}` — advanced stats in response
5. **Frontend**: Game detail page shows sport-specific advanced stats section
6. **Backfill**: Run advanced stats phase for a date range, verify `last_advanced_stats_at` set
7. **Season audit**: Advanced stats coverage % appears on season audit page
