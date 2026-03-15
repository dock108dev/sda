# Analytics Integration Guide

> API reference for the analytics system. All endpoints live under `/api/analytics/`.

---

## Navigation Structure

| Nav Item | Route | Purpose |
|----------|-------|---------|
| **Simulator** | `/analytics/simulator` | MLB pregame Monte Carlo simulations using pitch-level data |
| **Models** | `/analytics/models` | Feature loadouts, training, model registry, performance |
| **Batch Sims** | `/analytics/batch` | Bulk simulation jobs + prediction outcome tracking |
| **Experiments** | `/analytics/experiments` | Parameter sweep training + variant comparison |
| **Profiles** | `/analytics/profiles` | Team rolling profile comparison + scouting |

---

## Simulator

Monte Carlo simulations using pitch-level data and team profiles.

### Teams & Rosters

```
GET /api/analytics/mlb-teams
GET /api/analytics/mlb-roster?team=NYY
```

### Team Profiles

```
GET /api/analytics/team-profile?team=NYY&rolling_window=30
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
  "home_lineup": [...],     // optional: exactly 9 batters
  "away_lineup": [...],     // optional: exactly 9 batters
  "home_starter": {...},    // optional
  "away_starter": {...},    // optional
  "starter_innings": 6.0,
  "sportsbook": {...}       // optional: moneylines for edge comparison
}
```

The backend uses the active trained model. Falls back to rule-based if no model is trained.

---

## Models Page

### Feature Loadouts
- `GET/POST/PUT/DELETE /api/analytics/feature-config[s]`
- `GET /api/analytics/available-features?sport=mlb`

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

- `POST /api/analytics/batch-simulate`
- `GET /api/analytics/batch-simulate-jobs`
- `POST /api/analytics/record-outcomes`
- `GET /api/analytics/prediction-outcomes`

---

## Experiments

Parameter sweep training — combinatorial grid of algorithms, rolling windows, test splits, and feature loadouts.

- `POST /api/analytics/experiments` — create and launch suite
- `GET /api/analytics/experiments` — list suites
- `GET /api/analytics/experiments/:id` — suite detail with variant leaderboard
- `POST /api/analytics/experiments/:id/promote/:variant_id` — activate winning model

### Historical Replay

- `POST /api/analytics/replay` — evaluate model on historical games
- `GET /api/analytics/replay-jobs`

---

## Types

See `web/src/lib/api/analyticsTypes.ts` for the complete type catalog.
