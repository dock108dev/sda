# Analytics Engine

Predictive modeling, simulation, and matchup analysis for sports data.

**Code:** `api/app/analytics/`

---

## Package Structure

| Package | Description |
|---------|-------------|
| `api/` | REST endpoints — profiles, simulations, models, ensemble config |
| `core/` | Orchestration — SimulationEngine, SimulationRunner, SimulationAnalysis |
| `datasets/` | Training data extraction — PA, pitch, and batted ball dataset builders with shared ProfileMixin for rolling profile assembly |
| `ensemble/` | Weighted probability combination from multiple providers |
| `features/` | Feature extraction pipeline with configurable feature sets |
| `inference/` | Model inference engine with in-memory artifact caching |
| `models/core/` | BaseModel interface, ModelRegistry (JSON-backed), ModelLoader |
| `models/sports/mlb/` | MLB models — plate appearance, pitch, batted ball, run expectancy, game |
| `models/sports/nba/` | NBA models — possession, game (rule-based defaults until trained) |
| `models/sports/nhl/` | NHL models — shot, game (rule-based defaults until trained) |
| `models/sports/ncaab/` | NCAAB models — possession, game (rule-based defaults until trained) |
| `probabilities/` | Provider abstraction — rule-based, ML, ensemble; ProbabilityResolver for routing |
| `services/` | AnalyticsService (API adapter), ModelService (model management) |
| `simulation/` | Pitch-level simulators (PitchSimulator, PitchLevelGameSimulator) |
| `sports/mlb/` | MLB PA-level game simulator, metrics, matchup logic; `constants.py` is the SSOT for all MLB baselines and canonical team abbreviations |
| `sports/nba/` | NBA possession-based game simulator, metrics; `constants.py` for NBA baselines |
| `sports/nhl/` | NHL shot-based game simulator (with shootout), metrics; `constants.py` for NHL baselines |
| `sports/ncaab/` | NCAAB four-factor possession simulator (with ORB mechanic), metrics; `constants.py` for NCAAB baselines |
| `training/core/` | TrainingPipeline, DatasetBuilder, ModelEvaluator |
| `training/sports/` | Sport-specific training (MLBTrainingPipeline — label extraction, record builders; stubs only for data loading) |

---

## Simulation

The simulation engine runs Monte Carlo simulations with pluggable probability sources.

### Flow

1. `SimulationEngine.run_simulation()` receives game context (teams, probability mode, iterations)
2. If `pitch_level` mode: routes to `_run_pitch_level()` (see Pitch-Level Simulation below)
3. Otherwise: `ProbabilityResolver` selects the provider based on mode (`rule_based`, `ml`, `ensemble`, `market_blend`)
4. When home/away team profiles are both present, PA probabilities are resolved separately for each team
5. Home field advantage applied via `_apply_hfa()` — sport-specific boost to home scoring probabilities
6. `SimulationRunner` invokes the sport-specific simulator N times (default 5,000–10,000)
7. If `market_blend` mode: post-simulation WP blended with devigged market line (`α × model + (1-α) × market`)
8. Results aggregated: win probabilities, average scores, score distribution, event summary, variance metrics
9. `SimulationDiagnostics` attached to result with execution metadata

### Home Field Advantage

Sport-specific HFA constants applied to home team scoring probabilities before simulation:

| Sport | Constant | Boost Applied To | Historical Home Win % |
|-------|----------|-----------------|----------------------|
| MLB | `MLB_HFA_BOOST = 0.04` | walk/single (full) + HR (half) | ~54% |
| NBA | `NBA_HFA_BOOST = 0.04` | 2pt/3pt make probability | ~58% |
| NHL | `NHL_HFA_BOOST = 0.03` | goal probability | ~54% |
| NCAAB | `NCAAB_HFA_BOOST = 0.035` | 2pt/3pt make probability | ~56% |
| NFL | `NFL_HFA_BOOST = 0.03` | touchdown/field goal probability | ~57% |

### Simulation Diagnostics

Every simulation run produces a `SimulationDiagnostics` object (`core/simulation_diagnostics.py`) that tracks exactly what ran and why:

```python
@dataclass
class ModelInfo:
    model_id: str
    version: int
    trained_at: str | None = None
    metrics: dict[str, float]        # accuracy, brier_score, etc.

@dataclass
class SimulationDiagnostics:
    requested_mode: str              # what the user asked for
    executed_mode: str               # what actually ran
    model_info: ModelInfo | None
    warnings: list[str]              # validation issues, etc.
```

The diagnostics are surfaced in the API response as `simulation_info` and in the frontend as the `SimulationInfoBanner` component (mode badge, model version/accuracy). There is no silent fallback — ML failures raise directly.

### Profile Freshness

`get_team_rolling_profile()` returns a `ProfileResult` dataclass (`services/profile_service.py`) with freshness metadata. This function supports all sports (MLB, NBA, NHL, NCAAB), using sport-specific advanced stats tables to build each team's rolling profile:

```python
@dataclass
class ProfileResult:
    metrics: dict[str, float]
    games_used: int
    date_range: tuple[str, str]      # (oldest_game_date, newest_game_date)
    season_breakdown: dict[int, int] # year → game count
```

Surfaced in the API response as `profile_meta.data_freshness` with per-team game counts and date ranges. The frontend shows a stale-data warning when the newest game is older than 3 days.

### MLB Game Simulation (PA-Level, Lineup-Aware)

Each game simulation runs 9+ innings. Each half-inning simulates plate appearances until 3 outs.

**Team-level mode:** All PAs use a single probability distribution per team.

**Lineup-aware mode (default in batch sims):** Each of 9 batters has individual matchup probabilities vs the opposing starter and bullpen. Starter pitches through ~6 innings, then switches to bullpen weights.

