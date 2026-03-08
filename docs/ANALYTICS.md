# Analytics Engine

Predictive modeling, simulation, and matchup analysis for sports data.

**Code:** `api/app/analytics/`

---

## Package Structure

| Package | Description |
|---------|-------------|
| `api/` | REST endpoints — profiles, simulations, models, ensemble config |
| `core/` | Orchestration — SimulationEngine, SimulationRunner, SimulationAnalysis, MatchupEngine, ProfileBuilder |
| `ensemble/` | Weighted probability combination from multiple providers |
| `features/` | Feature extraction pipeline with configurable feature sets |
| `inference/` | Model inference engine with in-memory artifact caching |
| `models/core/` | BaseModel interface, ModelRegistry (JSON-backed), ModelLoader |
| `models/sports/mlb/` | MLB models — plate appearance, pitch, batted ball, run expectancy, game |
| `probabilities/` | Provider abstraction — rule-based, ML, ensemble; ProbabilityResolver for routing |
| `services/` | AnalyticsService (API adapter), ModelService (model management) |
| `simulation/` | Pitch-level simulators (PitchSimulator, PitchLevelGameSimulator) |
| `sports/mlb/` | MLB PA-level game simulator, transforms, metrics, matchup logic |
| `training/core/` | TrainingPipeline, DatasetBuilder, ModelEvaluator |
| `training/sports/` | Sport-specific training (MLBTrainingPipeline — data loading, label extraction) |

---

## Simulation

The simulation engine runs Monte Carlo simulations with pluggable probability sources.

### Flow

1. `SimulationEngine.run_simulation()` receives game context (teams, probability mode, iterations)
2. `ProbabilityResolver` selects the provider based on mode (`rule_based`, `ml`, `ensemble`, `pitch_level`)
3. `SimulationRunner` invokes the sport-specific simulator N times (default 5,000–10,000)
4. Results aggregated: win probabilities, average scores, score distribution

### MLB Game Simulation (PA-Level)

Each game simulation runs 9+ innings. Each half-inning simulates plate appearances until 3 outs:

1. Sample event (strikeout, out, walk, single, double, triple, home_run) from probability distribution
2. Advance base runners based on event type
3. Track runs scored

**Key files:**
- `core/simulation_engine.py` — orchestrator
- `core/simulation_runner.py` — N iterations + aggregation
- `sports/mlb/game_simulator.py` — PA-level MLB simulator

### Pitch-Level Simulation

Alternative path using `PitchLevelGameSimulator`. Simulates individual pitches within each plate appearance for more granular analytics. Slower than PA-level but provides pitch-sequence data.

**Key files:**
- `simulation/mlb/pitch_simulator.py` — pitch-level PA simulation

---

## Probability Providers

Four probability sources, selected via `probability_mode`:

| Provider | Description |
|----------|-------------|
| **RuleBasedProvider** | League-average defaults adjusted by batter/pitcher features. Always available as fallback. |
| **MLProvider** | Loads active trained model from registry, builds features, runs inference. |
| **EnsembleProvider** | Weighted average of rule-based and ML predictions (configurable weights). |
| **Pitch-level** | Implicit — when mode is `pitch_level`, SimulationEngine routes to PitchLevelGameSimulator. |

**Fallback:** If ML model fails to load and `strict_mode=False`, falls back to rule-based automatically.

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

1. `ModelInferenceEngine.predict_proba(sport, model_type, profiles)` called
2. Check registry for active model; auto-reload if active model changed
3. `InferenceCache` loads artifact via joblib (or returns cached)
4. `FeatureBuilder` extracts features from profiles
5. Model's `predict_proba(features)` returns probability dict

---

## Feature Pipeline

Sport-agnostic `FeatureBuilder` routes to sport-specific builders. Features are configurable via DB-backed feature loadouts.

### MLB Features

**Plate-appearance features (28 total):**
- Batter (14): contact_rate, power_index, barrel_rate, hard_hit_rate, swing_rate, whiff_rate, avg_exit_velocity, expected_slug, chase_rate, plate_discipline_index, z_contact_rate, o_contact_rate, z_swing_rate, o_swing_rate
- Pitcher (14): Same set as batter — allows the model to capture pitcher-side tendencies

**Game-level features (28 total):**
- Home/Away (14 each): contact_rate, power_index, barrel_rate, hard_hit_rate, whiff_rate, expected_slug, avg_exit_velo, chase_rate, plate_discipline_index, z_contact_rate, o_contact_rate, z_swing_rate, o_swing_rate, swing_rate

### Feature Configuration

Feature loadouts are stored in the `analytics_feature_configs` database table. Each loadout has a name, sport, model type, and a JSONB array of features — each with `name`, `enabled` (bool), and `weight` (float). Loadouts are managed via the Admin UI workbench or the `/api/analytics/feature-config*` CRUD endpoints.

---

## Training Pipeline

End-to-end flow: data → features → train → evaluate → register. Training runs asynchronously via a Celery task (`train_analytics_model`) and is tracked in the `analytics_training_jobs` table.

### Steps

1. `POST /api/analytics/train` creates an `AnalyticsTrainingJob` record and dispatches the Celery task
2. `load_training_data()` — queries `MLBGameAdvancedStats` + `SportsGame` for games in the date range
3. `build_dataset()` — extracts features (from the linked feature loadout) and labels via DatasetBuilder
4. `train_test_split()` — sklearn split (configurable, default 80/20)
5. `train_model()` — fits sklearn model (gradient_boosting default; also random_forest, xgboost)
6. `evaluate_model()` — accuracy, precision, recall, F1, Brier score
7. `save_artifact()` — serializes to `{sport}/artifacts/{model_id}.pkl` via joblib
8. Register in model registry; update job record with metrics and artifact path

### Label Extraction (MLB)

- `pa_label_fn()` — PA outcome (strikeout, walk, single, double, triple, home_run, out)
- `game_label_fn()` — game outcome (home_win, away_win)

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

### Profiles & Matchups

| Method | Path | Description |
|--------|------|-------------|
| GET | `/team` | Team analytical profile (rolling window from DB) |
| GET | `/player` | Player analytical profile |
| GET | `/matchup` | Head-to-head matchup analysis (rolling profiles from DB) |
| GET | `/mlb-teams` | List MLB teams with games_with_stats count (for dropdowns) |

### Simulation (Admin)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/simulate` | Monte Carlo sim with full control (probability mode, ensemble, custom probabilities) |
| POST | `/live-simulate` | Live game simulation from current state |
| POST | `/batch-simulate` | Async batch simulation over upcoming games (Celery task) |
| GET | `/batch-simulate-jobs` | List batch simulation jobs |
| GET | `/batch-simulate-job/{id}` | Get batch simulation job details |

### Simulator (Downstream Apps)

Separate router at `/api/simulator` — simplified, downstream-friendly interface. Always uses ML probability mode.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/simulator/mlb/teams` | List MLB teams available for simulation |
| POST | `/api/simulator/mlb` | Run MLB game simulation (only home_team + away_team required) |

See [API.md — Simulator](API.md#simulator) for full request/response documentation.

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
