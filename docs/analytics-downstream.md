# Analytics Integration Guide for Downstream Apps

> This document describes the analytics APIs and UI patterns your app should implement.
> **Remove all old team-level-only simulation logic.** The lineup-aware simulator is the only supported simulation path going forward.

---

## API Base

All analytics endpoints live under `/api/analytics/`. Include `X-API-Key` header on every request. See `api.md` for auth details.

---

## Navigation Structure

The analytics section has **4 pages**:

| Nav Item | Route | Purpose |
|----------|-------|---------|
| **Simulator** | `/analytics/simulator` | Run pregame and live game simulations |
| **Models** | `/analytics/models` | Feature loadouts, training, model registry, performance |
| **Batch Sims** | `/analytics/batch` | Bulk simulation jobs + prediction outcome tracking |
| **Team Explorer** | `/analytics/explorer` | Team/player/matchup data lookup |

---

## Simulator Page (Primary)

This is the main user-facing page. It has two modes: **Pregame** and **Live**.

### Pregame Flow

The pregame simulator uses **lineup-aware simulation**. Here's the full flow:

#### Step 1: Select Teams

```
GET /api/analytics/mlb-teams
→ { teams: [{ id, name, short_name, abbreviation, games_with_stats }], count }
```

Display two dropdowns (home/away) populated from this endpoint. Use the `abbreviation` field for API calls.

#### Step 2: Fetch Rosters

When a team is selected, fetch its roster:

```
GET /api/analytics/mlb-roster?team=NYY
→ {
    batters: [{ external_ref, name, games_played }],
    pitchers: [{ external_ref, name, games, avg_ip }]
  }
```

- **Batters** are ordered by `games_played` descending (most active first)
- **Pitchers** are ordered by appearance count descending

#### Step 3: Build Lineup

Present a UI for the user to:
1. Pick **9 batters** per team from the roster (drag-to-reorder or numbered slots)
2. Pick **1 starting pitcher** per team from the pitchers list
3. Set **starter innings** (default 6.0, range 4.0–9.0) — the inning when the bullpen takes over

Auto-fill suggestion: default to the top 9 batters by `games_played` and the top pitcher by `games`.

#### Step 4: Run Simulation

```
POST /api/analytics/simulate
Content-Type: application/json

{
  "sport": "mlb",
  "home_team": "NYY",
  "away_team": "BOS",
  "iterations": 10000,
  "rolling_window": 30,
  "probability_mode": "ml",
  "home_lineup": [
    { "external_ref": "660271", "name": "Aaron Judge" },
    { "external_ref": "592450", "name": "Juan Soto" },
    ... (exactly 9 entries)
  ],
  "away_lineup": [
    { "external_ref": "646240", "name": "Rafael Devers" },
    ... (exactly 9 entries)
  ],
  "home_starter": { "external_ref": "543037", "name": "Gerrit Cole" },
  "away_starter": { "external_ref": "678394", "name": "Brayan Bello" },
  "starter_innings": 6.0
}
```

**Lineup mode activation:** Both `home_lineup` and `away_lineup` must have exactly 9 entries. If either is missing, the backend uses team-level mode. If `use_lineup=True` is passed to a simulator that does not implement `simulate_game_with_lineups()`, the backend raises `RuntimeError` — there is no silent fallback.

#### Step 5: Display Results

Response shape:

```typescript
interface SimulationResult {
  sport: string;
  home_team: string;
  away_team: string;
  home_win_probability: number;    // 0-1
  away_win_probability: number;    // 0-1
  average_home_score: number;
  average_away_score: number;
  average_total: number;
  median_total: number;
  most_common_scores: { score: string; probability: number }[];
  iterations: number;
  probability_source?: string;
  probability_meta?: Record<string, unknown>;
  profile_meta?: {
    has_profiles?: boolean;
    rolling_window?: number;
    model_win_probability?: number;
    model_prediction_source?: string;
    home_pa_source?: string;
    away_pa_source?: string;
    lineup_mode?: boolean;
    home_pitcher?: PitcherAnalytics;
    away_pitcher?: PitcherAnalytics;
    home_bullpen?: Record<string, number>;
    away_bullpen?: Record<string, number>;
    data_freshness?: {
      home: { games_used: number; newest_game: string; oldest_game: string };
      away: { games_used: number; newest_game: string; oldest_game: string };
    };
    [key: string]: unknown;
  };
  model_home_win_probability?: number;
  home_pa_probabilities?: Record<string, number>;
  away_pa_probabilities?: Record<string, number>;
  // Diagnostics (added 2026-03-12)
  simulation_info?: {
    requested_mode: string;       // what the user asked for
    executed_mode: string;        // what actually ran
    fallback_used: boolean;
    fallback_reason: string | null;
    model_info: {
      model_id: string;
      version: number;
      trained_at: string | null;
      metrics: Record<string, number>;
    } | null;
    warnings: string[];
  };
  predictions?: {
    monte_carlo: {
      home_win_probability: number | null;
      method: string;
      probability_inputs?: string;
    };
    game_model?: {
      home_win_probability: number | null;
      method: string;
      model_id?: string;
    };
  };
}
```

Key display elements:
- **Win probabilities** — show as percentages with a visual bar
- **Average scores** — expected final score
- **Most common scores** — show top 5-10 likely final scores
- **Lineup mode confirmation** — check `profile_meta.lineup_mode` to confirm lineup data was used
- **PA probabilities** — `home_pa_probabilities` / `away_pa_probabilities` show aggregate plate appearance outcome distributions (strikeout, walk, single, double, triple, home_run probabilities)
- **Simulation diagnostics** — check `simulation_info` to see what probability mode actually ran and whether a fallback occurred. Display `simulation_info.fallback_reason` as a warning when `fallback_used` is true
- **Data freshness** — check `profile_meta.data_freshness` for per-team game counts and date ranges. Warn if newest game is older than 3 days
- **Two prediction systems** — `predictions.monte_carlo` is the PA-level Monte Carlo result; `predictions.game_model` (when present) is a separate trained classifier prediction