- For completed games: batting order reconstructed from PBP (first 9 unique batters)
- For future games: most recent actual lineup + probable pitcher from MLB Stats API
- Fallback: team-level probabilities when lineup data unavailable

**Key files:**
- `sports/mlb/game_simulator.py` — `simulate_game()` + `simulate_game_with_lineups()`
- `services/lineup_reconstruction.py` — extract batting order from PBP
- `services/lineup_weights.py` — per-batter weight building (shared SSOT for pitcher regression + bullpen metrics)
- `services/lineup_fetcher.py` — probable pitcher from MLB Stats API + recent lineup proxy
- `sports/mlb/matchup.py` — `batter_vs_pitcher()` probability computation

### NBA Game Simulation (Possession-Level, Rotation-Aware)

Each game simulates ~100 possessions per team across 4 quarters + overtime.

**Team-level mode:** All possessions use a single probability distribution per team.

**Rotation-aware mode (default in batch sims):** Each possession is randomly assigned to the starter unit (top 5 by minutes, ~70%) or bench unit (~30%). Each unit has its own probability weights derived from individual player profiles weighted by usage rate. OT uses starters only.

- Starters identified from `NBAPlayerAdvancedStats.minutes` (top 5 per team)
- Player profiles: rolling averages of off_rating, ts_pct, efg_pct, usg_pct, shot type splits
- Unit probabilities adjusted for opposing team's defensive rating

**Key files:** `sports/nba/game_simulator.py`, `services/nba_rotation_service.py`, `services/nba_player_profiles.py`, `services/nba_rotation_weights.py`

### NHL Game Simulation (Shot-Level, Rotation-Aware)

Each game simulates ~30 shot attempts per team across 3 periods + OT + shootout.

**Rotation-aware mode:** Each shot is randomly assigned to top-line (top 10 skaters by TOI, ~65%) or depth unit (~35%). Starting goalie's save% adjusts the opposing team's goal probability. OT uses top-line only. Shootout uses blended team/league probability.

- Top-line identified from `NHLSkaterAdvancedStats.toi_minutes` (enriched from boxscore cross-reference)
- Starting goalie identified from `NHLGoalieAdvancedStats` (most shots faced)
- Per-skater profiles: xGoals, shooting%, goals_per_60, shots_per_60

**Key files:** `sports/nhl/game_simulator.py`, `services/nhl_rotation_service.py`, `services/nhl_player_profiles.py`, `services/nhl_rotation_weights.py`

### NCAAB Game Simulation (Four-Factor Possession, Rotation-Aware)

Each game simulates ~68 possessions per team across 2 halves with offensive rebound recursion.

**Rotation-aware mode:** Same starter/bench unit model as NBA. Additionally, each unit has its own ORB% and FT% (NCAAB-specific). On missed shots, offensive rebound chance uses the active unit's ORB% (max 3 consecutive ORBs).

- Starters identified from `NCAABPlayerAdvancedStats.minutes` (123K/133K rows have minutes data)
- Player profiles: off_rating, usg_pct, ts_pct, efg_pct, volume stats

**Key files:** `sports/ncaab/game_simulator.py`, `services/ncaab_rotation_service.py`, `services/ncaab_player_profiles.py`, `services/ncaab_rotation_weights.py`

### NFL Game Simulation (Drive-Based)

Each game simulates ~12 drives per team per half. Each drive resolves as one of: touchdown, field goal, punt, turnover, or turnover on downs.

**Drive outcome probabilities** derived from:
- Team offensive EPA/play + success rate + CPOE (from nflverse `nfl_game_advanced_stats`)
- Opposing team's defensive pressure: sacks/game, TFL/game, QB hits/game, turnovers forced/game (from ESPN boxscore JSONB)
- Special teams: FG success rate from kicking stats

After touchdown: extra point attempt (~94%) or rare 2-point conversion. OT uses modified sudden death (both teams get at least 1 drive).

**Key files:** `sports/nfl/game_simulator.py`, `sports/nfl/constants.py`, `services/nfl_drive_profiles.py`, `services/nfl_drive_weights.py`

### Rotation/Lineup Dispatch in Batch Sims

The batch simulation orchestrator (`batch_sim_tasks.py`) is split into focused modules:

| Module | Purpose |
|--------|---------|
| `batch_sim_tasks.py` | Celery task entry point, job lifecycle, simulation orchestration loop |
| `_batch_sim_weights.py` | Sport-specific rotation/lineup weight builders (one per sport) |
| `_batch_sim_helpers.py` | Stats converters, rolling profile builder, lineup metadata serializer |
| `_batch_sim_enrichment.py` | Closing/current line analysis, batch summary, prediction outcome persistence |

Each sport dispatches to its own weight builder:

| Sport | Builder | Data Source |
|-------|---------|-------------|
| MLB | `try_build_lineup_weights()` | Consensus lineup (last 7 games) + rotation prediction + pitcher profiles |
| NBA | `try_build_nba_rotation_weights()` | Player minutes + advanced stats |
| NCAAB | `try_build_ncaab_rotation_weights()` | Player minutes + advanced stats |
| NHL | `try_build_nhl_rotation_weights()` | Skater TOI + goalie stats |
| NFL | `try_build_nfl_drive_weights()` | Team EPA + defensive boxscore |

All sports fall back to team-level simulation when rotation/lineup data is unavailable.

### MLB Rotation & Lineup Prediction (Future Games)

For scheduled games where actual data doesn't exist yet:

**Starter prediction** (`mlb_rotation_service.py`) uses a fallback chain:
1. MLB Stats API probable pitcher (reliable 1-2 days out)
2. Rotation cycle projection — identifies the 5/6-man rotation from recent starts, projects forward by counting game days
3. OpenAI tiebreaker — for ambiguous rotations (< 4 clear members)

**Lineup prediction** (`lineup_fetcher.fetch_consensus_lineup()`) analyses the last 7 completed games:
- Frequency analysis identifies the 9 most common starters
- Batting order consensus uses mode position per player
- Falls back to single most recent game if < 3 games have data

