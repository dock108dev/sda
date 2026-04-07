# Analytics Integration Guide

> API reference for the analytics system. All endpoints live under `/api/analytics/`.

---

## Navigation Structure

| Nav Item | Route | Purpose |
|----------|-------|---------|
| **Simulator** | `/analytics/simulator` | Multi-sport pregame Monte Carlo simulations (MLB, NBA, NHL, NCAAB) |
| **Models** | `/analytics/models` | Feature loadouts, training, model registry, performance |
| **Batch Sims** | `/analytics/batch` | Bulk simulation jobs + prediction outcome tracking |
| **Experiments** | `/analytics/experiments` | Parameter sweep training + variant comparison |
| **Profiles** | `/analytics/profiles` | Team rolling profile comparison + scouting |

---

## Simulator

Monte Carlo simulations using pitch-level data and team profiles.

### Teams & Rosters

```
GET /api/analytics/{sport}/teams    (sport = mlb, nba, nhl, ncaab)
GET /api/analytics/mlb-teams        (MLB backward compat)
GET /api/analytics/mlb-roster?team=NYY (MLB only — lineup support)
```

#### Roster Response (MLB)

The roster endpoint now includes **projected lineup** and **probable starter** fields that downstream apps should use as defaults:

```json
{
  "batters": [...],
  "pitchers": [...],
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

Returns team metrics with league baselines for comparison.

### Run Simulation

```
POST /api/analytics/simulate
{
  "sport": "mlb",
  "home_team": "NYY",
  "away_team": "BOS",
  "iterations": 5000,
  "rolling_window": 30,
  "probability_mode": "ml",
  "model_id": "mlb_pa_v3",  // optional: test a specific model without activating it
  "home_lineup": [...],     // optional: exactly 9 batters
  "away_lineup": [...],     // optional: exactly 9 batters
  "home_starter": {...},    // optional
  "away_starter": {...},    // optional
  "starter_innings": 6.0,
  "sportsbook": {...}       // optional: moneylines for edge comparison
}
```

The backend uses the active trained model (or the model specified by `model_id`). Falls back to rule-based if no model is trained.

The response includes `event_summary` (per-team PA rates and game shape metrics) and `simulation_info.sanity_warnings` when anomalous results are detected.

**Multi-sport:** The same endpoint works for any sport:
```json
{
  "sport": "nba",
  "home_team": "BOS",
  "away_team": "LAL",
  "iterations": 5000
}
```
Lineup-related fields (`home_lineup`, `away_lineup`, `home_starter`, `away_starter`, `starter_innings`) are MLB-only.

### Public Simulator API (for downstream apps)

Simplified endpoints at `/api/simulator/{sport}` — no configuration needed:

```
GET  /api/simulator/{sport}/teams
POST /api/simulator/{sport}  {"home_team": "BOS", "away_team": "LAL"}
```

See [API Reference](api.md#simulator) for full documentation.

---

## Models Page

### Feature Loadouts
- `GET /api/analytics/feature-configs` — list loadouts (filter by `sport`, `model_type`)
- `GET /api/analytics/feature-config/{id}` — single loadout
- `POST /api/analytics/feature-config` — create loadout
- `PUT /api/analytics/feature-config/{id}` — update loadout
- `DELETE /api/analytics/feature-config/{id}` — delete loadout
- `POST /api/analytics/feature-config/{id}/clone` — clone loadout
- `POST /api/analytics/feature-configs/bulk-delete` — bulk delete (`{"ids": [1, 2, 3]}`)
- `GET /api/analytics/available-features?sport=mlb` — list features with descriptions

### Training
- `POST /api/analytics/train` — start training job
- `GET /api/analytics/training-jobs` — list jobs
- `POST /api/analytics/training-job/:id/cancel`

### Registry
- `GET /api/analytics/models` — list registered models
- `POST /api/analytics/models/activate` — activate a model
- `GET /api/analytics/models/compare`

### Performance
- `GET /api/analytics/calibration-report`
- `GET /api/analytics/degradation-alerts`

---

## Batch Sims

### Endpoints

- `POST /api/analytics/batch-simulate` — accepts optional `model_id` to test a specific trained model
- `GET /api/analytics/batch-simulate-jobs` — list jobs
- `GET /api/analytics/batch-simulate-job/{id}` — detail with `batch_summary` and `warnings`
- `DELETE /api/analytics/batch-simulate-job/{id}` — delete job (revokes Celery task if running)
- `POST /api/analytics/record-outcomes` — trigger outcome recording for finalized games
- `GET /api/analytics/prediction-outcomes` — list prediction outcomes (filter by `sport`, `status`)

### Response: Batch Sim Job

```jsonc
{
  "id": 17,
  "sport": "mlb",
  "probability_mode": "ml",
  "iterations": 5000,
  "rolling_window": 60,
  "date_start": "2025-08-01",
  "date_end": "2025-08-01",
  "status": "completed",           // pending | queued | running | completed | failed
  "celery_task_id": "abc-123",
  "game_count": 11,
  "results": [                     // array of per-game results
    {
      "game_id": 125322,
      "game_date": "2025-08-01",
      "home_team": "Seattle Mariners",
      "away_team": "Texas Rangers",
      "home_win_probability": 0.509,
      "away_win_probability": 0.491,
      "average_home_score": 5.5,
      "average_away_score": 5.6,
      "probability_source": "ml",
      "has_profiles": true
    }
  ],
  "error_message": null,
  "created_at": "2026-03-18T...",
  "completed_at": "2026-03-18T...",
  // Detail endpoint only (GET /batch-simulate-job/{id}):
  "batch_summary": {
    "avg_home_runs": 5.4,
    "avg_away_runs": 5.5,
    "avg_total_runs": 10.8,
    "home_win_rate": 0.727,
    "wp_distribution": {"50-55": 5, "55-60": 2, "60-70": 4, "70+": 0}
  },
  "warnings": [                    // sanity alerts (may be empty)
    "Home avg runs (18.3) is unrealistically high (>15)"
  ]
}
```

### Response: Prediction Outcome

```jsonc
{
  "id": 1,
  "game_id": 125322,
  "sport": "mlb",
  "batch_sim_job_id": 17,
  "home_team": "Seattle Mariners",
  "away_team": "Texas Rangers",
  "predicted_home_wp": 0.509,
  "predicted_away_wp": 0.491,
  "predicted_home_score": 5.5,
  "predicted_away_score": 5.6,
  "probability_mode": "ml",
  "game_date": "2025-08-01",
  // Populated after game finishes (null while pending):
  "actual_home_score": 4,
  "actual_away_score": 6,
  "home_win_actual": false,
  "correct_winner": false,
  "brier_score": 0.245,
  "outcome_recorded_at": "2026-03-18T...",
  "created_at": "2026-03-18T..."
}
```

### Model Testing Workflow

1. `POST /api/analytics/train` — train a model with custom parameters, get `job_id`
2. `GET /api/analytics/training-job/{id}` — poll until complete, get `model_id`
3. `POST /api/analytics/batch-simulate` with `model_id` — test that model on real games
4. Results include `event_summary` (PA rates), `batch_summary`, and `warnings` for tuning
5. `POST /api/analytics/simulate` with `model_id` — test single matchups with diagnostics

---

## Experiments

Parameter sweep training — combinatorial grid of algorithms, rolling windows, test splits, and feature loadouts.

- `POST /api/analytics/experiments` — create and launch suite
- `GET /api/analytics/experiments` — list suites
- `GET /api/analytics/experiments/:id` — suite detail with variant leaderboard
- `POST /api/analytics/experiments/:id/promote/:variant_id` — activate winning model
- `POST /api/analytics/experiments/:id/cancel` — stop a running experiment
- `DELETE /api/analytics/experiments/:id` — delete suite and all variants
- `DELETE /api/analytics/experiments/:id/variant/:variant_id` — delete single variant

### Historical Replay

- `POST /api/analytics/replay` — evaluate model on historical games
- `GET /api/analytics/replay-jobs`

---

## Types

Types for this repo's admin UI live in `web/src/lib/api/analyticsTypes.ts`.

Downstream consuming apps should define their own types based on the response shapes documented above.
