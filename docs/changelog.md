# Changelog

All notable changes to Sports Data Admin.

## [2026-04-07] - Current

### Phantom Game Detection & Cancellation

- **Phantom game auto-cancel:** Games created from odds feeds for conditional tournament matchups (e.g., "Illinois @ Duke" when UConn won the prior round) are now automatically marked `canceled` instead of `final` when they have no scores, PBP, boxscore, or scrape data past their expected end time. Existing phantom finals are also retroactively fixed on the next game state updater cycle.
- **Games list excludes canceled/postponed:** The `GET /games` endpoint now filters out `canceled` and `postponed` games by default, preventing phantom games from appearing in consumer-facing apps.

### NHL Game Time Fix

- **NHL start times no longer stuck at noon ET:** Fixed `_has_real_time()` to recognize the noon-ET placeholder (from `_et_noon_utc()`) as a non-real time. Previously, games created with the noon-ET fallback were never updated with actual start times from the NHL schedule API because the system incorrectly treated noon ET as a real game time.

### Projected Lineups & Probable Starters

- **Roster endpoint enhanced:** `GET /api/analytics/mlb-roster` now returns optional `projected_lineup` (consensus 9-batter batting order from last 7 games) and `probable_starter` (today's announced starter from MLB Stats API). Downstream apps should use these fields as default pre-fills for simulation lineup selectors.
- **Frontend auto-fill improved:** The simulator UI now uses projected lineup and probable starter when available, falling back to top-9-by-games-played only when the new fields are absent.

## [2026-03-25]

### Multi-Sport Simulator & Analytics

- **Multi-sport game simulators:** Extended the MLB play-level simulator to all supported sports. NBA and NCAAB use possession-based models (with four-factor mechanics and offensive rebounds for NCAAB). NHL uses a shot-based model with overtime and shootout simulation. All simulators implement the `GameSimulator` protocol and are registered in `SimulationEngine`.
- **Multi-sport profile service:** `get_team_rolling_profile()` now builds rolling profiles from sport-specific advanced stats tables (NBAGameAdvancedStats, NHLGameAdvancedStats, NCAABGameAdvancedStats) instead of returning `None` for non-MLB sports. Added `profile_to_probabilities()` dispatcher for sport-generic probability conversion.
- **Sport-specific feature builders:** NBA (20 possession features), NHL (14 shot-quality features), NCAAB (22 four-factor features) registered in `FeatureBuilder` registry.
- **Sport-specific ML model stubs:** Possession/game models for NBA and NCAAB, shot/game models for NHL. Rule-based defaults until trained models are available. All registered in `ModelRegistry`.
- **Generic teams API:** `GET /api/analytics/{sport}/teams` endpoint returns teams with advanced stats counts for any supported sport. Existing `/mlb-teams` preserved as alias.
- **Sport-aware team profiles:** `GET /api/analytics/team-profile` now accepts `sport` query param and returns sport-specific baselines.
- **Frontend sport selector:** All 5 analytics pages (Simulator, Models, Batch Sims, Experiments, Profiles) now have a sport selector pill bar. MLB-specific UI (lineup mode, pitcher selection, PA probabilities) conditionally shown. Team lists reload on sport change.
- **Test coverage:** 170+ tests covering all new simulators, metrics, feature builders, model stubs, engine integration, profile service, and API routes.

## [2026-03-24]

### Ingestion Pipeline Hardening

- **Schedule-based game population:** All leagues (NBA, NHL, NCAAB, MLB, NFL) now populate game rows from league schedules *before* boxscore ingestion. Ensures games exist in the DB for odds matching and prevents orphaned boxscores. Each league's `populate_*_games_from_schedule()` runs as the first step of the boxscore phase.
- **Sequential bulk backfill:** Bulk backfill tasks now process date chunks one at a time within a single Celery task (instead of fanning out parallel subtasks). Prevents worker starvation and ensures proper job run status tracking. Monthly chunking with season awareness.
- **NBA historical fallback:** `ingest_nba_historical` auto-falls back to Basketball Reference when CDN returns empty data for historical seasons. CDN probe path used for game ID discovery before attempting full boxscore fetch.
- **CBB API caching:** NCAAB data fetchers (team boxscores, player boxscores, PBP) now cache responses for past date ranges in a Docker volume (`scraper-cache`). Only past-date responses are cached; live data is always fetched fresh. PBP cached per-game after game is final. Team/player boxscores cached per date range.
- **NCAAB fuzzy team matching:** `_find_team_by_name()` in the persistence layer uses fuzzy matching with Levenshtein distance to match CBB API team names to canonical DB team records during upsert. Prevents duplicate teams when API names vary slightly across seasons.
- **ET date standardization:** Six timezone fixes applied across the scraper. All date matching now uses `to_et_date()` / `start_of_et_day_utc()` / `end_of_et_day_utc()` instead of naive `.date()` calls. Fixes games near midnight UTC being assigned to the wrong calendar day.
- **NFL abbreviation mapping:** NFL advanced stats ingestion now maps nflverse team abbreviations (e.g., `LA` -> `LAR`) to canonical DB abbreviations before game matching. Date matching uses ET conversion.
- **Golf tournament status:** Tournament status now derived from tournament dates when DataGolf API has no explicit status field. Live prediction fields populated.
- **Game upsert `source_game_key` fallback:** Constraint violation on `source_game_key` during enrichment gracefully handled — key is only set at creation time (SSOT).
- **Held task job runs:** When the admin hold is active and a Beat-scheduled task is skipped, the corresponding `SportsJobRun` record (if any) is marked `skipped` instead of remaining stuck in `queued`.

## [2026-03-23]

### Game Theory Module

- **Kelly Criterion:** Optimal bet sizing (full/half/quarter Kelly) for single bets and batches with total exposure management. 2 endpoints.
- **Nash Equilibrium:** Two-player zero-sum game solver via fictitious play. Includes lineup optimization (batter-vs-pitcher matchup matrices) and pitch selection optimization. 3 endpoints.
- **Portfolio Optimization:** Mean-variance bankroll allocation across correlated bets with risk aversion tuning, per-bet caps, and Sharpe ratio output. 1 endpoint.
- **Minimax + Regret Matching:** Alpha-beta pruned game tree solver for sequential decisions, plus regret minimization for repeated games. 2 endpoints.
- **Implementation:** 5 new modules in `api/app/analytics/game_theory/`, 8 API endpoints under `/api/analytics/game-theory/*`, 40 unit tests.

## [2026-03-22]

### NFL Support (Full Pipeline)

- **NFL live data:** Full ESPN API integration — schedule, play-by-play, boxscores, live polling. 7 new scraper files (`nfl.py`, `nfl_pbp.py`, `nfl_boxscore.py`, `nfl_constants.py`, `nfl_models.py`, `nfl_helpers.py`). Alembic migration seeds 32 NFL teams. NFL added to scheduled ingestion, calendar polling, flow generation (6:30 AM EST), game processors, polling helpers, diagnostics, and control panel league dropdown.
- **NFL odds:** Props markets added (`player_pass_tds`, `player_rush_yds`, `player_receptions`, `player_anytime_td`, etc.). NFL already had mainline odds wired via `SPORT_KEY_MAP`.
- **NFL pipeline config:** Gameflow thresholds (21-point blowout, 7-point close game, 14-point momentum swing). NFL added to `FAIRBET_LEAGUES`.

### Advanced Stats (All 5 Sports)

- **MLB Statcast:** Already implemented (reference pattern). Pitch-level exit velocity, launch angle, barrel rate, plate discipline.
- **NBA (boxscore-derived):** TS%, eFG%, OFF/DEF/NET rating, pace, four factors, usage rate, game score — all computed from existing boxscore JSONB data. No external API calls (stats.nba.com blocks cloud IPs). Tracking/hustle stats (speed, deflections) deferred as TODO. 2 new DB tables, frontend section.
- **NHL (MoneyPuck):** Season ZIP (not CSV) with 124-feature shot data. Pre-computed xGoals, Corsi, Fenwick, PDO, danger-zone saves. Game ID matching strips 4-digit season prefix from NHL PK (e.g., `2025020105` → `20105`). 3 new DB tables (team, skater, goalie), frontend section.
- **NFL (nflverse):** Pre-computed EPA/WPA/CPOE via `nflreadpy`. Team and per-role player stats. 2 new DB tables, frontend section. New dependency: `nflreadpy`.
- **NCAAB (four factors):** Computed from existing boxscore JSONB data — zero external API calls. eFG%, TOV%, ORB%, FT rate, efficiency ratings, pace, game score. 2 new DB tables, frontend section.
- **Shared infrastructure:** `_dispatch_final_actions()` fires sport-specific Celery tasks 60s after game final. `advanced_stats_phase.py` dispatches per league. All 5 sports have frontend components in game detail view.

### Season Audit

- **Season audit endpoint:** `GET /api/admin/sports/season-audit?league=NBA&season=2025` returns game counts vs expected, coverage percentages for 7 data types (boxscore, PBP, odds, social, flow, advanced stats), and team counts.
- **Season audit UI:** New page at `/admin/sports/season-audit` with league/season/type selector, progress bars with green/yellow/red thresholds.
- **Expected game baselines:** Added `expected_regular_season_games` and `expected_teams` to `LeagueConfig` (NBA=1230, NHL=1312, MLB=2430, NCAAB=5460, NFL=272).

### Ingestion Resilience & Backfill Improvements

- **Per-game commit/rollback:** All boxscore, PBP, and advanced stats ingestion loops now commit per-game and rollback on failure. Previously, one `UniqueViolation` poisoned the SQLAlchemy session and killed entire backfills.
- **`only_missing` filter fix:** Changed from checking only `SportsTeamBoxscore` to requiring BOTH team AND player boxscores before skipping a game. Prevents games with team stats but no player stats from being skipped.
- **`source_game_key` UniqueViolation fix:** Removed `source_game_key` assignment during enrichment — now only set at game creation time (SSOT). Was causing cascade failures when enrichment tried to set a key owned by another game row.
- **Advanced stats standalone backfill:** `advanced_stats_phase.py` now calls `_populate_external_ids()` so it can run without boxscore/PBP phases having populated IDs first. Circuit breaker stops after 5 consecutive failures.
- **NFL game stubs:** Added `populate_nfl_games_from_schedule()` to create game rows from ESPN schedule. NFL had 0 games in DB during offseason (no odds to create stubs).
- **Shared math utilities:** Extracted `safe_div`, `safe_pct`, `safe_float`, `safe_int`, `parse_minutes` to `scraper/sports_scraper/utils/math.py`, replacing 9+ duplicate definitions across ingestion services.

### Scheduler & Task Queue Fixes

- **`_HoldAwareTask` base class:** Replaced broken `task_prerun` signal with `app.Task = _HoldAwareTask` in `celery_app.py`. The `task_cls` constructor arg only affects `@app.task`, not `@shared_task`. Hold-aware tasks skip execution when Redis `scheduler:hold` flag is set, unless `manual_trigger` header is present.
- **Backfill bypasses hold:** Added `headers={"manual_trigger": True}` to backfill dispatch so manual triggers are never skipped by the hold mechanism.
- **Task expiry:** Added `expires` option to all high-frequency Celery Beat tasks (orchestrator, polling, odds sync) to prevent queue piling when workers fall behind.
- **Cancel releases locks:** Cancel endpoint now deletes `lock:ingest:{league}` Redis keys for `data_backfill` jobs, preventing orphaned locks from blocking subsequent runs.
- **Backfill pre-dispatch visibility:** Creates `SportsJobRun` with `status="queued"` before Celery dispatch so queued tasks appear immediately in the RunsDrawer.
- **MLB restored to scheduled ingestion:** MLB was accidentally dropped from the leagues list when NFL was added.

### NBA Historical Backfill (Basketball Reference)

- **New scraper:** `NBABasketballReferenceScraper` for boxscores, player stats, and PBP from basketball-reference.com. Polite scraping (5-9s delays), HTML caching, retry with backoff. Covers 1946–present.
- **Historical ingestion service:** `ingest_nba_historical_boxscores()` and `ingest_nba_historical_pbp()` with per-game commit/rollback and `only_missing` skip logic.
- **Celery task:** `ingest_nba_historical` dispatchable from Control Panel with date range params.
- **NBA CDN season guard:** `_is_current_nba_season()` prevents wasteful NBA CDN API calls for historical seasons. CDN only serves current season data.
- **SSOT enforcement:** NBA removed from `_SCRAPER_REGISTRY` (Basketball Reference is standalone historical, not a fallback). NBA CDN scoreboard "fallback" log downgraded from WARNING to INFO.

### Advanced Stats Fixes

- **Archived games:** All 5 sports' advanced stats ingestion now processes `archived` games (was skipping ~55 NBA games from Jan 24-31 that had been promoted from `final` to `archived`).
- **NCAAB nested key fix:** CBB Stats API returns nested JSONB (`{"fieldGoals": {"made": 25}}`) but the fetcher expected flat keys (`fieldGoalsMade`). Fixed `_extract_stat()` to handle both formats. Was causing 1,400+ NCAAB games to report `empty_boxscores`.
- **NFL game ID matching fix:** nflverse `old_game_id` (GSIS format `2024090500`) doesn't match ESPN event IDs (`401772860`). Changed to match by `game_date` + `home_team` + `away_team`. ESPN game ID no longer required.
- **`nflreadpy` dependency:** Added to `scraper/pyproject.toml` (was missing — every NFL game hit `nflreadpy_not_installed`).

### Error Handling Hardening (15 items)

- **Redis lock fail-closed:** `acquire_redis_lock()` returns `None` on Redis failure instead of a dummy token. Prevents duplicate concurrent task execution during Redis outages.
- **JWT validation:** Production startup refuses to start if `JWT_SECRET` equals the insecure default.
- **Game stub logging:** 5 bare `except: pass` blocks in `poll_game_calendars` now log at DEBUG level.
- **Social task fail-closed:** `_social_task_exists_for_league()` returns `True` on DB error (prevents duplicate dispatch).
- **Pitch model log upgrade:** `logger.debug` → `logger.warning` for pitch model load failures in simulation engine.
- **Error counters:** All per-game boxscore/PBP/advanced stats loops now return `(processed, enriched, with_stats, errors)` 4-tuple. Callers track and log error counts.
- **Odds error/skip split:** `_persist_snapshots` separates DB errors from match skips in its counters.
- **Partial success:** `ScrapeRunManager.run()` tracks phase errors and marks runs as `partial_success` when some phases fail but others succeed.
- **Model registration failure:** Now propagated as `RuntimeError` instead of swallowed — training job reports "error" if model can't be registered.
- **React ErrorBoundary:** Admin layout wraps children in ErrorBoundary to prevent white-screen crashes.
- **Celery `task_acks_late`:** Both scraper and API Celery apps now acknowledge tasks only after completion (prevents task loss on worker crash).
- **DB credential validation:** Production startup rejects `sports:sports` default credentials (was only checking `postgres:postgres`).
- **Poller circuit breakers:** Realtime polling loops use exponential backoff after 10 consecutive failures.
- **Ensemble `providers_used`:** ML ensemble tracks which probability providers contributed to predictions.
- **Redis typed returns:** Live odds Redis reads return `(data, error)` tuples. Frontend sees `redis_status: "error"` when Redis is down.

### Logging & UI Fixes

- **structlog level fix:** Switched from `PrintLoggerFactory` to `stdlib.LoggerFactory` + `ProcessorFormatter`. Celery was showing all structlog messages as WARNING regardless of actual level.
- **NCAAScoreboardClient fix:** Constructor changed to require `httpx.Client` argument but caller in `scrape_tasks.py` was using no args.
- **RunsDrawer multi-select filter:** Status filter changed from single-select dropdown to multi-select chips. Added skipped, canceled, interrupted statuses.
- **Control panel defaults:** All leagues and data types unselected by default. Added "Force re-upsert all games" checkbox.
- **Season audit pro-rating:** Expected games pro-rated for in-progress seasons based on season calendar dates. Shows all 5 leagues at once (no league picker).
- **PBP diagnostics gated:** `detect_missing_pbp` only runs when `config.pbp=True` — boxscore-only runs no longer spam PBP missing warnings.

## [2026-03-19]

### Golf Data Layer & Country Club Pools

- **Golf data ingestion:** Full DataGolf API integration — tournaments, players, leaderboard, field, odds (outrights + matchups), DFS projections, skill ratings. 8 golf tables (`golf_tournaments`, `golf_players`, `golf_leaderboard`, `golf_rounds`, `golf_player_stats`, `golf_tournament_odds`, `golf_tournament_fields`, `golf_dfs_projections`). Celery tasks sync leaderboard every 5 min, odds every 30 min, field every 6h, schedule daily.
- **Golf pool system:** Country club pool feature for Masters and other tournaments. Two variants: RVCC (7 picks, best 5 of those who make cut) and Crestmont (6 picks from buckets, best 4). 8 pool tables. Pure scoring engine with 28 unit tests. Materialized leaderboard refreshed every 5 minutes. CSV bulk import for entries. Admin UI with pool management, leaderboard review, and entry inspection.
- **Golf API:** 11 data endpoints (`/api/golf/tournaments`, `/players`, `/odds`, `/dfs`) + 15 pool endpoints (`/api/golf/pools/*` — CRUD, entry submission, leaderboard, buckets, CSV upload, rescore, lock). Admin web pages for tournaments, players, pools, and control panel tasks.
- **Golf admin UI:** Dashboard, tournament browser/detail, player search/detail, pool list/create/detail with leaderboard and entry tabs. 7 golf sync tasks + pool scoring task in control panel.

### NHL PBP Improvements

- **Deduplication:** NHL API returns duplicate events with different sortOrder values. Ingestion now deduplicates on `(period, game_clock, play_type, team, player)` before persisting.
- **Richer descriptions:** Hits now show hitter/hittee/zone ("Hit (Player A on Player B) in D zone"), blocked shots show blocker/shooter, giveaways/takeaways include zone.
- **Tier reassignment:** NHL Tier 2 reduced from `[penalty, delayed_penalty, takeaway, giveaway, hit]` to `[penalty, delayed_penalty]`. Hits/giveaways/takeaways demoted to Tier 3 to reduce timeline noise.

### Game Calendar Polling

- **15-minute calendar poll:** New `poll_game_calendars` Celery task fetches schedules from all league APIs every 15 minutes. Creates game stubs for games added after the daily 3:30 AM ingestion (postseason matchups, schedule changes).
- **7-day lookahead:** Calendar poll looks 7 days ahead so upcoming games are in the DB well before tip-off. NBA/NCAAB loop per-day; NHL/MLB use native range APIs.

### Simulation Calibration & Infrastructure

- **Baseline anchoring:** `anchor_to_baseline()` in `probability_provider.py` clamps ML model outputs within 25% of league-average baseline probabilities. Prevents poorly-calibrated models from producing absurd simulations (e.g., 60% hit rate → 30 runs/game) while preserving meaningful team differentiation
- **Canonical PA labels:** Unified to a single label set (`strikeout`, `walk_or_hbp`, `ball_in_play_out`, `single`, `double`, `triple`, `home_run`). Removed the V1/V2 dual-label system, the `PA_EVENTS_V2` constant, and the `_V2_TO_V1` translation layer. All consumers now use canonical labels directly
- **XGBoost label encoding:** `_XGBStringClassesWrapper` in `training_pipeline.py` handles XGBoost's integer-label requirement transparently. Wraps the model after `fit()` so `predict()` / `predict_proba()` / `classes_` return string labels. Serializes correctly via joblib
- **Prediction outcomes filter:** `GET /prediction-outcomes` now accepts `batch_sim_job_id` query parameter to scope results to a specific batch job
- **Bulk delete loadouts:** `POST /feature-configs/bulk-delete` endpoint + frontend UI with checkbox selection and "Delete N" button on the LoadoutsPanel
- **Loadout dropdown in experiments:** Experiments page now loads all MLB loadouts (removed overly restrictive `model_type` filter)
- **FairBet deadlock fix:** `delete_stale_fairbet_odds()` now uses `pg_try_advisory_xact_lock()` to prevent deadlocks when multiple Celery workers run concurrent stale deletes
- **Log-relay training worker:** Added `sports-api-training-worker` to allowed containers in both `docker_logs.py` (API) and `log-relay/server.py` (sidecar)
- **Resizable logs drawer:** Drag handle on left edge allows resizing between 25%–85% of viewport width (default 50%)
- **Training worker concurrency:** Changed from `--autoscale=4,1` to `--concurrency=2` (fixed). Configurable via `CELERY_TRAINING_CONCURRENCY` env var
- **Dataset builder query optimization:** Replaced `WHERE game_id IN (N ids)` with date-range `JOIN` in all three dataset builders (PA, pitch, batted ball) to support 7,500+ game training
- **Docker deploy fix:** Replaced `docker compose pull --ignore-buildable` with `--policy always` in both CI/CD workflows to prevent skipping services with `build:` directives
- **`parseInt` safety:** All `parseInt` calls in experiments page use explicit radix and `Number.isNaN` guards

## [2026-03-18]

### Pitch-Level Training & Simulation Overhaul

- **Pitch outcome dataset builder:** `MLBPitchDatasetBuilder` extracts individual pitches from `raw_data["playEvents"]` with count state, zone, speed, and point-in-time batter/pitcher profiles. Labels derived from `details.code` via `mlb_pitch_labeler.py`
- **Batted ball dataset builder:** `MLBBattedBallDatasetBuilder` extracts BIP outcomes with exit velocity, launch angle, and spray angle (derived from hit coordinates). Rows without `launchSpeed` are skipped
- **Profile loading consolidation:** Extracted `_profile_mixin.py` (ProfileMixin) with shared `_load_profile_histories()`, `_build_player_profile()`, `_build_pitcher_profile()`. All three dataset builders (PA, pitch, batted ball) now inherit from this mixin
- **Training pipeline:** Registered `pitch` and `batted_ball` model types in `TrainingPipeline`. Added `pitch_label_fn()` and `batted_ball_label_fn()` to `MLBTrainingPipeline`. Default classifiers: RandomForestClassifier with `class_weight="balanced"` for both
- **Feature builder:** Added `_PITCH_FEATURES` and `_BATTED_BALL_FEATURES` specs to `mlb_features.py` with routing in `build_features()` for `model_type="pitch"` and `"batted_ball"`
- **Pitch-level simulation refactor:** `_run_pitch_level()` now uses `SimulationRunner` (not manual iteration), resolves per-team profiles for differentiated probabilities, and loads trained models from the registry
- **Event diagnostics:** `PitchLevelGameSimulator` returns `home_events`/`away_events` with PA counts, enabling `SimulationRunner._aggregate_events()` to produce full event summaries for pitch-level mode
- **Dead code removal:** Removed unused `MLBRunExpectancyModel` import/instantiation from pitch simulator, dead `_simulate_half_inning()` wrapper, wasteful re-run sampling loop, stale `import random` from simulation engine
- **Bug fix:** `GradientBoostingClassifier` does not support `class_weight` — switched pitch model default to `RandomForestClassifier`
- **Security:** Replaced `passlib` with direct `bcrypt` for password hashing

**Files changed:** `simulation_engine.py`, `pitch_simulator.py`, `training_pipeline.py`, `mlb_training.py`, `mlb_features.py`, `_training_data.py`, `analytics_routes.py`, `security.py`, `requirements.txt`. **New:** `_profile_mixin.py`, `mlb_pitch_dataset.py`, `mlb_pitch_labeler.py`, `mlb_batted_ball_dataset.py`, `test_pitch_dataset.py`, `test_batted_ball_dataset.py`, `test_models_and_features.py`, `test_simulation_training_coverage.py`, `test_profile_mixin_and_datasets.py`

## [2026-03-17]

### Post-Simulation Diagnostics & Sanity Analysis

- **Event tracking:** `MLBGameSimulator` now returns per-team PA event counts (`home_events`/`away_events`) and `innings_played` from both `simulate_game()` and `simulate_game_with_lineups()`. Backward compatible — existing callers unaffected
- **Event summary aggregation:** `SimulationRunner.aggregate_results()` computes `event_summary` with per-team PA rates (K%, BB%, HR%, hit rate) and game-shape metrics (extra innings %, shutout %, 1-run game %)
- **Sanity warnings:** `check_simulation_sanity()` and `check_batch_sanity()` in `simulation_analysis.py` flag anomalous results (unrealistic runs, PA outside 30–50, WP flatness)
- **Batch sim enrichment:** Batch results include `batch_summary` (avg runs/team, avg total/game, home win rate, WP distribution) and `warnings` array. Computed on-the-fly during API serialization — no DB migration required
- **UI sanity panel:** Batch sim results page shows a "Simulation Sanity" section with score realism, PA mix breakdown, game shape metrics, and yellow warning cards

### Model-Specific Simulation (`model_id` Parameter)

- **`model_id` on `/simulate`:** Test a specific trained model without activating it globally. Threads through `SimulationEngine` → `ProbabilityResolver` → `MLProvider` → `ModelInferenceEngine`
- **`model_id` on `/batch-simulate`:** Test a model across a full date range of games. When `model_id` or `probability_mode=ml` is set, batch sim now routes through the ML pipeline instead of rule-based `profile_to_pa_probabilities()` conversion
- **`ModelRegistry.get_model_info_by_id()`:** Look up any registered model by ID, not just the active one
- **`ModelInferenceEngine._get_model(model_id=...)`:** Load a specific model artifact without switching the active model
- **Event summary in `/simulate` response:** Fixed `AnalyticsService.run_full_simulation()` to preserve `event_summary`, diagnostics, and probability metadata that was previously discarded when `SimulationAnalysis.summarize_results()` replaced the runner result

**Files changed:** `game_simulator.py`, `simulation_runner.py`, `simulation_analysis.py`, `simulation_engine.py`, `analytics_service.py`, `analytics_routes.py`, `_pipeline_routes.py`, `batch_sim_tasks.py`, `model_registry.py`, `model_inference_engine.py`, `probability_provider.py`, `analyticsTypes.ts`, `batch/page.tsx`

## [2026-03-14]

### Datetime SSOT — `to_et_date()` Consolidation

- **Bug fix:** After the `tip_time` → `game_date` migration, ~25 call sites used `.date()` on `game_date` (now a full UTC datetime). This returned the UTC date, not the ET sports-calendar date — breaking late-night games (e.g., 11 PM ET = 4 AM UTC next day → wrong date). Games ending after midnight ET were stuck on LIVE with no stats because API queries used the wrong date to populate external IDs
- **New utility:** `to_et_date(dt)` added to both `scraper/sports_scraper/utils/datetime_utils.py` and `api/app/utils/datetime_utils.py`. Converts UTC datetime to ET calendar date. All `.date()` calls on `game_date` replaced with `to_et_date()`
- **Name collision fix:** `api/app/realtime/models.py::to_et_date()` (returned `str`) renamed to `to_et_date_str()` to avoid collision with the SSOT `to_et_date()` (returns `date`)
- **Removed:** `today_eastern()` renamed to `today_et()` for cross-package naming consistency. `eastern_date_to_utc_range()` deleted (dead in production, duplicated scraper's `start_of_et_day_utc()`/`end_of_et_day_utc()`)
- **Inline consolidation:** 4 remaining inline `.astimezone(ET).date()` patterns replaced with `to_et_date()` in `sweep_tasks.py`, `mlb_boxscore_ingestion.py`, `games.py`, `social_tasks.py`
- **Files changed:** 19 scraper files, 4 API files, 3 test files. Net -126 lines

### game_date SSOT — tip_time Removal

- **Breaking:** `tip_time` column removed from `sports_games`. `game_date` now stores the actual scheduled start time (UTC datetime) instead of a midnight placeholder
- **Migration:** `20260314_merge_tip_time` copies `tip_time` into `game_date` where non-null, then drops the column and its indexes
- **API:** `start_time` property and `has_reliable_start_time` property removed from `SportsGame` model. All API responses now use `gameDate` for the scheduled start time
- **Scraper:** All `tip_time` parameters removed from `upsert_game_stub()`, `update_game_from_live_feed()`, `upsert_game()`, and `NormalizedOddsSnapshot`
- **Tweet mapper:** `_get_game_start()` simplified to use `game.game_date` directly. `_pregame_start_utc()` and window floor calculation now convert to ET before extracting the calendar date
- **Game state updater:** All queries updated from `SportsGame.tip_time` to `SportsGame.game_date`
- **Odds persistence:** Removed `tip_time` backfill logic from `upsert_odds()`
- **Tests:** All test files updated — removed `tip_time` mock attributes, deleted tests for removed behavior (`test_sets_tip_time_when_null`, `test_updates_tip_time_on_cache_hit`, `TestUpsertOddsUpdateTipTime` class)

### MLB Game Detail — Pitcher and Fielding Stats

- **Pitcher game stats:** Game detail endpoint now loads `MLBPitcherGameStats` for the current game via `selectinload`
- **Per-game fielding stats:** `MLBPlayerFieldingStats` refactored from seasonal aggregates to per-game rows (one row per player per game). Game detail endpoint queries fielding stats for both teams in the current game. Gated to regular season and postseason only
- **Migration:** `20260313_add_mlb_player_level_tables` adds `mlb_pitcher_game_stats` and `mlb_player_fielding_stats` tables

### game_processors SSOT — PBP & Boxscore Processing

- **Refactor:** Extracted per-game PBP and boxscore processing into `scraper/sports_scraper/services/game_processors.py`. Both live polling (`polling_helpers.py`) and scheduled ingestion (`pbp_*.py`, `*_boxscore_ingestion.py`) now call the same functions, ensuring identical processing regardless of trigger
- **Dead code removal:** `_select_ncaa_pbp_fallback_games()` deleted from `pbp_ncaab.py` (superseded by `game_processors.process_game_pbp_ncaab`)

### MLB Advanced Stats — Raw Counts & Pitcher Enrichment

- **Refactor:** MLB advanced stats display switched from derived rates to raw Statcast counts. Frontend (`MLBAdvancedStatsSection.tsx`) updated to show raw values; rate fields removed from TypeScript types
- **Pitcher stats:** `mlb_pitcher_game_stats` now populated with IP, K, BB, pitch count, zone/chase metrics from Statcast `playByPlay` endpoint

### NCAA Game ID Population — Scoreboard Fallback

- **Enhancement:** `ncaab_game_ids.py` now falls back to the NCAA scoreboard API when the CBB schedule API cannot match a game. Uses team name fuzzy matching against scoreboard entries to populate `ncaa_game_id` for games the CBB API doesn't cover

### Rate Limiting — SSE/Auth Exemption

- **Fix:** SSE (`/v1/sse`) and auth (`/auth/me`) endpoints exempted from rate limiting to prevent 429 cascade on SSE reconnects

### Boxscore Ingestion — Direct PK Lookup

- **Fix:** `persist_game_payload()` accepts optional `game_id` parameter for direct PK fetch, bypassing fuzzy team+date matching when the caller already knows the game ID. Reduced MLB boxscore miss rate from 39% to ~0%

### FairBet Indexes — Concurrent Creation

- **Migration:** `20260314_add_fairbet_odds_indexes` creates indexes on `fairbet_game_odds_work` using `postgresql_concurrently=True` with `autocommit_block()` to avoid deadlocks with active scrapers

### Preferences — MissingGreenlet Fix

- **Fix:** Added `await db.refresh(prefs, ["updated_at"])` after flush in both `put_preferences` and `patch_preferences` to prevent `MissingGreenlet` error from async lazy loading

### CI/CD — Image Tagging

- **PR builds:** Now tagged as `pr-<N>-<short-sha>` + `latest`
- **Push builds:** Tagged as `<short-sha>` + `latest`

### Game Browser — Filter Persistence

- **localStorage caching:** Game browser filters saved to `localStorage` on apply/reset, restored on page load. Offset excluded from persistence

## [2026-03-13]

### User Account Email Flows

- **Email service** (`app/services/email.py`): Async SMTP delivery via `aiosmtplib`. Falls back to logging when `SMTP_HOST` is not configured (local dev)
- **Password reset emails**: `POST /auth/forgot-password` now sends a reset link via email instead of only logging the token. Link points to `{FRONTEND_URL}/auth/reset-password?token=...` (30-minute expiry)
- **Magic-link login**: New `POST /auth/magic-link` and `POST /auth/magic-link/verify` endpoints for passwordless sign-in. Sends a login link via email (15-minute expiry), user exchanges the token for a JWT
- **Config**: Added `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM`, `FRONTEND_URL` settings
- **Dependency**: Added `aiosmtplib==3.0.2`

## [2026-03-12]

### Game Simulator Overhaul — Diagnostics, Freshness & Priority Fix

- **SimulationDiagnostics dataclass**: New `core/simulation_diagnostics.py` — SSOT for simulation run metadata. Tracks `requested_mode`, `executed_mode`, `fallback_used`, `fallback_reason`, `model_info`, and `warnings`. Replaces loose `prob_meta` dicts throughout the engine
- **ProfileResult dataclass**: `profile_service.py` now returns `ProfileResult` with `metrics`, `games_used`, `date_range`, and `season_breakdown` instead of raw `dict | None`. All callers updated to extract `.metrics`
- **Priority bug fix**: Profile-derived PA probabilities no longer shadow ML/ensemble resolver output. `analytics_routes.py` only pre-sets `game_context["home_probabilities"]` for `rule_based` mode; `simulation_engine.py` always overwrites with resolver output
- **ModelInferenceEngine.get_model_status()**: Returns structured availability info (`available`, `model_id`, `version`, `trained_at`, `metrics`, `reason`) used by `ProbabilityResolver` to populate diagnostics
- **API response enrichment**: `/simulate` response now includes `simulation_info` (diagnostics), `predictions` (Monte Carlo + game model entries), and `profile_meta.data_freshness` (per-team game counts and date ranges)
- **Frontend diagnostics**: `SimulationInfoBanner` shows mode badge (blue=ML, yellow=fallback), fallback warnings, model version/accuracy. `DataFreshnessDisplay` shows game counts and stale-data warnings (>3 days). "Rule-Based" added as explicit dropdown option
- **SSOT enforcement pass**: Removed duplicate `_predict_with_game_model()` from `simulator.py` (now imported from `analytics_routes.py`). Fixed `simulator.py` to extract `.metrics` from `ProfileResult`. Updated `guardrails.py` to import tweet constants from `tweet_scorer` (canonical source)
- **Probability validation**: `validate_probabilities()` now called on resolver output; issues added as diagnostics warnings
- **17 tests**: `test_simulation_diagnostics.py` covering dataclass defaults, serialization, ML fallback, active model, rule-based mode, exception handling, priority bug fix, probability validation, ProfileResult fields, get_model_status

## [2026-03-11]

### Lineup-Aware MLB Simulation

- **Player profile service**: `get_player_rolling_profile()` and `get_pitcher_rolling_profile()` in `profile_service.py` — queries per-batter Statcast data and per-pitcher boxscore JSONB to build rolling statistical profiles. Sparse data blending (< 5 games → weighted blend with team average)
- **Team roster endpoint**: `GET /api/analytics/mlb-roster?team=NYY` — returns recent batters and pitchers for lineup selection UI
- **Lineup-aware simulator**: `MLBGameSimulator.simulate_game_with_lineups()` — per-batter probability distributions via `MLBMatchup.batter_vs_pitcher()`, lineup index tracking across innings, starter-to-bullpen transition at configurable inning
- **Pre-computed weights**: 36 `batter_vs_pitcher()` calls (9 batters × 2 pitcher states × 2 teams) computed once before the 10k-iteration loop — same performance as team-level simulation
- **API orchestration**: `SimulateRequest` extended with optional `home_lineup`, `away_lineup`, `home_starter`, `away_starter`, `starter_innings` fields. When lineup fields are provided, routes through lineup-aware path automatically
- **Hard failure on unsupported lineup mode**: `SimulationRunner` raises `RuntimeError` if `use_lineup=True` is passed to a simulator without `simulate_game_with_lineups()` — no silent fallback
- **13 tests**: `test_lineup_simulator.py` (7 tests: lineup cycling, pitcher transition, backward compat, determinism) and `test_player_profile.py` (6 tests: rolling profiles, sparse blending, pitcher rate derivation)

### Analytics UI Overhaul

- **Navigation consolidated**: Analytics section reduced from 6 items to 4 (Simulator, Models, Batch Sims, Team Explorer)
- **Simulator page**: Lineup mode toggle with roster auto-fill, 9-slot batter selectors, starting pitcher picker, bullpen transition slider. Removed inline ensemble config (lives in Models only)
- **Models page consolidated**: 4-tab page absorbing former Workbench (Loadouts, Training, Ensemble) and Performance (Calibration, Degradation) pages
- **Batch Sims extracted**: Standalone page at `/admin/analytics/batch` (previously a tab inside Simulator)
- **Dead pages removed**: `workbench/page.tsx`, `model-performance/page.tsx`, `simulator/BatchSimulator.tsx` — orphaned after route removal
- **Stale docstrings updated**: Backend references to "workbench" updated to "models page"

### Live Odds Status Filtering

- **Fix**: `GET /api/fairbet/live/games` now filters to only return games with live status (`in_progress`, `live`, `halftime`). Previously returned all games with Redis odds data regardless of status, causing pregame and final games to appear on the live odds page.

### User Authentication & Account Management

- **User accounts**: `users` table (email, password_hash, role, is_active, created_at) with Alembic migration
- **JWT authentication**: Signup, login, and identity endpoints at `/auth/*` — returns JWT with role claim
- **Role-based access**: Three-tier system (guest/user/admin) with FastAPI dependencies (`resolve_role`, `require_user`, `require_admin`)
- **Self-service account management**: Authenticated users can update email, change password, and delete their own account (all require password confirmation)
- **Admin user management**: Full CRUD at `/api/admin/users/*` — list, create, update role, enable/disable, change email, reset password, delete
- **Admin UI**: Users management page at `/admin/users` with inline editing, role dropdown, enable/disable toggle, and delete confirmation
- **Feature flag**: `AUTH_ENABLED=false` bypasses all role checks (returns admin for all requests) for gradual rollout
- **Shared password hashing**: Single `CryptContext` in `app/security.py` used by all modules
- **Configuration**: `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`, `AUTH_ENABLED` in `app/config.py`
- **19 tests**: Full coverage of JWT creation/decoding, role resolution, and access control in `test_roles.py`

### Legacy Code Cleanup (SSOT Enforcement)

- **Removed**: 3 backward-compat constants (`BLOWOUT_MARGIN_THRESHOLD`, `GARBAGE_TIME_MARGIN`, `GARBAGE_TIME_PERIOD_MIN`) from `block_analysis.py` — superseded by `league_config.get_config()`
- **Fixed**: Broken `AsyncSessionLocal` import in `backfill_timelines.py` — replaced with `get_async_session()`
- **Secured**: Removed hardcoded admin credentials from `seed_admin_user.py` — now reads from environment variables
- **Consolidated**: Triplicated `CryptContext` instantiation collapsed to single `app/security.py` SSOT

## [2026-03-08]

### MLB Constants SSOT (P2-B)

- **Centralized MLB constants**: All baseline values, default event probabilities, hit-type fractions, feature baselines, and simulation parameters consolidated into `app.analytics.sports.mlb.constants` — single source of truth
- **7 consumer modules updated**: `matchup.py`, `metrics.py`, `game_simulator.py`, `mlb_features.py`, `probability_provider.py`, `pa_model.py`, `mlb_training.py` now import from the constants module instead of defining their own copies
- **SSOT enforcement tests**: 7 negative tests in `TestSSOTMLBConstants` guard against regression (deleted functions stay deleted, imports come from SSOT)

### PA Model Implementation (P2)

- **PA training data loading**: `_training_helpers.py` now loads plate appearance training data from `MLBPlayerAdvancedStats` — builds rolling batter profiles paired with opposing team profiles using configurable window sizes
- **Heuristic outcome derivation**: `_derive_pa_outcome()` classifies PA outcomes (strikeout, walk, home_run, double, single, out) from Statcast game-level metrics (whiff rate, barrel rate, exit velocity, hard-hit rate, swing rates)
- **Multi-class Brier score**: Backtest evaluation now computes multi-class Brier score for PA models (sum of squared probability errors across all outcome classes)
- **Frontend enabled**: Removed `disabled` attribute from plate appearance option in workbench training dropdown — PA model training is now end-to-end functional
- **9 new tests**: `test_training_helpers_pa.py` covers all outcome derivation paths plus validity check against `PA_EVENTS`

### Model Registry & Charting (P3)

- **Registry cleanup**: Reset `models/registry/registry.json` (was full of 12 stale entries pointing to non-existent pytest temp dirs); training pipeline now uses artifact_dir-local registry to prevent test pollution
- **`.gitignore` updated**: Added `*.pkl`, `*.joblib`, `api/models/` to prevent model artifacts from being committed
- **Recharts charting library**: Added `recharts` to web dependencies; 4 chart components (`ScoreDistributionChart`, `PAProbabilitiesChart`, `WinProbabilityTimeline`, `CalibrationChart`) in `charts.tsx`
- **Simulator page charts**: PA probabilities, score distribution, and win probability timeline now render as interactive charts instead of raw tables
- **Model performance chart**: Calibration chart showing predicted WP vs actual win rate across 6 probability buckets
- **Live sim persistence**: Timeline state persisted to `sessionStorage` — survives page navigation, restored on mount, cleared on explicit reset

### Legacy Code Removal (P4)

- **Dead label functions deleted**: `pitch_label_fn()`, `batted_ball_label_fn()`, `run_expectancy_label_fn()` removed from `MLBTrainingPipeline` — no callers in production code
- **Dead constants deleted**: `PITCH_OUTCOMES`, `BATTED_BALL_OUTCOMES` removed from `mlb_training.py` — duplicated in model files, only consumed by deleted label functions
- **Dead test class deleted**: `TestMLBTrainingLabels` (3 tests) removed — tested the now-deleted functions
- **Unused import removed**: `HTTPException` from `_model_routes.py`
- **PA_OUTCOMES sourced from SSOT**: `mlb_training.py` now imports `PA_EVENTS as PA_OUTCOMES` from `constants.py` instead of maintaining a local copy
- **Intentionally kept**: Pitch/batted_ball/run_expectancy models are NOT dead code — they are used by `PitchSimulator` via `pitch_level` probability mode in the simulation API

### Analytics P0 Fixes

- **Feature config enforcement (P0-A)**: Fixed broken chain where DB-backed feature loadouts were never applied during training. Added `_feature_config_to_dict()` converter in `training_tasks.py` that transforms `AnalyticsFeatureConfig.features` (JSONB `[{name, enabled, weight}]`) into the `{feat_name: {enabled, weight}}` dict expected by `FeatureBuilder._apply_config()`. Threaded `feature_config` through `TrainingPipeline` → `DatasetBuilder` → `FeatureBuilder.build_features(config=...)`.
- **Analytics docs accuracy (P0-B)**: Fixed MLB feature counts — PA features documented accurately (28 total), game features corrected from "28 total" to "60 total (30 per side)" with full metric key listing. Updated training pipeline steps to describe the feature config enforcement flow.

### Dedicated Live Odds Page

- **New page: `/admin/fairbet/live`**: Full-featured live odds page matching the pregame experience -- discovers all games with live odds, displays them grouped by game with scoreboard header strips
- **New endpoint: `GET /api/fairbet/live/games`**: Scans Redis for all games with live odds data, returns `LiveGameInfo[]` (game_id, league, teams, date, status) sorted by game time
- **New Redis function: `discover_live_game_ids()`**: Scans `live:odds:*` keys and extracts unique `(league, game_id)` pairs for game discovery
- **Multi-game view**: Fetches live odds for all discovered games in parallel, displays in a unified grid with game headers showing league, matchup, live status, last update, and bet count
- **Full filtering**: League, Category, Sort, Hide Alternates -- matching pregame feature parity
- **Auto-refresh**: 15-second polling with visual indicator and manual refresh button
- **Pregame page simplified**: Removed embedded Live tab from `/admin/fairbet/odds` (now pregame-only); live odds have their own dedicated page
- **Navigation**: Added "Live Odds" link in admin sidebar under Data section

## [2026-03-07]

### Analytics Workbench

- **Feature loadouts (DB-backed)**: Full CRUD for feature configurations via `analytics_feature_configs` table -- create, update, delete, clone loadouts with per-feature enabled/weight toggles
- **Available features endpoint**: `GET /api/analytics/available-features` returns all features with descriptions and DB coverage stats
- **Training pipeline**: `POST /api/analytics/train` dispatches async Celery training jobs -- pick a loadout, model type, algorithm, date range, produces joblib artifact registered in model registry
- **Training job tracking**: `analytics_training_jobs` table tracks status (pending, running, completed, failed), metrics, artifact path, and Celery task ID
- **Admin UI workbench**: Two-tab page (Feature Loadouts + Train Model) with loadout builder, feature grid, and training job status polling
- **Alembic migration**: `20260307_000013` creates `analytics_feature_configs` and `analytics_training_jobs` tables

### Analytics SSOT Cleanup

- **6 legacy pages deleted**: team, player, matchup, feature-config, ensemble, baseball-models -- consolidated into Explorer (3 tabs) and Workbench
- **Navigation consolidated**: Analytics section reduced from 10 items to 6 (Overview, Workbench, Models, Simulator, Performance, Explorer)
- **YAML configs removed**: `config/features/` directory and legacy training scripts (`scripts/train_models/`) deleted -- DB-backed loadouts are the SSOT
- **Legacy API types removed**: `FeatureConfigResponse`, `FeatureConfigListResponse`, `getFeatureConfig`, `listFeatureConfigs`, `saveFeatureConfig` replaced by DB-backed equivalents
- **SSOT assertion tests**: 7 tests enforce no legacy symbols in routes, no YAML config files, DB models exist

### Analytics Route Split & Legacy Removal

- **Route file split**: `analytics_routes.py` (800+ lines) split into 4 sub-modules: `_calibration_routes.py`, `_feature_routes.py`, `_pipeline_routes.py`, `_model_routes.py`. Main file is now a thin assembler (~194 lines).
- **Training task split**: Extracted shared helpers from `training_tasks.py` (1173 lines) into `_training_helpers.py` (324 lines) -- data loading, rolling profile aggregation, feature conversion, sklearn model factory
- **Legacy code deleted**: `FeatureConfigLoader`, `FeatureConfigRegistry` (YAML-based), `PredictionRepository` (in-memory), `SimulationRepository`, `SimulationJobManager`, `MLBSimulationAnalysis` (redundant wrapper)
- **Legacy endpoints removed**: `simulate-job`, `live-simulate-job`, `simulation-result`, `simulation-history`, `record-outcome` (single), `model-performance`, `predictions`, `mlb/pitch-model`, `mlb/pitch-sim`, `mlb/run-expectancy`
- **DB-backed replacements**: Prediction outcomes via `analytics_prediction_outcomes`, degradation alerts via `analytics_degradation_alerts`, batch simulation via `analytics_batch_sim_jobs`, backtesting via `analytics_backtest_jobs`
- **Frontend cleanup**: Removed unused exports (`getPitchModel`, `getPitchSim`, `getRunExpectancy`, `getBacktestJob`, `getBatchSimJob`, `getEnsembleConfig`)

### Documentation Consolidation

- **LOCAL_DEVELOPMENT.md deleted**: Content consolidated into INFRA.md (Docker setup, manual setup, troubleshooting in one place)
- **OPERATOR_RUNBOOK.md slimmed**: Removed duplicated deployment/migration/env-var sections, now references DEPLOYMENT.md and INFRA.md
- **ARCHITECTURE.md fixed**: Removed stale `GET /api/analytics/mlb/*` endpoints, added 4 missing analytics DB tables
- **DATABASE_INTEGRATION.md fixed**: Added 4 missing analytics tables (backtest_jobs, batch_sim_jobs, prediction_outcomes, degradation_alerts)
- **INDEX.md updated**: Fixed analytics description, updated links for consolidated docs

## [2026-03-06]

### Analytics Engine

- **Monte Carlo simulation**: `POST /api/analytics/simulate` runs N-iteration game simulations with pluggable probability sources (`rule_based`, `ml`, `ensemble`, `pitch_level`)
- **Live simulation**: `POST /api/analytics/live-simulate` simulates from a mid-game state (inning, outs, bases, score)
- **Batch simulation**: `POST /api/analytics/batch-simulate` for background execution with job tracking via `/batch-simulate-jobs`
- **Team/Player/Matchup profiles**: `GET /api/analytics/team`, `/player`, `/matchup` endpoints for analytical profiles and head-to-head probability distributions
- **ML model registry**: `GET/POST /api/analytics/models/*` endpoints for listing, activating, comparing, and inspecting registered models (JSON-backed, one active per sport/model_type)
- **Model inference**: `POST /api/analytics/model-predict` runs predictions through the active ML model with feature extraction from entity profiles
- **Feature configuration**: DB-backed feature loadouts (`/api/analytics/feature-config*` CRUD) for configurable feature sets per sport/model type
- **Ensemble system**: Weighted combination of rule-based and ML predictions (`GET/POST /api/analytics/ensemble-config`) with configurable provider weights
- **Prediction calibration**: `POST /api/analytics/record-outcomes` triggers auto-recording; `GET /api/analytics/calibration-report` returns Brier score, accuracy, and bias metrics
- **Degradation alerts**: `POST /api/analytics/degradation-check` triggers model quality analysis; `GET /api/analytics/degradation-alerts` lists alerts
- **Backtesting**: `POST /api/analytics/backtest` starts async backtest job against held-out data
- **5 built-in MLB models**: plate appearance, game, pitch outcome, batted ball, run expectancy — each with rule-based fallbacks using league-average baselines
- **Admin UI pages**: 6 analytics pages (Overview, Workbench, Models, Simulator, Performance, Explorer)

### Repository Cleanup

- **Dead code removed**: Unused `_run_single_iteration()` method from `SimulationEngine`, unused `runner` variable in `AnalyticsService`, unused `getActiveModel()`/`getModelMetrics()` functions from web API client
- **Lint fixes (15 total)**: 8 unused imports, 1 unsorted import block, 6 line-too-long violations across analytics package
- **Duplicate utilities consolidated**: `formatMetricName()`/`formatMetricValue()` extracted from analytics pages into shared `web/src/lib/utils/formatting.ts`
- **Trailing whitespace removed**: `AdminTable.tsx`

### Documentation

- **ANALYTICS.md** (NEW): Full documentation of the analytics/ML engine — package structure, simulation, probability providers, model registry, feature pipeline, training, MLB models, ensemble system, and all 29 API endpoints
- **API.md**: Added Analytics section (29 endpoints across 8 subsections) with parameter tables, request/response examples
- **ARCHITECTURE.md**: Added Analytics Engine as first-class component (Section 3) with endpoint listing
- **INDEX.md**: Added Analytics & ML section
- **README.md**: Updated directory descriptions, added analytics doc link
- **INFRA.md**: Consolidated local development content, added troubleshooting section
- **OPERATOR_RUNBOOK.md**: Replaced duplicated env vars table with cross-reference to INFRA.md

### Live +EV Fair-Bet Computation

- **Live EV pipeline**: `GET /api/fairbet/live` now runs the same EV pipeline as pre-game odds (Shin devig, Pinnacle reference, extrapolation) on live in-game odds from Redis — nothing persisted to the DB
- **Multi-book Redis snapshots**: Live odds scraper now aggregates all bookmakers per (game, market) into a single Redis snapshot instead of writing per-bookmaker (which caused last-write-wins data loss)
- **`write_live_snapshot` signature change**: From `(selections, provider)` to `(books: dict[str, list[dict]])` — stores all bookmakers in one key enabling cross-book EV computation
- **Removed old closing-lines comparison**: Old `ClosingLineResponse` / `LiveSnapshotResponse` models and the closing-lines-vs-live-snapshot UI removed; replaced with full EV-annotated `LiveBetDefinition` and `FairbetLiveResponse`
- **Frontend Pre-Game/Live tabs**: FairBet odds page split into Pre-Game and Live tabs sharing a `BetCard` component; Live tab has game selector, 15s auto-refresh, and pulsing live indicator
- **Frontend API client**: Added `FairbetLiveResponse`, `FairbetLiveFilters` types and `fetchFairbetLiveOdds()` function

### NCAAB SSOT Consolidation

- **CBB API as single source of truth**: NCAAB game ingestion uses CBB Stats API exclusively for schedule, boxscores, and PBP — removed duplicate data paths
- **MLB Schedule API pre-population**: `populate_mlb_games_from_schedule()` creates game stubs from the MLB Schedule API before the boxscore phase, ensuring all games exist regardless of Odds API coverage (fixes ~66% game gap in MLB backfills)

### Documentation

- **ODDS_AND_FAIRBET.md**: Added "Live +EV (In-Game Odds)" section documenting architecture, Redis snapshot format, API parameters, frontend, and file references
- **API.md**: Rewrote `GET /live` endpoint from old closing-lines format to new EV-annotated response
- **ARCHITECTURE.md**: Updated FairBet Live endpoint description
- **CHANGELOG.md**: Added today's entries

---

## [2026-03-04]

### Social Scraping Hardening

- **Redis visibility timeout**: Set `broker_transport_options.visibility_timeout` to 86400s (24h) to prevent Redis from re-delivering long-running social tasks (root cause of infinite loop where NHL tasks ran 15+ times)
- **Redis distributed locks**: `collect_team_social` (2h lock per league) and `collect_game_social` (30 min lock) use `acquire_redis_lock`/`release_redis_lock` to prevent duplicate execution
- **Live vs bulk queue split**: New `social-bulk` queue and dedicated `social-bulk` worker for heavy tasks (`collect_team_social`, `collect_social_for_league`); live tasks (`collect_game_social`, `run_final_whistle_social`, `map_social_to_games`) stay on `social-scraper` queue with its own worker. Two separate workers ensure multi-hour bulk jobs never block live tasks
- **Rewritten `collect_game_social`**: Now targets games with odds but missing or stale (>2h) social data instead of all games in any status. Frequency increased from hourly to every 30 minutes. `map_social_to_games` staggered to :15/:45.
- **Date range cap**: Bulk social dispatch capped to yesterday+today (was unbounded), reducing NHL from ~32 teams to ~12-16 and cutting task time from ~67 min to ~25-30 min
- **Admin registry fixes**: `collect_social_for_league` queue updated to `social-bulk`; `collect_game_social` description updated to reflect new targeting logic

### Documentation

- **DATA_SOURCES.md**: Updated social schedule from "hourly" to "every 30 minutes"; added bulk queue routing info; updated task dispatch queue list
- **ARCHITECTURE.md**: Fixed PostgreSQL version from 15+ to 16+ (matches `postgres:16-alpine` in docker-compose)
- **INFRA.md**: Updated social-scraper and social-bulk services to document separate worker architecture
- **GAMEFLOW_PIPELINE.md**: Reduced duplication with GAMEFLOW_CONTRACT.md; added cross-references instead of repeating block/role definitions
- **GAME_FLOW_GUIDE.md**: Added cross-references to GAMEFLOW_CONTRACT.md for authoritative spec details

---

## [2026-03-03]

### MLB Advanced Stats (Statcast-derived)

- **New table `mlb_game_advanced_stats`**: Stores team-level advanced batting stats derived from pitch-level Statcast data in the MLB Stats API `playByPlay` endpoint
- **New table `mlb_player_advanced_stats`**: Stores per-batter advanced stats with same columns as team-level, plus player identification
- **Plate discipline stats**: Zone swing rate, outside swing rate, zone contact rate, outside contact rate (zones 1-9 = strike zone, 11-14 = outside)
- **Quality of contact stats**: Average exit velocity, hard-hit rate (>= 95 mph), barrel rate (MLB barrel formula: >= 98 mph + angle window)
- **Automatic dispatch**: `ingest_mlb_advanced_stats` task fires with 60s countdown when an MLB game transitions to FINAL
- **API integration**: `mlbAdvancedStats` and `mlbAdvancedPlayerStats` on game detail response, `hasAdvancedStats` on game list/detail
- **Admin trigger**: `ingest_mlb_advanced_stats` added to task registry for on-demand dispatch

### Documentation

- **README.md**: Fixed league list to include MLB
- **API.md**: Added MLB to Supported Leagues table with Advanced Stats; added `hasAdvancedStats`, `mlbAdvancedStats`, `mlbAdvancedPlayerStats`, `mlbBatters`, `mlbPitchers`, `MLBAdvancedTeamStats`, `MLBAdvancedPlayerStats`, `MLBBatterStat`, `MLBPitcherStat` models; added `lastAdvancedStatsAt` to `GameSummary`/`GameMeta`; added `withAdvancedStatsCount` to `GameListResponse`
- **DATA_SOURCES.md**: Fixed MLB boxscore URL (`api/v1/game/{game_pk}/boxscore`); added MLB flow generation schedule (11:00 UTC / 6:00 AM ET); added MLB Advanced Stats section
- **DATABASE_INTEGRATION.md**: Added `mlb_game_advanced_stats` and `mlb_player_advanced_stats` tables; fixed `status = 'completed'` to `'final'` in example query
- **ARCHITECTURE.md**: Updated ingestion diagram from "SportsRef" to "League APIs"; added `mlb_game_advanced_stats` and `mlb_player_advanced_stats` to schema list
- **DATA_SOURCES.md**: Updated MLB Advanced Stats section to cover both team-level and player-level stats

---

## [2026-02-27]

### Documentation Consolidation

- **DATABASE_INTEGRATION.md**: Expanded schema table from 11 to 26 tables, organized into sections (Core, Odds, Social, Game Flow, Operations). Fixed `status = 'completed'` → `'final'` in example query.
- **EV_LIFECYCLE.md**: Consolidated from 245 lines to ~100 lines. Removed sections 1-4 and 7-9 that duplicated ODDS_AND_FAIRBET.md (~60% overlap). Retained unique value: Shin's formula, American-to-implied conversion, decimal odds conversion, worked examples, and fair odds sanity check.
- **DATA_SOURCES.md**: Added social task queue documentation (pre-dispatch visibility, FIFO cap at 10, queued status, eviction). Added comprehensive rate limiting table (per-scroll, between teams, between games, circuit breaker). Fixed NBA boxscore source from "basketball-reference.com" to "NBA API (cdn.nba.com)".
- **ARCHITECTURE.md**: Fixed NBA boxscore source from "Sports Reference" to "NBA API (cdn.nba.com)".
- **INDEX.md**, **ODDS_AND_FAIRBET.md**: Updated cross-references to match EV_LIFECYCLE.md consolidation.

### Queued Social Tasks

- Social backfill tasks are now immediately visible in the RunsDrawer with `status="queued"` before the worker picks them up
- Queued tasks are cancellable (Celery task revoked) and capped at 10 with oldest-first eviction
- Pre-generated Celery task IDs link the DB record to the Redis-queued task
- Worker transition: `queued` → `running` → `success`/`error`
- Cancel endpoint accepts both `"running"` and `"queued"` statuses
- Job list sorted by `created_at` instead of `started_at` so queued tasks sort correctly
- Stale-run cleanup on worker restart/shutdown includes `"queued"` status
- UI: RunsDrawer shows queued status pill, social phase filter, cancel button for queued tasks

### Social Rate Limiting

- Per-scroll delay changed from fixed 2s to random 5–10s
- Polite delay between team requests changed from 20–30s to 30–60s
- Inter-game delay changed from fixed 45s to random 30–60s (configurable via `inter_game_delay_seconds`/`inter_game_delay_max_seconds`)

## [2026-02-24]

### Server-Side Business Logic Migration

Moves client-side display logic to the API so clients become dumb renderers. All new fields are additive (`Optional` with `None` defaults) — no breaking changes.

#### FairBet Explanation Steps
- **`explanation_steps`** on `BetDefinition`: Pre-computed step-by-step math walkthrough explaining how fair odds were derived — eliminates ~300 lines of client-side devig math/formatting logic in `FairExplainerSheet.swift`
- **4 dispatch paths**: Pinnacle paired devig (3-4 steps), Pinnacle extrapolated (3-4 steps), fallback (1-2 steps), not available (1 step with human-readable disabled reason)
- **`ExplanationStep` / `ExplanationDetailRow` models**: Each step has `step_number`, `title`, `description`, and `detail_rows` (label/value with `is_highlight` for client emphasis)
- **Pure function**: `build_explanation_steps()` in `fairbet_display.py` — all inputs passed explicitly, no router imports
- **8 new tests** in `test_fairbet_display.py`: all paths, sequential numbering, EV math consistency with `calculate_ev()`

#### Status Flags + Live Snapshot
- **Status convenience flags** on `GameSummary` and `GameMeta`: `isLive`, `isFinal`, `isPregame`, `isTrulyCompleted`, `readEligible` — eliminates client-side `deriveGameStatus()` / `isGameTrulyCompleted()`
- **`currentPeriodLabel`**: Server-computed period label ("Q4", "2nd Half", "P3", "OT") reusing existing `period_label()` — eliminates client-side `getPeriodLabel()`
- **`liveSnapshot`**: At-a-glance live state (`periodLabel`, `timeLabel`, `homeScore`, `awayScore`, `currentPeriod`, `gameClock`)
- **`dateSection`**: Game date classification ("Today", "Yesterday", "Tomorrow", "Earlier", "Upcoming") in US Eastern — eliminates client-side `classifyDateSection()`
- **New service**: `game_status.py` — pure function mapping status strings to booleans
- **New service**: `date_section.py` — date classification in US Eastern timezone

#### FairBet Display Fields
- **`BetDefinition` display fields**: `fairAmericanOdds`, `selectionDisplay`, `marketDisplayName`, `bestBook`, `bestEvPercent`, `confidenceDisplayLabel`, `evMethodDisplayName`, `evMethodExplanation` — eliminates client-side odds formatting, selection display, and confidence label logic
- **`BookOdds` display fields**: `bookAbbr`, `priceDecimal`, `evTier` — eliminates client-side book abbreviation tables and EV tier computation
- **`evConfig`** on `FairbetOddsResponse`: `minBooksForDisplay`, `evColorThresholds` — server controls display thresholds
- **New service**: `fairbet_display.py` — display-oriented helpers for FairBet odds
- **New constants** in `ev_config.py`: `BOOK_ABBREVIATIONS`, `CONFIDENCE_DISPLAY_LABELS`, `MARKET_DISPLAY_NAMES`, `FAIRBET_METHOD_DISPLAY_NAMES`, `FAIRBET_METHOD_EXPLANATIONS`

#### Game Detail Odds Table
- **`oddsTable`** on `GameDetailResponse`: Structured odds grouped by market (spread → total → moneyline) with opening/closing lines and `isBest` flags — eliminates client-side odds grouping/sorting/best-line logic
- **New service**: `odds_table.py` — builds structured odds table from raw `SportsGameOdds`

#### Stats Normalization + Annotations
- **`normalizedStats`** on `TeamStat` and `PlayerStat`: Canonical stat array with display labels, resolving alias differences across data sources (Basketball Reference, NBA API, CBB API) — eliminates client-side alias tables
- **`statAnnotations`** on `GameDetailResponse`: Human-readable callouts for notable stat advantages (e.g., "BOS dominated the glass (+7 OREB)") — eliminates client-side `generateAnnotations()`
- **New service**: `stat_normalization.py` — alias resolution with nested dict handling
- **New service**: `stat_annotations.py` — threshold-based annotation generation

#### Timeline Enrichment
- **`PlayEntry` enrichment fields**: `scoreChanged`, `scoringTeamAbbr`, `pointsScored`, `homeScoreBefore`, `awayScoreBefore`, `phase` — eliminates client-side score delta computation and phase classification
- **`enrich_play_entries()`** in `play_tiers.py`: Tracks running scores, computes deltas, assigns game phase per league

#### Miscellaneous
- **Parlay evaluation endpoint**: `POST /api/fairbet/parlay/evaluate` — accepts 2-20 legs with `trueProb` and optional `confidence`, returns combined fair probability, fair American odds, and geometric mean confidence
- **New router**: `parlay.py` registered under `/api/fairbet`

### Tests

- **124 new tests** across 7 test files: `test_game_status.py` (19), `test_fairbet_display.py` (33), `test_odds_table.py` (8), `test_stat_normalization.py` (10), `test_stat_annotations.py` (8), `test_parlay.py` (8), `test_play_tiers.py` (9 new + existing)
- All 1337 tests pass (124 new + 1213 existing)

---

## [2026-02-22]

### EV: Shin's Method for Vig Removal

- **Shin's method**: `remove_vig()` now uses Shin's model to account for favorite-longshot bias, distributing more vig correction to longshots. Falls back to additive normalization when overround is zero.
- **Frontend update**: DerivationContent popover shows Shin's parameter (`z`) and Shin formula instead of simple additive ratio

### Pipeline: Peak Margin Tracking

- **`peak_margin` / `peak_leader` on NarrativeBlock**: Each block now tracks the largest absolute margin that occurred within it, even if that margin eroded by block's end
- **Comeback detection**: New `_detect_big_lead_comeback()` identifies games where a large lead (≥15) was overcome, adding targeted prompt guidance for comeback narratives
- **Close game fix**: `_detect_close_game()` now includes `peak_margin` in max margin calculation, preventing misclassification of games with hidden mid-block leads
- **Drama analysis**: Quarter summaries track `peak_margin` and `peak_leader` for richer AI prompts
- **Render prompts**: `Peak:` lines appear in block prompts when peak margin exceeds boundary margin by ≥6 points

### Social Scraping: SSOT Consolidation

- **`SocialConfig` reshaped**: Removed 7 dead fields (`recent_game_window_hours`, `pregame_window_minutes`, `postgame_window_minutes`, `gameday_start_hour`, `gameday_end_hour`, `max_consecutive_empty_results`, `hourly_request_cap`); added 10 new fields that were previously scattered as local constants
- **`SOCIAL_QUEUE` constant**: All `queue="social-scraper"` hardcoded strings in scraper replaced with `SOCIAL_QUEUE` from `celery_app.py`
- **Config-driven constants**: `team_collector.py`, `playwright_collector.py`, `tweet_mapper.py`, `final_whistle_tasks.py`, `sweep_tasks.py` all read from `SocialConfig` instead of local `_CONSTANTS`
- **`LeagueConfig` for durations**: `tweet_mapper.py` reads game duration and postgame window from `LEAGUE_CONFIG` instead of local dicts. NBA/NHL duration changed from 2.5h to 3.0h, NCAAB from 2.0h to 2.5h (wider mapping windows).
- **`get_social_enabled_leagues()`**: `run_manager.py` derives supported leagues from config instead of hardcoded tuple
- **Dead `task_routes` removed**: Redundant `task_routes` dict in `celery_config` deleted (was immediately overwritten)
- **`collect_game_social` restructured**: Changed from flat team-based iteration to game-based iteration with team dedup, batch commits, and configurable cooldowns
- **`map_social_to_games` scheduled task**: New Celery beat task runs every 30 minutes to map unmapped tweets to games

### Tests

- **Shin's method tests**: 4 new tests (`test_shin_favors_longshot_correction`, `test_shin_extreme_longshot`, `test_shin_near_even_minimal_difference`, `test_no_vig_no_change`) and updated tolerances for symmetric lines
- **Peak margin tests**: Tests for peak margin in quarter summaries (`test_analyze_drama.py`), block creation (`test_group_blocks.py`), serialization round-trip, and prompt rendering (`test_render_blocks.py`)
- **Comeback detection tests**: Tests for `_detect_big_lead_comeback` and `_detect_close_game` with peak margin
- **Social SSOT test fixes**: Updated `test_final_whistle.py` (cooldown 180→15), `test_team_collector.py` (mock settings), `test_persistence.py` (NBA duration 2.5→3.0), `test_tweet_mapper.py` (all duration assertions)

### Documentation

- **EV_LIFECYCLE.md**: Updated devig section from "Additive Normalization" to "Shin's Method" with formula, updated example EV numbers, updated limitation #3

---

## [2026-02-20]

### Control Panel & Admin Consolidation

- **Control Panel page**: New `/admin/control-panel` replaces three separate pages (Runs, Pipelines, Tasks) with a single interface for dispatching any of 17 registered Celery tasks with inline parameter inputs
- **Task Control API**: New `POST /api/admin/tasks/trigger` and `GET /api/admin/tasks/registry` endpoints with a whitelisted task registry (17 tasks across 7 categories: Ingestion, Polling, Odds, Social, Flows, Timelines, Utility)
- **RunsDrawer**: IDE-style bottom panel for job run monitoring, available on all admin pages with collapsed/half/full height states, phase and status filters, and auto-refresh
- **Nav consolidation**: Sidebar simplified to General (Overview), Data (Games, Odds), System (Control Panel, Logs) — Runs, Pipelines, and Tasks pages removed

### Game State & Live Polling

- **Game state machine enhancements**: Improved game state transitions and tracking in `game_state_updater.py`
- **Final whistle social**: New `run_final_whistle_social` task collects post-game social content when games transition to FINAL
- **Live polling unconditional**: `LIVE_POLLING_ENABLED` config field removed; live PBP + boxscore polling now runs in all environments (schedule is unconditional in `celery_app.py`)
- **Job run summaries**: New `job_run_summary_data` column on `sports_job_runs` for tracking run statistics

### NCAAB Enhancements

- **NCAAB live feed clients**: New `ncaa_boxscore.py`, `ncaa_pbp.py`, `ncaa_scoreboard.py`, `ncaa_constants.py` for direct CBB API integration
- **Score filling**: Early plays in NCAAB PBP now get scores filled correctly
- **Game status handling**: Enhanced NCAAB game status parsing in `NCAABLiveFeedClient`

### Legacy Code Cleanup

- **Dead Python code removed**: `pipeline_tasks.py` (dead `trigger_game_pipelines_task`), `get_social_mapping_stats` task, `live_polling_enabled` config field
- **Dead web components removed**: `ScrapeRunForm`, `ScrapeRunsTable`, `RunOriginBadge`, `RunTaskBadges`, `useScrapeRuns` hook
- **Dead API client functions removed**: `createScrapeRun`, `cancelScrapeRun`, `clearScraperCache`, `fetchScrapeRun`, `getGamePipelineSummary`, `getPipelineRun` from frontend API clients
- **Dead pages removed**: `/admin/sports/ingestion/`, `/admin/sports/flow-generator/`, `/admin/sports/tasks/`
- **Bug fix**: Task registry entry `clear_scraper_cache_task` corrected to `clear_scraper_cache` (matching actual Celery task name)

### Tests

- **NCAAB API tests**: 829-line test suite for new NCAA API clients (`test_ncaa_api.py`)
- **Game state updater tests**: Enhanced coverage in `test_game_state_updater.py`
- **Final whistle tests**: Updated `test_final_whistle.py`
- **Flow immutability tests**: Updated `test_flow_immutability.py`

---

## [2026-02-19]

### Admin Console Refactor

- **Sidebar reorganization**: Nav restructured into General (Overview), Data (Games, Runs, Pipelines, Odds), and System (Logs) sections with renamed page titles
- **Structured status indicators**: Replaced green/red dots with 4-state indicators (`present`, `missing`, `stale`, `not_applicable`) that explain *why* data is missing, with contextual tooltips and staleness thresholds
- **Pipeline runs section**: Game detail page now shows pipeline run history with expandable per-stage progress, error details, and a "Run Pipeline" action button
- **Run origin and task badges**: Scrape runs table shows origin (Manual/Scheduled/Rescrape/Odds Sync) and task breakdown (Box/Odds/Social/PBP) badges derived from existing `scraper_type`, `requested_by`, and `config` fields
- **Logs page**: Full-width container log viewer at `/admin/sports/logs` with container tabs, line count selector, text search, auto-refresh, and log level highlighting

### API Alignment

- **`last_odds_at` column**: New nullable timestamp on `sports_games` tracking when odds were last synced for a game; set during odds persistence, exposed in `GameSummary` and game detail responses
- **X-Request-ID correlation**: `StructuredLoggingMiddleware` now generates or echoes `X-Request-ID` headers for request tracing through server logs
- **Pipeline run enrichment**: `PipelineRunSummary` now includes per-stage detail (`stages` field) so the admin UI can render expandable rows without extra fetches
- **Config normalization**: Scrape run config JSONB is parsed through `ScrapeRunConfig` for consistent camelCase serialization

### Legacy Code Elimination

- **Route aliases deleted**: Removed 3 pipeline route aliases and 1 docker logs route alias (`include_in_schema=False` endpoints that delegated to canonical handlers)
- **Computed field shims deleted**: Removed 7 `computed_field` compatibility aliases from pipeline models (`stage_name`, `completed_at`, `error_message`, `auto_chain`, `next_stage`)
- **Docker logs path consolidated**: `/scraper/logs` (legacy) removed; `/logs` is the single canonical path
- **Config fallback removed**: `_normalize_config()` no longer silently falls back to raw JSONB on parse failure — fails fast
- **Frontend fallbacks removed**: `lastOddsAt ?? lastScrapedAt` replaced with direct `lastOddsAt`; duplicate route constants (`SPORTS_BROWSER`, `SPORTS_INGESTION`, `SPORTS_FLOW_GENERATOR`) deleted
- **`has_required_data` removed**: Dropped from schema, backend, and frontend

### Documentation

- **EV_INFRASTRUCTURE_REVIEW.md deleted**: Historical snapshot (2026-02-14) whose findings were already acted upon; superseded by ODDS_AND_FAIRBET.md
- **X_INTEGRATION.md deleted**: Content fully consolidated into DATA_SOURCES.md social section (authentication instructions merged)
- **ARCHITECTURE.md**: Updated admin UI features to reflect refactored console
- **API.md**: Added X-Request-ID correlation documentation; updated `GameSummary` fields (`lastOddsAt` added, `hasRequiredData` removed); logs endpoint path corrected to `/logs`
- **INDEX.md**: Removed entries for deleted docs

---

## [2026-02-18]

### EV Annotation Enhancements

- **Entity key derivation**: `derive_entity_key()` extracts team/game/player identity from selection keys for proper sharp reference grouping — prevents cross-entity EV (e.g., Lakers spread should not use Celtics Pinnacle reference)
- **3-tuple sharp reference grouping**: `_build_sharp_reference()` now groups by `(game_id, market_base, entity_key)` instead of `(game_id, market_base)`, supporting entity-aware Pinnacle lookup
- **Mainline disagreement check**: Rejects extrapolated EV when the mainline Pinnacle reference disagrees with the extrapolated direction
- **Extrapolated probability divergence check**: Rejects extrapolated probabilities that diverge too far from the mainline reference

### Live Stats & PBP SSOT

- **`live_odds_enabled` field**: Added to `LeagueConfig` with import-time assertion ensuring it remains `False` for all leagues — documents the closing-line architecture constraint as code
- **`LIVE_POLLING_ENABLED` setting**: New env var gates live PBP/boxscore polling independently from other production tasks, enabling live polling in non-prod environments
- **Live polling schedule extraction**: `poll_live_pbp` moved from `_prod_only_schedule` to `_live_polling_schedule` with its own gating logic
- **`IngestionConfig.live` → `batch_live_feed`**: Renamed to clarify that this flag controls batch ingestion's use of live endpoints (e.g., `cdn.nba.com`), not scheduled live polling
- **Heartbeat logging**: `poll_live_pbp` zero-games log upgraded from `DEBUG` to `INFO` with structured `poll_live_pbp_heartbeat` event

### Legacy Code Elimination

- **`sync_all_odds` deleted**: Removed legacy wrapper that dispatched `sync_mainline_odds` + `sync_prop_odds`; admin odds sync endpoint now dispatches both tasks directly
- **Backward-compat re-exports removed**: `ncaab_boxscore_ingestion.py` no longer re-exports functions from `ncaab_game_ids`; all importers updated to use canonical module
- **`IngestionConfig` alias removed**: Dropped `Field(alias="live")` and `ConfigDict(populate_by_name=True)` — callers must use `batch_live_feed` directly

### NCAAB Fair Odds Fix

- **DB team names for FairBet selection keys**: `upsert_fairbet_odds()` now looks up the game's actual home/away teams from `sports_teams` instead of using Odds API snapshot names, preventing wrong team names from entering `fairbet_game_odds_work` when a game is mis-matched
- **Team mismatch validation guard**: For moneyline/spread bets, the FairBet upsert now verifies that the snapshot's side matches one of the game's actual DB teams — mismatches are logged (`fairbet_skip_team_mismatch`) and skipped
- **NCAAB token overlap threshold tightened**: `match_game_by_names_ncaab()` now requires 2+ overlapping tokens when both names have 2+ tokens (was 1 for names with ≤2 tokens), preventing false matches on shared words like "State" (e.g., "Illinois State" no longer matches "Youngstown State")
- **Subset matching guard**: Single-token subsets (e.g., `{"state"}`) no longer qualify as subset matches — subsets must have 2+ tokens

### Documentation

- **ODDS_AND_FAIRBET.md** (NEW): Consolidated guide covering the full odds pipeline from ingestion through game matching, selection key generation, EV computation, and API consumption
- **EV_LIFECYCLE.md**: Updated Section 1 with DB team name selection keys and validation guard; added NCAAB matching and Pinnacle coverage limitations
- **DATA_SOURCES.md**: Rewrote Odds section with sync schedule, props markets, updated game matching description, credit management details
- **API.md**: Added `ev_diagnostics` to FairbetOddsResponse TypeScript interface; cross-reference to ODDS_AND_FAIRBET.md; clarified selection_key uses DB team names
- **INDEX.md**: Added ODDS_AND_FAIRBET.md as primary FairBet entry point

### Odds Sync Optimization

- **Split cadence**: `sync_mainline_odds` (every 15 min) and `sync_prop_odds` (every 60 min) run at independent intervals
- **Regions trimmed**: Default regions reduced from `us, us_ex, eu, uk` to `us, eu` (`us_ex` books are excluded from EV anyway; `uk` overlaps with `eu`)
- **3–7 AM ET quiet window**: Both odds tasks skip execution during the overnight quiet window (no games in progress)
- **`OddsSynchronizer` removed from `ScrapeRunManager`**: Odds sync is now a standalone Celery beat task, no longer triggered during manual scrape runs

### Odds Browser UI

- **OddsEntry schema expansion**: Added `market_category`, `player_name`, `description` fields to the API schema and TypeScript types
- **Tabbed cross-book view**: Game detail odds section rewritten with category tabs (Mainline, Player Props, Team Props, Alternates) and cross-book comparison tables showing all sportsbooks as columns
- **Player prop search**: Search input to filter player props by player name
- **Dynamic tabs**: Only categories with data are shown; defaults to Mainline

### Tweet Mapper Floor Constraint

- **4 AM ET sports day boundary**: `get_game_window()` now floors `window_end` at 4:00 AM ET on the day after the game date, ensuring the collection window extends to the end of the sports day

### Test Fixes

- **`test_run_manager.py` / `test_services_run_manager.py`**: Removed all `OddsSynchronizer` patches and obsolete odds-specific tests to match the refactored `ScrapeRunManager`
- **`test_tweet_mapper.py`**: Updated 5 `TestGetGameWindow` expected values to account for the 4 AM ET floor constraint

---

## [2026-02-17]

### Live Boxscore Polling

- **Live boxscore ingestion**: New polling task fetches boxscores for in-progress games every 5 minutes alongside live PBP
- **`last_boxscore_at` column**: New timestamp on `sports_games` tracks when boxscore data was last refreshed
- **Active game service**: New `services/active_games.py` module centralizes live game detection for polling tasks

### NCAAB Team Normalization & Matching

- **NCAAB name normalization**: New `normalization/ncaab_teams.py` with 28 additional alias mappings for NCAAB team matching
- **Odds matching improvements**: `persistence/odds_matching.py` enhanced with fuzzy matching for NCAAB teams where canonical names differ from odds API names
- **Missing NCAAB teams seeded**: 7 HBCU/mid-major teams added to `sports_teams` (included in baseline seed data)
- **NCAAB social handles fixed**: Corrected X handles for 66 NCAAB teams (8 NULL + 58 stale)
- **Alembic squash**: Replaced 51 broken migration files (cycles, duplicates) with clean baseline + seed + linear chain

### Legacy Code Cleanup

- **Dead timeline constants removed**: `NBA_PREGAME_REAL_SECONDS`, `NBA_OVERTIME_PADDING_SECONDS`, `POSTGAME_WINDOW_HOURS`, `LEAGUE_SEGMENTS` deleted from `timeline_types.py`
- **Dead feature flags removed**: `ENABLE_AI_SOCIAL_ROLES`, `ENABLE_AI_SEGMENT_ENRICHMENT`, `ENABLE_AI_SUMMARY`, `NEXT_PUBLIC_ENABLE_INLINE_X_VIDEO` removed from `docker-compose.yml` and `.env`
- **API client hardened**: `client.ts` timeout made private, silent `{} as T` fallback replaced with explicit error throw

### Documentation

- **Accuracy fixes**: Fixed migration path in ARCHITECTURE.md, updated live PBP info in DATA_SOURCES.md, removed stale nginx reference in OPERATOR_RUNBOOK.md
- **Missing env vars documented**: Added `OPENAI_MODEL_CLASSIFICATION` and `OPENAI_MODEL_SUMMARY` to INFRA.md
- **Phase N terminology removed**: Cleaned "Phase 5"/"Phase 1"/"Phase 4" labels from gameflow README.md

---

## [2026-02-14]

### FairBet EV Framework

- **EV eligibility gating**: New `evaluate_ev_eligibility()` function with 4-check pipeline: strategy exists, sharp book present, freshness, minimum qualifying books
- **EV strategy config**: `ev_config.py` maps `(league, market_category)` → strategy with confidence tiers (high/medium/low), staleness limits, and minimum book thresholds
- **Book exclusion**: 20 offshore/promo/irrelevant books excluded at SQL level via `EXCLUDED_BOOKS`; remaining ~17 included books participate in EV calculation
- **Confidence tiers**: High (NBA/NHL mainlines), Medium (NCAAB mainlines, team props), Low (player props, alternates); player props can never be High
- **Pregame-only filter**: FairBet odds endpoint restricted to pregame games (`game_start > now`) — removed stale 4-hour live cutoff
- **Odds model expansion**: Added `market_category`, `has_fair`, `player_name`, `selection_key` columns to odds tables; new prop market support

### FairBet UI Fixes

- **CSS stacking context fix**: Replaced `filter: brightness(0.96)` hover with `background: linear-gradient()` to prevent derivation popover from being clipped by adjacent cards

### Legacy Code Cleanup

- **Deleted one-shot scripts**: `migrate_sports_data.sh`, `_team_color_data.py`, `extract_team_colors.py`, `map_ncaab_teams.py`, `harvest_cbb_abbreviations.py`
- **Cleaned legacy comments**: Removed "Phase N" labels from FlowSection.tsx, fixed misleading "Safe fallback" comments in render_blocks.py, cleaned StatusBadge.module.css comment

### Documentation

- **EV_LIFECYCLE.md**: End-to-end EV computation walkthrough from ingestion to annotation
- **EV_INFRASTRUCTURE_REVIEW.md**: Codebase review documenting assumptions, gaps, and open questions

---

## [2026-02-13]

### Mini Box Score Fix

- **Per-team score deltas**: `game_stats_helpers.py` now uses per-team score deltas instead of combined total to prevent cross-team point inflation (e.g., a player getting credited with 20 PTS when actual was 13)
- **`_compute_single_team_delta()`**: New helper that isolates home vs away scoring, with team-abbreviation matching as a tiebreaker when both scores change simultaneously
- **Score=0 fix**: Replaced `event.get("home_score") or prev_home` with explicit `None` check so a legitimate score of 0 is not treated as missing

### Legacy Code Cleanup

- **Position-based tweet system removed**: Deleted `TweetPosition` enum, `classify_tweet_position()`, `_select_with_distribution()`, `_compute_distribution()`, `enforce_embedded_caps()`, `_find_target_block()` — all dead code replaced by temporal block matching
- **Fallback name matching removed**: `game_stats_helpers.py` no longer guesses team abbreviation via player-name substring matching; players without abbreviations are skipped
- **`TYPE_CHECKING` block removed**: Cleaned empty import guard from `ncaab_boxscore.py`
- **Legacy vocabulary cleaned**: Removed "Phase N" labels from module docstrings, renamed "Old format"/"New format" to "Flat format"/"Nested format" in `ncaab_helpers.py`

### Documentation Consolidation

- **GAMEFLOW_CONTRACT.md**: Updated embedded tweet selection criteria from "early, mid, late" position distribution to temporal matching
- **CHANGELOG.md**: Removed "(Phase N)" labels from section headers
- **API.md**: Updated with enhanced scraper and team/player stats endpoints

---

## [2026-02-11]

### Team Color Management

- **`PATCH /teams/{id}/colors`**: New endpoint to update team light/dark hex colors
- **`colorLightHex`/`colorDarkHex`** on `TeamSummary` and `TeamDetail` responses
- **`get_matchup_colors()`**: Server-side color selection with perceptual distance fallback (`team_colors.py`)

### Server-Side Computation

- **Derived metrics**: 40+ metrics computed server-side (`derived_metrics.py`), returned on `GameSummary.derivedMetrics` and `GameDetailResponse.derivedMetrics`
- **Period labels**: `periodLabel` and `timeLabel` on `PlayEntry` — league-aware ("Q1", "1st Half", "P2") via `period_labels.py`
- **Play tiers**: `tier` on `PlayEntry` (1=key, 2=notable, 3=routine) and `groupedPlays` for Tier-3 collapse via `play_tiers.py`
- **Play serialization**: `teamAbbreviation` and `playerName` now included on `PlayEntry`

### Timeline Odds Integration

- **`odds_events.py`** (NEW): Odds event processing — book selection, movement detection, event building
- **Odds in timeline**: Up to 3 pregame odds events (opening_line, closing_line, line_movement) merged into unified timeline
- **Book priority**: fanduel > draftkings > betmgm > caesars
- **Movement thresholds**: spread >= 1.0 pt, total >= 1.0 pt, moneyline >= 20 cents
- **`GET /games/{id}/timeline`**: New endpoint to retrieve persisted timeline artifacts (404 if not generated)
- **Validation updated**: C3 dedup handles odds events; W4 warning for odds missing phase

### Documentation Consolidation

- **TIMELINE_ASSEMBLY.md**: Rewritten — added odds as third source, multi-league PHASE_ORDER, updated merge pseudocode
- **TIMELINE_VALIDATION.md**: Rewritten — aligned check numbering with code (C1-C6, W1-W4), removed aspirational checks
- **API.md**: Added GET timeline endpoint, PATCH colors, PlayEntry/TimelineArtifactResponse models
- **SERVER_SIDE_MIGRATION.md** (NEW): Comprehensive 6-phase migration guide
- **INDEX.md**: Added Server-Side Migration section
- **ARCHITECTURE.md**: Updated timeline section with all modules

---

## [2026-02-09]

### NCAAB Social Scraping Enabled

- **NCAAB social enabled**: Social/X scraping now active for all three leagues (NBA, NHL, NCAAB)
- **Config flag**: `config_sports.py` NCAAB `social_enabled` flipped to `True`
- **Run manager**: NCAAB added to `_supported_social_leagues` so social runs execute instead of being silently skipped
- **Prerequisite**: NCAAB teams need active `TeamSocialAccount` rows with X handles before collection produces results

### Embedded Tweet Backfill

- **Post-generation backfill**: New pipeline endpoint `POST /pipeline/backfill-embedded-tweets` attaches social post references to flows that were generated before social scraping completed
- **Final-whistle integration**: After social Scrape #1, backfill runs automatically for the completed game
- **Daily sweep integration**: Sweep scans flows from the last 7 days for missing embedded tweets
- **Sole permitted mutation**: Backfill only sets `embedded_social_post_id` on blocks — block structure, roles, and narratives are never altered

### Game Stats Delta Validation

- **Scoring logic refactor**: `game_stats_helpers.py` delta computation rewritten with explicit validation
- **Expanded test coverage**: Comprehensive tests for delta calculation edge cases

### Odds Upsert Result Enum

- **`OddsUpsertResult` enum**: `upsert_odds` now returns `PERSISTED`, `SKIPPED_NO_MATCH`, or `SKIPPED_LIVE` instead of a boolean
- **Live game protection**: Live games explicitly skipped during odds sync to preserve pre-game closing lines

---

## [2026-02-08]

### Story to Game Flow Rename

- **Story -> Game Flow rename**: All consumer-facing "story" terminology renamed to "game flow" across API responses, documentation, and types
- **API endpoint**: `/games/{id}/story` -> `/games/{id}/flow`, response field `story` -> `flow`
- **Type renames**: `GameStoryResponse` -> `GameFlowResponse`, `StoryContent` -> `GameFlowContent`, `StoryBlock` -> `GameFlowBlock`, `StoryMoment` -> `GameFlowMoment`, `StoryPlay` -> `GameFlowPlay`
- **`embedded_tweet` -> `embeddedSocialPostId`**: Block-level social context now uses a social post ID reference (`number | null`) instead of an inline tweet object; `EmbeddedTweet` interface removed
- **camelCase mini box keys**: `delta_pts` -> `deltaPts`, `delta_reb` -> `deltaReb`, `delta_ast` -> `deltaAst`, `delta_goals` -> `deltaGoals`, `delta_assists` -> `deltaAssists`; `block_stars` -> `blockStars` on `BlockMiniBox`
- **`GamePhase` enum added**: `"pregame" | "in_game" | "postgame"` type for social post phase classification
- **`hasStory` -> `hasFlow`**, **`withStoryCount` -> `withFlowCount`** in game list responses
- **Documentation files renamed**: `STORY_CONTRACT.md` -> `GAMEFLOW_CONTRACT.md`, `STORY_PIPELINE.md` -> `GAMEFLOW_PIPELINE.md`, `PBP_STORY_ASSUMPTIONS.md` -> `PBP_GAMEFLOW_ASSUMPTIONS.md`
- Internal pipeline identifiers (`story_type`, `storyline_score`, `sports_game_stories`, `story_version`, Celery task names) remain unchanged

---

## [2026-02-06]

### Game-State-Machine & Two-Scrape Social Model

- **Game-state-machine**: Games tracked through state transitions (PREGAME → LIVE → FINAL) with polling tasks every 3-5 min
- **Two-scrape social model**: Scrape #1 on final-whistle (immediate), Scrape #2 in daily sweep (catch-up)
- **`game_social_posts` eliminated**: All social data lives in `team_social_posts` with `mapping_status` column
- **`XPostCollector` → `TeamTweetCollector`**: Simplified team-centric collection
- **Daily sweep at 4:00 AM EST**: Ingestion + truth repair + social scrape #2
- **Flow generation at 4:30/5:00/5:30 AM EST**: NBA, NHL, NCAAB respectively

### Legacy Code Cleanup

- **Removed `game_social_posts` table**: Mapping now tracked via `team_social_posts.mapping_status`
- **Removed `XPostCollector`**: Replaced by `TeamTweetCollector`
- **Removed `poll_active_social_task`**: Social collection handled by two-scrape model

---

## [2026-02-05]

### Social Collection Architecture

- **Team-centric collection**: Social scraping now collects all tweets for a team in a date range, then maps to games
- **New tables**: `team_social_posts` for raw collected tweets

### Legacy Code Cleanup

- **Removed NHL SportsRef scraper**: NHL uses official NHL API exclusively for all data
- **Simplified timeline generator**: Removed unused `build_nba_timeline()` function
- **Simplified social events**: Removed AI classification stubs (heuristics only)

---

## [2026-02-03]

### Pipeline Enhancements

- **8-stage pipeline**: Added ANALYZE_DRAMA stage between VALIDATE_MOMENTS and GROUP_BLOCKS
- **Drama-weighted block distribution**: AI identifies dramatic peak quarters and weights block allocation accordingly
- **Mini box scores per block**: Each narrative block now includes cumulative stats with segment deltas
- **Fail-fast error handling**: Removed fallback narratives; pipeline fails on errors instead of degrading silently

### NBA PBP Migration

- **NBA API for PBP**: NBA play-by-play now uses the official NBA API instead of Sports Reference
- **Schedule integration**: Games matched via NBA schedule API to obtain game IDs

---

## [2026-02-01]

### Story Compression Overhaul

- **Larger moments**: Increased from 1-5 plays to 15-50 plays per moment (70-80% reduction in moment count)
- **Richer narratives**: Expanded from 3-4 sentences to 2-3 paragraphs (6-10 sentences) per moment
- **Cumulative box scores**: Each moment now includes a running player stats snapshot
- **Smaller batches**: Reduced OpenAI batching from 15 to 5 moments per call for longer outputs
- **More explicit plays**: Increased from 2 to 5 explicitly narrated plays per moment

### Technical Changes

- `SOFT_CAP_PLAYS`: 8 → 30
- `ABSOLUTE_MAX_PLAYS`: 12 → 50
- `MIN_PLAYS_BEFORE_SOFT_CLOSE`: 5 → 15
- `MAX_EXPLICIT_PLAYS_PER_MOMENT`: 2 → 5
- `MOMENTS_PER_BATCH`: 15 → 5

---

## [2026-01-28]

### NCAAB Enhancements

- **Batch API fetching**: Reduced CBB API calls from 2 per game to 2 per date range
- **API response caching**: Added JSON caching for NCAAB and NHL API responses
- **Event type normalization**: Comprehensive NCAAB event type mapping for PBP

### Architecture

- **Block-based Game Flow Model**: Game flows are ordered lists of narrative blocks backed by moments and specific plays
- **Multi-Stage Pipeline**: NORMALIZE_PBP → GENERATE_MOMENTS → VALIDATE_MOMENTS → ANALYZE_DRAMA → GROUP_BLOCKS → RENDER_BLOCKS → VALIDATE_BLOCKS → FINALIZE_MOMENTS
- **Deterministic Segmentation**: Moment boundaries are mechanical, AI is prose-only
- **Full Traceability**: Every narrative sentence maps to specific plays

### Features

- FastAPI admin API with game flow generation endpoints
- Celery scraper workers for NBA, NHL, NCAAB data
- Next.js admin UI for data browsing and game flow generation
- Sports Reference boxscore and PBP scraping
- NHL official API integration (schedule, PBP, boxscores)
- NCAAB College Basketball Data API integration
- The Odds API integration with local JSON caching
- Social media scraping from X/Twitter team accounts
- PostgreSQL with JSONB stats storage

### Documentation

- [Game Flow Contract](gameflow/contract.md) - Authoritative game flow specification
- [Game Flow Pipeline](gameflow/pipeline.md) - Pipeline stages and implementation