### Line Analysis Enrichment

After all simulations complete, `_batch_sim_enrichment.enrich_with_closing_lines()` adds market comparison data:
- **Final games**: Uses Pinnacle closing lines from the `ClosingLine` table
- **Future games**: Uses current market lines from `FairbetGameOddsWork`
- Computes: devigged market probability (Shin method), model edge, model fair line, EV%

### Player Profile Services

Each sport has its own player profile service that builds rolling averages from per-game advanced stats:

| Sport | Service | Data Source | Key Metrics |
|-------|---------|-------------|-------------|
| MLB | `services/mlb_player_profiles.py` | `MLBPlayerAdvancedStats` | Contact rate, whiff rate, exit velo, barrel% |
| MLB (pitchers) | `services/profile_service.py` | `MLBPitcherGameStats` + boxscore JSONB | K rate, BB rate, contact/power suppression |
| NBA | `services/nba_player_profiles.py` | `NBAPlayerAdvancedStats` | Off/def rating, TS%, EFG%, USG%, shot splits |
| NHL | `services/nhl_player_profiles.py` | `NHLSkaterAdvancedStats` | xGoals, shooting%, goals_per_60, TOI |
| NCAAB | `services/ncaab_player_profiles.py` | `NCAABPlayerAdvancedStats` | Off rating, USG%, TS%, EFG%, volume stats |
| NFL | `services/nfl_drive_profiles.py` | `NFLGameAdvancedStats` + boxscore JSONB | EPA/play, success rate, CPOE, sack rate, FG% |

**Shared patterns:**
- All use rolling windows (default 15-30 games)
- Players with fewer than 3 games use league-average fallback
- MLB blends sparse batter data with team average (weight = games/5)
- Pitcher profiles are regressed toward league average based on avg IP (shared in `services/lineup_weights.py`)
- Pitcher and batter profiles query by `player_external_ref` only (no team_id filter), so traded players retain full cross-team history

### Event Summary & Sanity Analysis

When event data is present in simulation results, `SimulationRunner.aggregate_results()` computes an `event_summary` with per-team PA rates and game-shape metrics:

```python
"event_summary": {
    "home": {
        "avg_pa": 37.2, "avg_hits": 8.4, "avg_hr": 1.1,
        "avg_bb": 3.2, "avg_k": 8.7, "avg_runs": 4.3,
        "pa_rates": {"k_pct": 0.234, "bb_pct": 0.086, "hr_pct": 0.030, ...}
    },
    "away": { ... },
    "game": {
        "avg_total_runs": 8.6, "median_total_runs": 8,
        "extra_innings_pct": 0.082, "shutout_pct": 0.043, "one_run_game_pct": 0.187,
    }
}
```

**Sanity warnings** automatically flag anomalous results via `check_simulation_sanity()` and `check_batch_sanity()` in `core/simulation_analysis.py`:

- Avg runs per team > 15 or < 1
- Avg PA per team outside 30–50
- Avg HR per team > 5
- K% outside 10–40%, BB% outside 2–20%
- Extra innings rate > 25%
- All games in a batch with WP between 49–51% (matchup flatness)

Warnings are included in both the `/simulate` response (`simulation_info.sanity_warnings`) and batch sim results (`warnings` array).

### Pitch-Level Simulation

Alternative simulation path using `PitchLevelGameSimulator`. Instead of sampling PA outcomes directly, it simulates individual pitches within each plate appearance — producing realistic count distributions, walk/strikeout rates, and pitch-level analytics.

**How it works:**

1. `SimulationEngine._run_pitch_level()` resolves per-team profiles from the game context
2. Profiles are mapped to pitch simulator feature keys via `_profile_to_pitch_features()` — home batting is paired with away pitching and vice versa, producing differentiated team features
3. If trained `pitch` and `batted_ball` models are active in the registry, they are loaded; otherwise rule-based defaults are used
4. `PitchLevelGameSimulator` is passed to `SimulationRunner` (same aggregation as PA-level)
5. Each game simulates 9+ innings, each half-inning pitch-by-pitch:
   - `MLBPitchOutcomeModel` predicts ball/called_strike/swinging_strike/foul/in_play
   - On ball-in-play, `MLBBattedBallModel` predicts out/single/double/triple/home_run
   - Count state (balls/strikes) updates between pitches
6. Event diagnostics (`home_events`/`away_events`, `innings_played`, `total_pitches`) are returned per game, enabling full `event_summary` aggregation

**Per-team differentiation:** Each team gets distinct feature dicts. The home team's batting profile is evaluated against the away team's pitching profile, producing different pitch/batted-ball probabilities for each side. This prevents the 50/50 WP compression that occurs when both teams share identical probabilities.

**Trained model support:** When trained `pitch` and `batted_ball` models are activated in the registry, `_load_pitch_models()` wraps them and injects them into the simulator. Rule-based defaults serve as the fallback.

Does not support lineup-aware mode.

**Key files:**
- `simulation/mlb/pitch_simulator.py` — `PitchSimulator` (per-PA) and `PitchLevelGameSimulator` (per-game)
- `core/simulation_engine.py` — `_run_pitch_level()`, `_profile_to_pitch_features()`, `_load_pitch_models()`
- `models/sports/mlb/pitch_model.py` — pitch outcome model (rule-based + trained)
- `models/sports/mlb/batted_ball_model.py` — batted ball outcome model (rule-based + trained)

---

## Probability Providers

Five probability sources, selected via `probability_mode`:

