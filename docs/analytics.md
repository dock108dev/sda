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
| `probabilities/` | Provider abstraction — rule-based, ML, ensemble; ProbabilityResolver for routing |
| `services/` | AnalyticsService (API adapter), ModelService (model management) |
| `simulation/` | Pitch-level simulators (PitchSimulator, PitchLevelGameSimulator) |
| `sports/mlb/` | MLB PA-level game simulator, transforms, metrics, matchup logic; `constants.py` is the SSOT for all MLB baselines, event probabilities, and feature defaults |
| `training/core/` | TrainingPipeline, DatasetBuilder, ModelEvaluator |
| `training/sports/` | Sport-specific training (MLBTrainingPipeline — label extraction, record builders; stubs only for data loading) |

---

## Simulation

The simulation engine runs Monte Carlo simulations with pluggable probability sources.

### Flow

1. `SimulationEngine.run_simulation()` receives game context (teams, probability mode, iterations)
2. If `pitch_level` mode: routes to `_run_pitch_level()` (see Pitch-Level Simulation below)
3. Otherwise: `ProbabilityResolver` selects the provider based on mode (`rule_based`, `ml`, `ensemble`)
4. When home/away team profiles are both present, PA probabilities are resolved separately for each team — each team's batting profile is paired with the opposing team as the "pitcher" side, producing differentiated probabilities per team
5. `SimulationRunner` invokes the sport-specific simulator N times (default 5,000–10,000)
6. Results aggregated: win probabilities, average scores, score distribution, event summary, variance metrics (WP std dev, score std dev per team)
7. `SimulationDiagnostics` attached to result with execution metadata

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

`get_team_rolling_profile()` returns a `ProfileResult` dataclass (`services/profile_service.py`) with freshness metadata:

```python
@dataclass
class ProfileResult:
    metrics: dict[str, float]
    games_used: int
    date_range: tuple[str, str]      # (oldest_game_date, newest_game_date)
    season_breakdown: dict[int, int] # year → game count
```

Surfaced in the API response as `profile_meta.data_freshness` with per-team game counts and date ranges. The frontend shows a stale-data warning when the newest game is older than 3 days.

### MLB Game Simulation (PA-Level)

Each game simulation runs 9+ innings. Each half-inning simulates plate appearances until 3 outs:

1. Sample event (strikeout, out, walk, single, double, triple, home_run) from probability distribution
2. Advance base runners based on event type
3. Track runs scored
4. Accumulate event counts per team (K, BB, HR, singles, etc.)

The simulator returns enriched results including per-team event counts and innings played:

```python
{
    "home_score": 5, "away_score": 3, "winner": "home",
    "home_events": {"strikeout": 8, "out": 5, "walk": 3, "single": 6, "double": 2, "triple": 0, "home_run": 1, "pa_total": 38},
    "away_events": {"strikeout": 9, "out": 4, "walk": 2, "single": 5, "double": 1, "triple": 1, "home_run": 0, "pa_total": 35},
    "innings_played": 9,
}
```

Event data is backward compatible — existing callers that only read `home_score`/`away_score`/`winner` are unaffected.

**Key files:**
- `core/simulation_engine.py` — orchestrator
- `core/simulation_runner.py` — N iterations + aggregation + event summary + variance computation
- `core/simulation_analysis.py` — sanity checks
- `sports/mlb/game_simulator.py` — PA-level MLB simulator

### Lineup-Aware Simulation

When lineup data is provided, the simulator uses per-batter probability distributions instead of team-level aggregates. Each batter in the lineup gets a unique probability set derived from the `MLBMatchup.batter_vs_pitcher()` matchup engine.

**How it works:**

1. API receives lineup (9 batters + starting pitcher per team)
2. Player rolling profiles are fetched for each batter via `get_player_rolling_profile()`
3. Pitcher rolling profile fetched via `get_pitcher_rolling_profile()`
4. `MLBMatchup.batter_vs_pitcher()` pre-computes 36 probability sets (9 batters × 2 pitcher states × 2 teams) — done once before the simulation loop
5. `simulate_game_with_lineups()` runs the full game with per-batter weights and lineup index tracking
6. Pitcher transition: starter pitches through a configurable inning (default 6), then switches to bullpen weights (team-level aggregate)

**Performance:** Pre-computation happens once; the hot loop indexes into pre-computed arrays with `rng.choices()` — same speed as team-level simulation.

**Key files:**
- `sports/mlb/game_simulator.py` — `simulate_game_with_lineups()`, `_simulate_half_inning_lineup()`
- `services/profile_service.py` — `get_player_rolling_profile()`, `get_pitcher_rolling_profile()`, `get_team_roster()`
- `sports/mlb/matchup.py` — `batter_vs_pitcher()` probability computation

**Fallback:** When `use_lineup=True` is passed to a simulator that does not implement `simulate_game_with_lineups()`, the runner raises `RuntimeError` rather than silently falling back.

### Player & Pitcher Profile Service

Rolling statistical profiles for individual batters and pitchers, used by lineup-aware simulation.

