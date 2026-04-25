# Analytics Integration Guide

> API reference for consuming apps. All endpoints live under `/api/analytics/`.

---

## Access Model

Analytics endpoints use **two access tiers**:

| Tier | Auth | Description |
|------|------|-------------|
| **Read** | API key only (`X-API-Key`) | Teams, rosters, profiles, simulations, predictions, model metrics, calibration reports |
| **Admin** | API key + admin role | Training, model activation/deletion, batch jobs, experiments, feature config CRUD |

Downstream consuming apps only need an API key for all read operations. Admin-gated endpoints are marked with a lock icon below.

---

## Simulator

Monte Carlo simulations using pitch-level data and team profiles.

### Teams & Rosters

```
GET /api/analytics/{sport}/teams    (sport = mlb, nba, nhl, ncaab) — SSOT
GET /api/analytics/mlb-teams        (thin delegate to /{sport}/teams with sport=mlb)
GET /api/analytics/mlb-roster?team=NYY (MLB only — lineup support)
```

All three are **read-only** (API key only).

#### Roster Response (MLB)

The roster endpoint returns **projected lineup** and **probable starter** fields that downstream apps should use as defaults:

```json
{
  "batters": [
    { "external_ref": "660271", "name": "Aaron Judge", "games_played": 28 }
  ],
  "pitchers": [
    { "external_ref": "543037", "name": "Gerrit Cole", "games": 6, "avg_ip": 6.2 }
  ],
  "projected_lineup": [
    { "external_ref": "665489", "name": "Jarren Duran" },
    ...
  ],
  "probable_starter": { "external_ref": "678394", "name": "Brayan Bello" }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `projected_lineup` | `array` or absent | Consensus 9-batter batting order from last 7 games. Use as default lineup pre-fill. Fall back to top 9 from `batters` if absent. |
| `probable_starter` | `object` or absent | Today's announced starter (from MLB Stats API). Cross-reference `external_ref` against `pitchers` for `avg_ip`. Fall back to first pitcher if absent. |

### Team Profiles

```
GET /api/analytics/team-profile?team=NYY&sport=mlb&rolling_window=30
```

Returns team metrics with league baselines for comparison. **Read-only.**

### Run Simulation

```
POST /api/analytics/simulate
{
  "sport": "mlb",
  "home_team": "NYY",
  "away_team": "BOS",
  "iterations": 5000,
  "rolling_window": 30,
  "probability_mode": "ml",           // "ml", "ensemble", "market_blend", "rule_based"
  "blend_alpha": 0.3,                 // only for market_blend mode (0-1, model weight)
  "home_lineup": [...],               // optional: exactly 9 batters (MLB only)
  "away_lineup": [...],               // optional: exactly 9 batters (MLB only)
  "home_starter": {...},              // optional (MLB only)
  "away_starter": {...},              // optional (MLB only)
  "starter_innings": 6.0,
  "sportsbook": {...}                 // optional: moneylines for edge comparison
}
```

**Read-only** (computation only, no data mutation). Works for any sport — lineup fields are MLB-only.

**Probability modes:**
- `ml` — ML model predictions (default)
- `ensemble` — weighted blend of ML + rule-based
- `market_blend` — ML simulation blended with devigged market lines (configurable alpha)
- `rule_based` — league-average defaults adjusted by team profiles

### Public Simulator API (alternative)

Simplified endpoints at `/api/simulator/{sport}` — same access tier (API key only):

```
GET  /api/simulator/{sport}/teams
POST /api/simulator/{sport}  {"home_team": "BOS", "away_team": "LAL"}
```

See [API Reference](api.md#simulator) for full documentation.

---

## Daily Forecasts (MLB)

Pre-computed predictions for all MLB games in the next 24 hours, refreshed hourly. **This is the recommended way for downstream apps to display MLB predictions** — no manual simulation needed.

### `GET /api/analytics/forecasts/mlb`

**Read-only** (API key only). Returns today's pre-computed predictions with line analysis.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `date` | `string` | today (ET) | Game date `YYYY-MM-DD` |
| `game_id` | `int` | — | Filter to a specific game |
| `min_edge` | `float` | — | Only include games where either side has at least this edge |

**Response:**
```json
{
  "forecasts": [
    {
      "game_id": 12345,
      "game_date": "2026-04-07",
      "home_team": "New York Yankees",
      "away_team": "Boston Red Sox",
      "home_win_prob": 0.583,
      "away_win_prob": 0.417,
      "predicted_home_score": 4.7,
      "predicted_away_score": 3.8,
      "probability_source": "lineup_matchup",
      "line_analysis": {
        "market_home_ml": -145,
        "market_away_ml": 125,
        "market_home_wp": 0.570,
        "market_away_wp": 0.430,
        "home_edge": 0.013,
        "away_edge": -0.013,
        "model_home_line": -152,
        "model_away_line": 132,
        "home_ev_pct": 2.3,
        "away_ev_pct": -1.8,
        "provider": "Pinnacle",
        "line_type": "current"
      },
      "sim_meta": {
        "iterations": 5000,
        "wp_std_dev": 0.012,
        "profile_games_home": 28,
        "profile_games_away": 30,
        "model_id": "mlb_pa_gb_20260401"
      },
      "refreshed_at": "2026-04-07T16:00:02Z"
    }
  ],
  "date": "2026-04-07",
  "count": 15,
  "last_refreshed": "2026-04-07T16:00:02Z"
}
```

| Field | Description |
|-------|-------------|
| `home_win_prob` / `away_win_prob` | Model win probability (sums to 1.0) |
| `predicted_home_score` / `predicted_away_score` | Average simulated final score |
| `probability_source` | How probabilities were computed: `lineup_matchup`, `team_profile`, or `league_defaults` |
| `line_analysis` | Current market odds comparison. `null` if no odds available for this game |
| `line_analysis.home_edge` | Model edge vs market: positive = model thinks home is underpriced |
| `line_analysis.home_ev_pct` | Expected value % if betting home at current market price |
| `line_analysis.model_home_line` | Model's fair American odds (with ~2% vig) |
| `sim_meta.model_id` | Which trained model was used. `null` = rule-based fallback |
| `last_refreshed` | When the forecasts were last recomputed (refreshes hourly at :05) |

### Usage Notes

- **Refresh cadence:** Forecasts update hourly at :05 past each hour. The `last_refreshed` field tells you how fresh the data is.
- **Edge filtering:** Use `?min_edge=0.03` to only show games where the model disagrees with the market by 3%+ on either side.
- **No odds?** Games without current market odds will have `line_analysis: null`. The simulation results (`home_win_prob`, scores) are still valid.
- **Off-season:** Returns `{"forecasts": [], "count": 0}` when no MLB games are scheduled.
- **Stale data:** Rows older than 1 day are automatically cleaned up.

---

## Models & Predictions (read-only)

All of these are **read-only** (API key only):

- `GET /api/analytics/models` — list registered models
- `GET /api/analytics/models/active` — currently active models
- `GET /api/analytics/models/details` — model details
- `GET /api/analytics/models/compare` — compare models
- `GET /api/analytics/model-metrics` — model performance metrics
- `GET /api/analytics/model-predict` — run a single prediction
- `POST /api/analytics/model-predict` — run prediction with custom params
- `GET /api/analytics/ensemble-config` — read ensemble config
- `GET /api/analytics/ensemble-configs` — list all configs

### Calibration & Outcomes (read-only)

- `GET /api/analytics/calibration-report` — prediction accuracy
- `GET /api/analytics/prediction-outcomes` — historical predictions (filter by `sport`, `status`)
- `GET /api/analytics/degradation-alerts` — model health alerts

### Feature Configs (read-only)

- `GET /api/analytics/feature-configs` — list loadouts (filter by `sport`, `model_type`)
- `GET /api/analytics/feature-config/{id}` — single loadout
- `GET /api/analytics/available-features?sport=mlb` — list features with descriptions

---

## Game Theory (read-only)

All computation-only, no data mutation:

- `POST /api/analytics/game-theory/kelly` — optimal bet sizing
- `POST /api/analytics/game-theory/kelly/batch` — batch bet sizing
- `POST /api/analytics/game-theory/nash` — Nash equilibrium
- `POST /api/analytics/game-theory/nash/lineup` — lineup optimization
- `POST /api/analytics/game-theory/nash/pitch-selection` — pitch selection
- `POST /api/analytics/game-theory/portfolio` — portfolio optimization
- `POST /api/analytics/game-theory/minimax` — minimax solver
- `POST /api/analytics/game-theory/regret-matching` — regret matching

---

## Batch Jobs & Results (read-only)

- `GET /api/analytics/batch-simulate-jobs` — list batch sim jobs
- `GET /api/analytics/batch-simulate-job/{id}` — job detail with `batch_summary` and `warnings`
- `GET /api/analytics/training-jobs` — list training jobs
- `GET /api/analytics/training-job/{job_id}` — training job detail

### Experiments (read-only)

- `GET /api/analytics/experiments` — list experiment suites
- `GET /api/analytics/experiments/{id}` — suite detail with variant leaderboard
- `GET /api/analytics/replay-jobs` — list replay jobs
- `GET /api/analytics/replay-job/{id}` — replay detail
- `GET /api/analytics/mlb-data-coverage` — data availability
- `GET /api/analytics/backtest-jobs` — list backtest jobs
- `GET /api/analytics/backtest-job/{id}` — backtest detail

---

## Admin-Only Endpoints

These require admin role (API key + JWT with `role=admin`). **Not intended for downstream consuming apps.**

### Training & Models
- `POST /api/analytics/train` — start training job
- `POST /api/analytics/training-job/{id}/cancel` — cancel training
- `POST /api/analytics/models/activate` — activate a model
- `DELETE /api/analytics/models` — delete a model
- `POST /api/analytics/ensemble-config` — create/update ensemble config

### Batch Operations
- `POST /api/analytics/batch-simulate` — start bulk batch sim
- `DELETE /api/analytics/batch-simulate-job/{id}` — delete batch job
- `POST /api/analytics/record-outcomes` — record prediction outcomes
- `POST /api/analytics/backtest` — start backtest

### Feature Configs
- `POST /api/analytics/feature-config` — create loadout
- `PUT /api/analytics/feature-config/{id}` — update loadout
- `DELETE /api/analytics/feature-config/{id}` — delete loadout
- `POST /api/analytics/feature-configs/bulk-delete` — bulk delete
- `POST /api/analytics/feature-config/{id}/clone` — clone loadout

### Experiments
- `POST /api/analytics/experiments` — create and launch suite
- `POST /api/analytics/experiments/{id}/promote/{variant_id}` — activate winning model
- `POST /api/analytics/experiments/{id}/cancel` — stop experiment
- `DELETE /api/analytics/experiments/{id}` — delete suite
- `DELETE /api/analytics/experiments/{id}/variant/{variant_id}` — delete variant
- `POST /api/analytics/replay` — start replay job

### Alerts
- `POST /api/analytics/degradation-check` — trigger degradation check
- `POST /api/analytics/degradation-alerts/{id}/acknowledge` — acknowledge alert

---

## Types

Types for this repo's admin UI live in `web/src/lib/api/analyticsTypes.ts`.

Downstream consuming apps should define their own types based on the response shapes documented above.