| Provider | Description |
|----------|-------------|
| **RuleBasedProvider** | League-average defaults adjusted by batter/pitcher features. |
| **MLProvider** | Loads active trained model from registry, builds features, runs inference. |
| **EnsembleProvider** | Weighted average of rule-based and ML predictions (configurable weights). |
| **MarketBlend** | Runs ML simulation internally, then blends game-level WP with devigged market lines: `final = α × model + (1-α) × market`. Alpha is configurable (default 0.3). |
| **Pitch-level** | Implicit — when mode is `pitch_level`, SimulationEngine routes to PitchLevelGameSimulator. |

**No silent fallback.** If the requested provider fails (missing artifact, feature mismatch, inference error), the error propagates directly — there is no automatic degradation to a different provider.

**Baseline anchoring.** ML model outputs are clamped via `anchor_to_baseline()` so each event probability stays within 25% of the league-average baseline. This prevents poorly-calibrated models from producing absurd simulations (e.g., 60% hit rate → 30 runs/game) while preserving meaningful team differentiation. Well-calibrated models pass through nearly unchanged.

**XGBoost compatibility.** XGBoost requires integer-encoded labels. The training pipeline wraps XGBoost models in `_XGBStringClassesWrapper` which handles label encoding during `fit()` and maps classes back to string names at `predict()` / `predict_proba()` time. The wrapper serializes transparently via joblib.

---

## Model Registry & Inference

### Registry

JSON-backed registry at `models/registry/registry.json`. Organized by sport + model_type.

- One active model per sport/model_type pair
- `register_model()` — add model with artifact path (no auto-activation)
- `activate_model()` — set active model (explicit API call required)
- `list_models()` — filter by sport/type

### Built-in Models

| Key | Class |
|-----|-------|
| `(mlb, plate_appearance)` | MLBPlateAppearanceModel |
| `(mlb, game)` | MLBGameModel |
| `(mlb, pitch)` | MLBPitchOutcomeModel |
| `(mlb, batted_ball)` | MLBBattedBallModel |
| `(mlb, run_expectancy)` | MLBRunExpectancyModel |

### Inference Flow

1. `ModelInferenceEngine.predict_proba(sport, model_type, profiles, model_id=...)` called
2. If `model_id` is provided, load that specific model via `get_model_info_by_id()`; otherwise check registry for the active model with auto-reload detection
3. `InferenceCache` loads artifact via joblib (or returns cached)
4. `FeatureBuilder` extracts features from profiles
5. Model's `predict_proba(features)` returns probability dict

The `model_id` parameter threads through the entire stack: API request → `SimulationEngine` → `ProbabilityResolver` → `MLProvider` → `ModelInferenceEngine`. This allows testing any registered model without activating it globally.

### Model Status

`ModelInferenceEngine.get_model_status(sport, model_type)` returns structured info about model availability:

```python
{
    "available": bool,
    "model_id": str | None,
    "version": int | None,
    "trained_at": str | None,
    "metrics": dict,
    "reason": str | None     # e.g., "no_active_model" when unavailable
}
```

Used by `ProbabilityResolver` to populate `SimulationDiagnostics.model_info`.

---

## Feature Pipeline

Sport-agnostic `FeatureBuilder` routes to sport-specific builders. Features are configurable via DB-backed feature loadouts.

### Shared Feature Infrastructure

All sport-specific feature builders use `build_features_from_spec()` from `feature_vector.py` — a single implementation that converts `(feature_name, source_entity, source_key)` specs into normalized `FeatureVector` objects. MLB has its own `_build_from_spec()` with additional rate-stat clamping logic.

### MLB Features

**Game-level features (92 total):**
- Home team (30) + Away team (30): batting composites, plate discipline, quality of contact, raw counts, derived ratios
- Starter pitcher (10): `home_starter_k_rate`, `home_starter_bb_rate`, `home_starter_era`, `home_starter_whip`, `home_starter_avg_ip` (× 2 sides)
- Market probability (2): `market_home_wp`, `market_away_wp` (devigged Pinnacle closing lines)

**Plate-appearance features (28 total):**
- Batter (15): contact_rate, power_index, barrel_rate, hard_hit_rate, swing_rate, whiff_rate, avg_exit_velocity, expected_slug, plate discipline percentages and ratios
- Pitcher (13): team-level proxy for the same metrics

### NBA Features (22 total)
- Home (10) + Away (10): off_rating, def_rating, pace, efg_pct, ts_pct, tov_pct, orb_pct, ft_rate, fg3_pct, ast_pct
- Market probability (2): market_home_wp, market_away_wp

### NHL Features (16 total)
- Home (7) + Away (7): xgoals_for, xgoals_against, corsi_pct, fenwick_pct, shooting_pct, save_pct, pdo
- Market probability (2): market_home_wp, market_away_wp

### NCAAB Features (24 total)
- Home (11) + Away (11): off/def four factors (efg_pct, tov_pct, orb_pct, ft_rate × off/def), pace, ratings
- Market probability (2): market_home_wp, market_away_wp

### NFL Features (26 total)
- Home (12) + Away (12): epa_per_play, pass_epa, rush_epa, total_epa, total_wpa, success_rate, pass/rush_success_rate, explosive_play_rate, avg_cpoe, avg_air_yards, avg_yac
- Market probability (2): market_home_wp, market_away_wp

Feature names are prefixed with `home_` or `away_` (e.g., `home_contact_rate`, `away_epa_per_play`).

### Feature Configuration

Feature loadouts are stored in the `analytics_feature_configs` database table. Each loadout has a name, sport, model type, and a JSONB array of features — each with `name`, `enabled` (bool), and `weight` (float). Loadouts are managed via the Admin UI models page or the `/api/analytics/feature-config*` CRUD endpoints.

---

## Training Pipeline

End-to-end flow: data → features → train → evaluate → register. Training runs asynchronously via a Celery task (`train_analytics_model`) and is tracked in the `analytics_training_jobs` table.

### Steps