**`get_player_rolling_profile(player_external_ref, team_id, *, rolling_window, db)`**
- Queries `MLBPlayerAdvancedStats` for the player's last N games
- Runs each row through `stats_to_metrics()` and averages across games
- Returns the same metrics dict shape as `get_team_rolling_profile()`
- Sparse data blending: if player has < 5 games, blends with team average (weight = games/5)

**`get_pitcher_rolling_profile(player_external_ref, team_id, *, rolling_window, db)`**
- Queries `SportsPlayerBoxscore` for the pitcher's recent games
- Derives metrics from JSONB `stats` column (`innings_pitched`, `strike_outs`, `base_on_balls`, `home_runs`, `hits`)
- Returns: `strikeout_rate`, `walk_rate`, `contact_suppression`, `power_suppression`
- Requires ≥ 3 valid games (games with 0 approx batters faced are skipped)

**`get_team_roster(team_abbreviation, *, db)`**
- Recent batters: distinct players from `MLBPlayerAdvancedStats` in last 30 days with game count
- Recent pitchers: distinct from `SportsPlayerBoxscore` with games started and avg IP
- Returns `{batters: [...], pitchers: [...]}`

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

Four probability sources, selected via `probability_mode`:

| Provider | Description |
|----------|-------------|
| **RuleBasedProvider** | League-average defaults adjusted by batter/pitcher features. |
| **MLProvider** | Loads active trained model from registry, builds features, runs inference. |
| **EnsembleProvider** | Weighted average of rule-based and ML predictions (configurable weights). |
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

### MLB Features

**Plate-appearance features (28 total):**
- Batter (15): contact_rate, power_index, barrel_rate, hard_hit_rate, swing_rate, whiff_rate, avg_exit_velocity, expected_slug, z_swing_pct, o_swing_pct, z_contact_pct, o_contact_pct, zone_swing_rate, chase_rate, plate_discipline_index
- Pitcher (13): contact_rate, power_index, barrel_rate, hard_hit_rate, swing_rate, whiff_rate, z_swing_pct, o_swing_pct, z_contact_pct, o_contact_pct, zone_swing_rate, chase_rate, plate_discipline_index

**Game-level features (60 total):**
- Home (30) + Away (30): Each side exposes 30 metrics from `_GAME_METRIC_KEYS`:
  - Derived composites (8): contact_rate, power_index, barrel_rate, hard_hit_rate, swing_rate, whiff_rate, avg_exit_velocity, expected_slug
  - Raw plate discipline (4): z_swing_pct, o_swing_pct, z_contact_pct, o_contact_pct
  - Raw quality of contact (3): avg_exit_velo, hard_hit_pct, barrel_pct
  - Raw counts (10): total_pitches, balls_in_play, hard_hit_count, barrel_count, zone_pitches, zone_swings, zone_contact, outside_pitches, outside_swings, outside_contact
  - Derived ratios (5): zone_swing_rate, chase_rate, zone_contact_rate, outside_contact_rate, plate_discipline_index

Feature names are prefixed with `home_` or `away_` (e.g., `home_contact_rate`, `away_barrel_rate`).

### Feature Configuration

Feature loadouts are stored in the `analytics_feature_configs` database table. Each loadout has a name, sport, model type, and a JSONB array of features — each with `name`, `enabled` (bool), and `weight` (float). Loadouts are managed via the Admin UI models page or the `/api/analytics/feature-config*` CRUD endpoints.

---

## Training Pipeline

End-to-end flow: data → features → train → evaluate → register. Training runs asynchronously via a Celery task (`train_analytics_model`) and is tracked in the `analytics_training_jobs` table.

### Steps

1. `POST /api/analytics/train` creates an `AnalyticsTrainingJob` record and dispatches the Celery task
2. `_execute_training()` converts the DB-backed `AnalyticsFeatureConfig` (JSONB array of `{name, enabled, weight}`) into a `{feat_name: {enabled, weight}}` dict and passes it through the pipeline
3. `load_training_data()` — handled by `app.tasks._training_helpers` (the SSOT for DB-backed training data loading):
   - **Game model:** queries `MLBGameAdvancedStats` + `SportsGame` for games in the date range, builds rolling home/away team profiles
   - **PA model:** queries `MLBPlayerAdvancedStats` for player stats in the date range, builds rolling batter profiles paired with opposing team profiles, derives PA outcome labels heuristically from Statcast metrics (whiff rate, barrel rate, exit velocity, hard-hit rate, swing rates)
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
| GET | `/mlb-teams` | List MLB teams with games_with_stats count (for dropdowns) |
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
| GET | `/api/simulator/mlb/teams` | List MLB teams available for simulation |
| POST | `/api/simulator/mlb` | Run MLB game simulation (only home_team + away_team required) |

See [API — Simulator](api.md#simulator) for full request/response documentation.

### Experiments & Replay

| Method | Path | Description |
|--------|------|-------------|
| POST | `/experiments` | Create experiment suite (parameter sweep across algorithms, windows, splits, loadouts) |
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
| `tasks/calibration_tasks.py` | Celery task for calibration model training |

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