### Live Simulation

For in-progress games:

```
POST /api/analytics/live-simulate
{
  "sport": "mlb",
  "inning": 5,
  "half": "top",
  "outs": 1,
  "bases": { "first": true, "second": false, "third": false },
  "score": { "home": 3, "away": 2 },
  "iterations": 10000
}
→ {
    home_win_probability, away_win_probability,
    expected_final_score: { home, away },
    iterations
  }
```

---

## Models Page

Consolidates the full model lifecycle into one page with sections:

### Sections

1. **Feature Loadouts** — CRUD for feature configurations
   - `GET /api/analytics/feature-configs` — list
   - `POST /api/analytics/feature-config` — create
   - `PUT /api/analytics/feature-config/:id` — update
   - `DELETE /api/analytics/feature-config/:id` — delete
   - `POST /api/analytics/feature-config/:id/clone` — clone
   - `GET /api/analytics/available-features?sport=mlb` — list available features for a sport

2. **Training** — kick off training jobs + ensemble config
   - `POST /api/analytics/train` — start a training job
   - `GET /api/analytics/training-jobs` — list jobs
   - `GET /api/analytics/training-job/:id` — poll status
   - `GET /api/analytics/ensemble-configs` — list ensemble configs
   - `POST /api/analytics/ensemble-config` — save ensemble weights

3. **Registry** — view trained models, activate/deactivate, compare
   - `GET /api/analytics/models` — list registered models
   - `GET /api/analytics/models/details?model_id=xxx` — model details + feature importance
   - `POST /api/analytics/models/activate` — activate a model
   - `GET /api/analytics/models/compare?model_ids=a,b` — compare two models

4. **Performance** — calibration and degradation monitoring
   - `GET /api/analytics/calibration-report?sport=mlb` — accuracy/brier metrics
   - `GET /api/analytics/degradation-alerts` — active alerts
   - `POST /api/analytics/degradation-alerts/:id/acknowledge` — dismiss alert
   - `POST /api/analytics/degradation-check?sport=mlb` — trigger manual check

---

## Batch Sims Page

Run bulk simulations across all upcoming games and track prediction accuracy.

### Endpoints

- `POST /api/analytics/batch-simulate` — start a batch job
- `GET /api/analytics/batch-simulate-jobs?sport=mlb` — list jobs
- `POST /api/analytics/record-outcomes` — match predictions to final scores
- `GET /api/analytics/prediction-outcomes` — list per-game predictions with actuals

---

## Team Explorer Page

Lookup and comparison tools.

### Endpoints

- `GET /api/analytics/team?sport=mlb&team_id=xxx` — team rolling metrics
- `GET /api/analytics/player?sport=mlb&player_id=xxx` — player metrics
- `GET /api/analytics/matchup?sport=mlb&entity_a=xxx&entity_b=yyy` — head-to-head probabilities

---

## TypeScript Types

Copy these types into your API client. They match the backend response shapes exactly:

```typescript
// Lineup slot (for sim request)
interface LineupSlot {
  external_ref: string;
  name: string;
}

// Same shape for pitcher
type PitcherSlot = LineupSlot;

// Simulation request
interface SimulationRequest {
  sport: string;
  home_team: string;
  away_team: string;
  iterations?: number;
  seed?: number | null;
  probability_mode?: "rule_based" | "ml" | "ensemble" | "pitch_level";
  rolling_window?: number;
  sportsbook?: Record<string, unknown>;
  // Lineup fields (all 4 required to activate lineup mode)
  home_lineup?: LineupSlot[];    // exactly 9
  away_lineup?: LineupSlot[];    // exactly 9
  home_starter?: PitcherSlot;
  away_starter?: PitcherSlot;
  starter_innings?: number;      // default 6.0
}

// Roster response
interface RosterBatter {
  external_ref: string;
  name: string;
  games_played: number;
}

interface RosterPitcher {
  external_ref: string;
  name: string;
  games: number;
  avg_ip: number;
}

interface MLBRosterResponse {
  batters: RosterBatter[];
  pitchers: RosterPitcher[];
}

// Team list
interface MLBTeam {
  id: number;
  name: string;
  short_name: string;
  abbreviation: string;
  games_with_stats: number;
}
```

See `web/src/lib/api/analytics.ts` for the complete type catalog (training jobs, backtest, batch sim, calibration, degradation alerts, ensemble config, etc.).

---

## What to Remove

**Delete all old team-level-only simulation logic:**

1. Any simulation flow that sends `POST /simulate` without lineup fields — remove or upgrade to include lineup selection
2. Any hardcoded `home_probabilities` / `away_probabilities` overrides — the backend computes these from Statcast data now
3. Any UI that only shows two team dropdowns + "Run Sim" without lineup/pitcher selection
4. Any references to the old 6-nav analytics structure (Overview, Workbench, Simulator, Models, Performance, Explorer) — it's now 4 pages
5. The old Overview/landing page — the nav itself serves this purpose
6. The old Workbench page — its contents (loadouts, training, ensemble) are absorbed into the Models page
7. The old standalone Performance page — it's now a section within Models

**The only simulation path downstream apps should implement is the lineup-aware flow** (steps 1-5 above). Team-level fallback exists in the backend for backward compatibility but should not be the primary UX.