1. `POST /api/analytics/train` creates an `AnalyticsTrainingJob` record and dispatches the Celery task
2. `_execute_training()` converts the DB-backed `AnalyticsFeatureConfig` (JSONB array of `{name, enabled, weight}`) into a `{feat_name: {enabled, weight}}` dict and passes it through the pipeline
3. `load_training_data()` — handled by `app.tasks._training_data` (the SSOT for DB-backed training data loading):
   - **Game model (all sports):** queries sport-specific advanced stats (e.g., `MLBGameAdvancedStats`, `NBAGameAdvancedStats`) + `SportsGame` for games in the date range, builds rolling home/away team profiles. MLB also includes starter pitcher profiles and market probability from closing lines. NBA, NHL, NCAAB, and NFL include market probability.
   - **PA model (MLB only):** queries `MLBPlayerAdvancedStats` for player stats, builds rolling batter profiles paired with opposing team profiles, derives PA outcome labels from Statcast metrics
4. `build_dataset()` — `DatasetBuilder` → `FeatureBuilder.build_features(config=...)` → `_apply_config()` filters disabled features and applies weights from the linked loadout
5. `train_test_split()` — sklearn split (configurable, default 80/20)
6. `train_model()` — fits sklearn model (gradient_boosting default; also random_forest, xgboost)
7. `evaluate_model()` — accuracy, precision, recall, F1, Brier score
8. `save_artifact()` — serializes to `{sport}/artifacts/{model_id}.pkl` via joblib
9. Register in model registry; update job record with metrics and artifact path

### Model Types

| Model Type | Dataset Builder | Label Function | Default Classifier |
|------------|----------------|----------------|--------------------|
| `game` | `_training_data.py` (team rolling profiles) | `game_label_fn()` — 1=home win, 0=away | GradientBoostingClassifier |
| `plate_appearance` | `MLBPADatasetBuilder` (PBP events + profiles) | `pa_label_fn()` — canonical PA outcome | GradientBoostingClassifier |
| `player_plate_appearance` | `MLBPADatasetBuilder` (player-level) | `pa_label_fn()` | GradientBoostingClassifier |
| `pitch` | `MLBPitchDatasetBuilder` (pitch events from `playEvents`) | `pitch_label_fn()` — ball/called_strike/swinging_strike/foul/in_play | RandomForestClassifier (balanced) |
| `batted_ball` | `MLBBattedBallDatasetBuilder` (hit data from BIP plays) | `batted_ball_label_fn()` — out/single/double/triple/home_run | RandomForestClassifier (balanced) |

### Dataset Builders

All dataset builders live in `analytics/datasets/` and share profile-loading logic via `ProfileMixin`:

- **`MLBPADatasetBuilder`** — Extracts one row per plate appearance from `SportsGamePlay.raw_data`. Labels derived from `result.event` via `mlb_pa_labeler.py`. Includes point-in-time batter/pitcher profiles with optional boxscore history merging and team fielding context.
- **`MLBPitchDatasetBuilder`** — Extracts one row per pitch from `raw_data["playEvents"]` where `isPitch == True`. Labels derived from `details.code` via `mlb_pitch_labeler.py` (e.g., `B` → ball, `S` → swinging_strike, `X` → in_play). Includes count state, pitch zone, and speed.
- **`MLBBattedBallDatasetBuilder`** — Extracts one row per ball-in-play from plays with Statcast `hitData`. Includes exit velocity, launch angle, and spray angle (derived from hit coordinates via `atan2`). Rows without `launchSpeed` are skipped.

All three builders use rolling point-in-time profiles (batter + pitcher) to prevent data leakage. Profile loading is centralized in `_profile_mixin.py`.

### Label Extraction (MLB)

Label functions live in `MLBTrainingPipeline` (`training/sports/mlb_training.py`):

- `pa_label_fn()` — PA outcome (strikeout, walk_or_hbp, single, double, triple, home_run, ball_in_play_out)
- `game_label_fn()` — game outcome (1 = home win, 0 = away win)
- `pitch_label_fn()` — pitch outcome (ball, called_strike, swinging_strike, foul, in_play)
- `batted_ball_label_fn()` — batted ball outcome (out, single, double, triple, home_run)

### Constants SSOT

All MLB baseline constants, default event probabilities, and feature defaults are centralized in `app.analytics.sports.mlb.constants`. Consumer modules (`matchup.py`, `metrics.py`, `game_simulator.py`, `mlb_features.py`, `probability_provider.py`, `pa_model.py`, `mlb_training.py`) import from this single source.

---

## MLB Models

### Plate Appearance Model

Predicts event probabilities for a plate appearance.

- **Input:** batter/pitcher features (contact_rate, power_index, etc.)
- **Output:** probabilities for strikeout, out, walk, single, double, triple, home_run
- **Defaults:** strikeout 0.22, out 0.46, walk 0.08, single 0.15, double 0.05, triple 0.01, home_run 0.03

### Pitch Outcome Model

Predicts pitch-level outcomes.

- **Input:** pitcher K-rate, batter contact rate, count (balls/strikes)
- **Output:** probabilities for ball, called_strike, swinging_strike, foul, in_play
- **Defaults:** ball 0.35, called_strike 0.17, swinging_strike 0.11, foul 0.18, in_play 0.19
- **Adjustments:** count state (3-ball counts shift toward ball/in_play), batter swing tendencies, pitcher K-tendency

### Batted Ball Model

Predicts batted ball outcomes from Statcast-style inputs.

- **Input:** exit velocity, launch angle, spray angle, batter barrel rate, hard hit rate, pitcher hard hit allowed, park factor, power index
- **Output:** probabilities for out, single, double, triple, home_run
- **Defaults:** out 0.72, single 0.15, double 0.07, triple 0.01, home_run 0.05

### Run Expectancy Model

Predicts expected runs for a base/out state.

- **Input:** base_state (0–7 encoded), outs (0–2), inning, score_diff, batter_quality, pitcher_quality
- **Output:** expected runs (float)
- **Static RE matrix:** 24 precalculated (base_state, outs) → expected runs mappings
- **Adjustments:** batter_quality 0.8–1.2x multiplier, pitcher_quality inverse

### Game Model

Predicts game-level outcomes.

- **Input:** home/away team features (contact_rate, power_index, expected_slug, barrel_rate, hard_hit_rate)
- **Output:** home_win_probability, expected_home_score, expected_away_score
- **Default home WP:** 0.54 (home advantage)

---

## Ensemble System

Combines predictions from multiple providers using configurable weights.

### Default Configurations

| Sport/Model | Rule-Based Weight | ML Weight |
|-------------|-------------------|-----------|
| MLB plate_appearance | 0.4 | 0.6 |
| MLB game | 0.5 | 0.5 |

### Algorithm

1. Normalize weights to sum to 1.0
2. Collect all event keys from all providers
3. Weighted sum per event across providers
4. Normalize result to sum to 1.0

Configurations are adjustable at runtime via the `/api/analytics/ensemble-config` endpoint.

---

## API Endpoints

All endpoints prefixed with `/api/analytics`.

### Teams & Profiles

| Method | Path | Description |
|--------|------|-------------|
| GET | `/team-profile` | Team rolling profile with league baselines (for comparison UI) |
| GET | `/{sport}/teams` | List teams per sport with `games_with_stats` count (SSOT) |
| GET | `/mlb-teams` | Thin delegate to `/{sport}/teams?sport=mlb` (kept for the web client's `listMLBTeams`) |
| GET | `/mlb-roster` | Team roster (recent batters + pitchers) for lineup selection |
| GET | `/mlb-data-coverage` | Data family readiness status (PA, Pitch, Fielding) |

### Simulation

| Method | Path | Description |
|--------|------|-------------|
| POST | `/simulate` | Monte Carlo sim. Supports optional `model_id` to test a specific model (else uses active model). Response includes `simulation_info` (diagnostics + sanity warnings), `event_summary` (PA rates, game shape), `predictions`, `profile_meta` with edge analysis data |
| POST | `/batch-simulate` | Async batch simulation over upcoming games (Celery task). Supports optional `model_id` to test a specific model. When `model_id` or `probability_mode=ml` is set, routes through the ML pipeline instead of rule-based profile conversion |
| GET | `/batch-simulate-jobs` | List batch simulation jobs |
| GET | `/batch-simulate-job/{id}` | Get batch simulation job details |

### Simulator (Downstream Apps)

Separate router at `/api/simulator` — simplified, downstream-friendly interface. Always uses ML probability mode.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/simulator/{sport}/teams` | List teams (SSOT — works for `mlb`, `nba`, `nhl`, `ncaab`) |
| POST | `/api/simulator/{sport}` | Run a sim for any supported sport |
| POST | `/api/simulator/mlb` | MLB-specific sim with optional lineup-aware fields (`home_lineup`, `away_lineup`, `home_starter`, etc.) |

See [API — Simulator](api.md#simulator) for full request/response documentation. The Monte Carlo loop is offloaded to a worker thread (`asyncio.to_thread`) so concurrent requests don't serialize on a single ASGI worker.

### Experiments & Replay

| Method | Path | Description |
|--------|------|-------------|
| POST | `/experiments` | Create experiment suite (parameter sweep across algorithms, windows, splits, loadouts, probability modes, blend alphas) |
| GET | `/experiments` | List experiment suites |
| GET | `/experiments/{id}` | Suite detail with variant leaderboard |
| POST | `/experiments/{id}/promote/{variant_id}` | Activate winning variant's model |
| POST | `/experiments/{id}/cancel` | Cancel a running experiment |
| DELETE | `/experiments/{id}` | Delete suite and all variants |
| DELETE | `/experiments/{id}/variant/{variant_id}` | Delete single variant |
| POST | `/replay` | Start historical replay job (evaluate model on past games) |
| GET | `/replay-jobs` | List replay jobs |

### Prediction Outcomes & Calibration

| Method | Path | Description |
|--------|------|-------------|
| POST | `/record-outcomes` | Trigger auto-recording of outcomes for finalized games |
| GET | `/prediction-outcomes` | List prediction outcomes (filter by sport/status) |
| GET | `/calibration-report` | Aggregate calibration metrics (Brier, accuracy, bias) |

### Degradation Alerts

| Method | Path | Description |
|--------|------|-------------|
| POST | `/degradation-check` | Trigger model degradation analysis |
| GET | `/degradation-alerts` | List degradation alerts |
| POST | `/degradation-alerts/{id}/acknowledge` | Acknowledge an alert |

### Model Registry

| Method | Path | Description |
|--------|------|-------------|
| GET | `/models` | List models from DB training jobs (filter by sport/type, sort by metric) |
| GET | `/models/details` | Full model details by ID (DB-backed, falls back to file registry) |
| GET | `/models/compare` | Compare metrics across model versions |
| POST | `/models/activate` | Activate a model (auto-registers from DB if needed, clears inference cache) |
| GET | `/models/active` | Get active model for sport/type |
| GET | `/model-metrics` | Model metrics |

### Model Inference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/model-predict` | Run prediction with profiles |
| GET | `/model-predict` | Sample prediction with empty profiles |

### Feature Loadouts (DB-Backed)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/feature-configs` | List all loadouts (filter by sport/model_type) |
| GET | `/feature-config/{id}` | Get loadout by ID |
| POST | `/feature-config` | Create new loadout |
| PUT | `/feature-config/{id}` | Update loadout |
| DELETE | `/feature-config/{id}` | Delete loadout |
| POST | `/feature-config/{id}/clone` | Clone loadout |
| GET | `/available-features` | List available features with descriptions and DB coverage |

### Training Pipeline

| Method | Path | Description |
|--------|------|-------------|
| POST | `/train` | Start async training job (Celery task) |
| GET | `/training-jobs` | List training jobs (filter by sport/status) |
| GET | `/training-job/{id}` | Get training job details |
| POST | `/training-job/{id}/cancel` | Cancel a pending/queued/running training job |

### Ensemble Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ensemble-config` | Get ensemble config for sport/model |
| GET | `/ensemble-configs` | List all ensemble configs |
| POST | `/ensemble-config` | Update ensemble weights |

### Backtesting

| Method | Path | Description |
|--------|------|-------------|
| POST | `/backtest` | Start async backtest job (Celery task) |
| GET | `/backtest-jobs` | List backtest jobs |
| GET | `/backtest-job/{id}` | Get backtest job details |

### Model Odds (MLB)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/model-odds/mlb` | Full model-odds decision framework per MLB game (see [Model Odds Pipeline](#model-odds-pipeline) below) |

---

## Model Odds Pipeline

Bridges the MLB simulation engine with market data to produce calibrated probabilities, uncertainty scoring, and actionable betting decisions. The sim and market layers remain fully decoupled — the pipeline sits between them.

**Code:** `api/app/analytics/calibration/`, `api/app/services/model_odds.py`, `api/app/routers/model_odds.py`

### Architecture

```
Sim Layer (unchanged)                  Market Layer (unchanged)
SimulationRunner                       FairBet / ClosingLine
  → raw home_wp                          → Pinnacle devig → market_wp
  → score_std_home/away                  → cross-book prices
  → home_wp_std_dev
        │                                      │
        └──────────────┬───────────────────────┘
                       │
              Calibration Layer (NEW)
              ├── SimCalibrator (isotonic regression)
              │     raw_wp → calibrated_wp
              ├── Uncertainty Scorer
              │     sim_variance + profile_freshness + market_disagreement
              │     → confidence_tier + penalty
              ├── Conservative Probability
              │     calibrated_wp ± penalty → p_conservative
              └── Decision Engine
                    p_conservative + market_price → Kelly + classification
                       │
                       ▼
              GET /api/model-odds/mlb
```

### Sim Observability

`SimulationRunner.aggregate_results()` now emits variance metrics alongside existing fields:

| Field | Type | Description |
|-------|------|-------------|
| `home_wp_std_dev` | float | Bernoulli std dev: `sqrt(p*(1-p)/n)` |
| `score_std_home` | float | Sample std dev of home scores across iterations |
| `score_std_away` | float | Sample std dev of away scores across iterations |

These are persisted on `analytics_prediction_outcomes` when batch sims run (see [Database](#database-columns) below).

### Calibration

`SimCalibrator` (`calibration/calibrator.py`) maps raw sim win probabilities to historically-accurate probabilities using scikit-learn's `IsotonicRegression`.

**Training data:** Joins `analytics_prediction_outcomes` (resolved predictions with Brier scores) to `closing_lines` (Pinnacle moneyline) via `game_id`. Devigging uses existing `remove_vig()` from the FairBet EV engine.

**Training:** Celery task `train_calibration_model` builds the dataset, fits the calibrator, and saves a joblib artifact to `artifacts/calibration/`.

**Inference:** The calibrator is loaded once per process and cached. Falls back to raw sim WP if no calibrator is available.

**Evaluation metrics:** Brier score before/after calibration, improvement delta, and 10-bin reliability diagram data.

### Uncertainty Scoring

`compute_uncertainty()` (`calibration/uncertainty.py`) produces a confidence tier and probability penalty from four weighted factors:

| Factor | Weight | Signal |
|--------|--------|--------|
| Sim variance | 15% | `home_wp_std_dev` from simulation |
| Profile freshness | 30% | Min games across both teams' rolling profiles |
| Market disagreement | 35% | `|calibrated_wp - market_wp|` |
| Pitcher data quality | 20% | Whether Statcast pitcher data is available |

**Confidence tiers and penalties:**

| Tier | Weighted Score | Probability Penalty | Required Edge |
|------|---------------|--------------------:|-------------:|
| high | < 0.15 | 1.0% | 2.0% |
| medium | 0.15–0.35 | 2.0% | 3.5% |
| low | 0.35–0.55 | 3.5% | 5.0% |
| very_low | ≥ 0.55 | 5.0% | no play |

A 0.5% tax/friction buffer is added to all required edge thresholds.

### Conservative Probability & Confidence Band

`apply_uncertainty()` produces:

- **`p_conservative`**: `p_true` pulled toward 0.5 by the penalty. Ensures recommended action is more cautious than the raw model.
- **Confidence band**: `p_true ± (penalty × 1.5)`, clamped to [0.01, 0.99].
- All values are also converted to American odds (`fair_line_mid`, `fair_line_conservative`, `fair_line_low`, `fair_line_high`).

### Decision Engine

`compute_model_odds()` (`services/model_odds.py`) combines calibrated probability, market price, and uncertainty into a complete decision:

| Output | Description |
|--------|-------------|
| `p_true` | Calibrated win probability |
| `p_conservative` | Probability after uncertainty penalty |
| `fair_line_mid` / `fair_line_conservative` | American odds conversions |
| `target_bet_line` | Price where edge exceeds required threshold |
| `strong_bet_line` | Target + additional 2% edge |
| `kelly_fraction` / `half_kelly` / `quarter_kelly` | Kelly criterion sizing |
| `decision` | `no_play`, `lean`, `playable`, or `strong_play` |

**Decision classification:**
- `very_low` confidence → always `no_play`
- No market data → `no_play`
- Edge ≤ 0 → `no_play`
- Positive edge but price doesn't beat target → `lean`
- Price beats target + medium/high confidence → `playable`
- Price beats target + high confidence + edge > 5% → `strong_play`

**Kelly sizing:** `kelly = max(0, (p × b − q) / b)` where `b` is the net decimal payout from the market price. Zero when no market price or no edge.

### API: `GET /api/model-odds/mlb`

Query parameters:
- `date` (string, YYYY-MM-DD) — game date (default: today)
- `game_id` (int, optional) — specific game

Response:

```json
{
  "games": [
    {
      "game_id": 1234,
      "game_date": "2026-03-21",
      "home_team": "New York Yankees",
      "away_team": "Boston Red Sox",
      "sim_raw_home_wp": 0.549,
      "calibrated": true,
      "home": {
        "p_true": 0.542,
        "p_conservative": 0.522,
        "model_line": -118.3,
        "model_line_conservative": -109.2,
        "model_range": [-126.1, -111.0],
        "current_market": {
          "best_price": 102.0,
          "best_book": "DraftKings"
        },
        "edge_vs_conservative": 0.032,
        "target_entry": 105.0,
        "strong_play_at": 115.0,
        "kelly_half": 0.007,
        "kelly_quarter": 0.0035,
        "confidence": "medium",
        "decision": "playable",
        "required_edge": 0.04
      },
      "away": { }
    }
  ],
  "date": "2026-03-21",
  "count": 1,
  "calibrator_loaded": true
}
```

### Database Columns

New nullable columns on `analytics_prediction_outcomes` (migration `20260321_add_sim_observability`):

| Column | Type | Description |
|--------|------|-------------|
| `sim_wp_std_dev` | Float | Bernoulli std dev of home WP |
| `sim_iterations` | Integer | Number of Monte Carlo iterations |
| `sim_score_std_home` | Float | Score std dev (home) |
| `sim_score_std_away` | Float | Score std dev (away) |
| `profile_games_home` | Integer | Games in home team rolling profile |
| `profile_games_away` | Integer | Games in away team rolling profile |
| `sim_probability_source` | String(50) | Probability source (team_profile, league_defaults, ml) |
| `feature_snapshot` | JSONB | Frozen team profile metrics used in simulation |

### Celery Tasks

| Task Name | Description |
|-----------|-------------|
| `train_calibration_model` | Build calibration dataset from historical predictions + closing lines, train isotonic regression, save artifact. Requires ≥ 20 resolved predictions. |

### Key Files

| File | Purpose |
|------|---------|
| `analytics/calibration/calibrator.py` | `SimCalibrator` — isotonic regression calibration |
| `analytics/calibration/dataset.py` | Calibration dataset builder (joins predictions to closing lines) |
| `analytics/calibration/uncertainty.py` | Uncertainty scoring, conservative probability, confidence bands |
| `services/model_odds.py` | Decision engine — Kelly sizing, target entry, classification |
| `routers/model_odds.py` | `GET /api/model-odds/mlb` endpoint |

---

## Game Theory Module

Strategic optimization layer that operates on top of the prediction engine. Provides mathematical frameworks for bet sizing, strategy optimization, and portfolio management.

All endpoints are under `/api/analytics/game-theory/*`.

### Kelly Criterion — Optimal Bet Sizing

Given a model probability and sportsbook odds, computes the mathematically optimal fraction of bankroll to wager.

- `POST /game-theory/kelly` — Single bet sizing (full, half, or quarter Kelly)
- `POST /game-theory/kelly/batch` — Multiple bets with total exposure cap

**Inputs:** `model_prob` (true win probability), `american_odds`, `bankroll`, `variant` (full/half/quarter), `max_fraction` (per-bet cap), `max_total_exposure` (batch only)

**Output:** `KellyResult` with edge, kelly_fraction, recommended_wager, implied_prob, decimal_odds

### Nash Equilibrium — Strategy Optimization

Solves two-player zero-sum games using fictitious play to find mixed-strategy Nash Equilibria.

- `POST /game-theory/nash` — Generic payoff matrix solver
- `POST /game-theory/nash/lineup` — Batter-vs-pitcher matchup optimization (rows=batters, cols=pitchers, values=expected outcome like wOBA)
- `POST /game-theory/nash/pitch-selection` — Optimal pitch mix against batter stances

**Output:** `NashEquilibrium` with row_strategy, col_strategy, game_value, iteration count

### Portfolio Optimization — Bet Diversification

Mean-variance optimization across multiple bets, accounting for correlations between outcomes (e.g., same-game bets are correlated).

- `POST /game-theory/portfolio` — Allocate bankroll across N bets

**Inputs:** Array of bets (model_prob, american_odds, optional game_id for correlation), `risk_aversion`, `max_per_bet`, `max_total`, optional `correlation_matrix`

**Output:** `PortfolioResult` with per-bet allocations (weights), expected return, variance, Sharpe ratio

### Minimax — Adversarial Decision Trees

Minimax with alpha-beta pruning for sequential game trees, plus regret minimization for repeated games.

- `POST /game-theory/minimax` — Solve a game tree (recursive JSON structure with maximizer/minimizer nodes)
- `POST /game-theory/regret-matching` — Find optimal mixed strategy via regret minimization over a payoff matrix

**Output:** `MinimaxResult` with optimal_action, action_values, strategy (mixed), regret_table

### Key Files

| File | Purpose |
|------|---------|
| `analytics/game_theory/kelly.py` | Kelly Criterion: `compute_kelly()`, `compute_kelly_batch()` |
| `analytics/game_theory/nash.py` | Nash Equilibrium: `solve_zero_sum()`, `lineup_nash()`, `pitch_selection_nash()` |
| `analytics/game_theory/portfolio.py` | Portfolio optimization: `optimize_portfolio()` |
| `analytics/game_theory/minimax.py` | Minimax + regret matching: `solve_minimax()`, `regret_matching()` |
| `analytics/game_theory/types.py` | Dataclass output types: `KellyResult`, `NashEquilibrium`, `PortfolioResult`, `MinimaxResult` |
| `analytics/api/_game_theory_routes.py` | FastAPI routes (8 endpoints) |
