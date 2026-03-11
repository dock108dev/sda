/**
 * Analytics API client.
 *
 * Calls the FastAPI analytics endpoints via the Next.js proxy.
 */

import { getApiBase } from "./apiBase";

const base = () => getApiBase();

export interface TeamAnalytics {
  sport: string;
  team_id: string;
  name: string;
  metrics: Record<string, number>;
}

export interface PlayerAnalytics {
  sport: string;
  player_id: string;
  name: string;
  metrics: Record<string, number>;
}

export interface MatchupAnalytics {
  sport: string;
  entity_a: string;
  entity_b: string;
  probabilities: Record<string, number>;
  comparison: Record<string, unknown>;
  advantages: Record<string, string>;
}

export interface SimulationRequest {
  sport: string;
  home_team: string;
  away_team: string;
  iterations?: number;
  seed?: number | null;
  home_probabilities?: Record<string, number>;
  away_probabilities?: Record<string, number>;
  sportsbook?: Record<string, unknown>;
  probability_mode?: "rule_based" | "ml" | "ensemble";
  rolling_window?: number;
  // Lineup-level simulation (optional)
  home_lineup?: { external_ref: string; name: string }[];
  away_lineup?: { external_ref: string; name: string }[];
  home_starter?: { external_ref: string; name: string };
  away_starter?: { external_ref: string; name: string };
  starter_innings?: number;
}

export interface ScoreEntry {
  score: string;
  probability: number;
}

export interface SimulationResult {
  sport: string;
  home_team: string;
  away_team: string;
  home_win_probability: number;
  away_win_probability: number;
  average_home_score: number;
  average_away_score: number;
  average_total: number;
  median_total: number;
  most_common_scores: ScoreEntry[];
  iterations: number;
  sportsbook_comparison?: Record<string, unknown>;
  probability_source?: string;
  probability_meta?: Record<string, unknown>;
  profile_meta?: {
    has_profiles?: boolean;
    rolling_window?: number;
    model_win_probability?: number;
    model_prediction_source?: string;
    home_pa_source?: string;
    away_pa_source?: string;
    [key: string]: unknown;
  };
  model_home_win_probability?: number;
  home_pa_probabilities?: Record<string, number>;
  away_pa_probabilities?: Record<string, number>;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.error || body.message || JSON.stringify(body);
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new Error(`API error: ${res.status} — ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function getTeamAnalytics(
  sport: string,
  teamId: string,
): Promise<TeamAnalytics> {
  const params = new URLSearchParams({ sport, team_id: teamId });
  return fetchJson<TeamAnalytics>(`${base()}/api/analytics/team?${params}`);
}

export async function getPlayerAnalytics(
  sport: string,
  playerId: string,
): Promise<PlayerAnalytics> {
  const params = new URLSearchParams({ sport, player_id: playerId });
  return fetchJson<PlayerAnalytics>(`${base()}/api/analytics/player?${params}`);
}

export async function getMatchupAnalytics(
  sport: string,
  entityA: string,
  entityB: string,
): Promise<MatchupAnalytics> {
  const params = new URLSearchParams({ sport, entity_a: entityA, entity_b: entityB });
  return fetchJson<MatchupAnalytics>(`${base()}/api/analytics/matchup?${params}`);
}

export async function runSimulation(
  req: SimulationRequest,
): Promise<SimulationResult> {
  return fetchJson<SimulationResult>(`${base()}/api/analytics/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export interface LiveSimulateRequest {
  sport: string;
  inning: number;
  half: "top" | "bottom";
  outs: number;
  bases: { first: boolean; second: boolean; third: boolean };
  score: { home: number; away: number };
  iterations?: number;
  seed?: number | null;
  home_probabilities?: Record<string, number>;
  away_probabilities?: Record<string, number>;
}

export interface LiveSimulateResult {
  sport: string;
  inning: number;
  half: string;
  score: { home: number; away: number };
  home_win_probability: number;
  away_win_probability: number;
  expected_final_score: { home: number; away: number };
  iterations: number;
}

export async function runLiveSimulation(
  req: LiveSimulateRequest,
): Promise<LiveSimulateResult> {
  return fetchJson<LiveSimulateResult>(`${base()}/api/analytics/live-simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}


// ---------------------------------------------------------------------------
// Feature Loadout CRUD (DB-backed)
// ---------------------------------------------------------------------------

export interface FeatureLoadout {
  id: number;
  name: string;
  sport: string;
  model_type: string;
  features: { name: string; enabled: boolean; weight: number }[];
  is_default: boolean;
  enabled_count: number;
  total_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface FeatureLoadoutListResponse {
  loadouts: FeatureLoadout[];
  count: number;
}

export async function listFeatureLoadouts(
  sport?: string,
  modelType?: string,
): Promise<FeatureLoadoutListResponse> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  if (modelType) params.set("model_type", modelType);
  const qs = params.toString();
  return fetchJson<FeatureLoadoutListResponse>(
    `${base()}/api/analytics/feature-configs${qs ? `?${qs}` : ""}`,
  );
}

export async function getFeatureLoadout(id: number): Promise<FeatureLoadout> {
  return fetchJson<FeatureLoadout>(`${base()}/api/analytics/feature-config/${id}`);
}

export async function createFeatureLoadout(data: {
  name: string;
  sport: string;
  model_type: string;
  features: { name: string; enabled: boolean; weight: number }[];
  is_default?: boolean;
}): Promise<{ status: string } & FeatureLoadout> {
  return fetchJson(`${base()}/api/analytics/feature-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateFeatureLoadout(
  id: number,
  data: Partial<{
    name: string;
    sport: string;
    model_type: string;
    features: { name: string; enabled: boolean; weight: number }[];
    is_default: boolean;
  }>,
): Promise<{ status: string } & FeatureLoadout> {
  return fetchJson(`${base()}/api/analytics/feature-config/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteFeatureLoadout(
  id: number,
): Promise<{ status: string; id: number; name: string }> {
  return fetchJson(`${base()}/api/analytics/feature-config/${id}`, {
    method: "DELETE",
  });
}

export async function cloneFeatureLoadout(
  id: number,
  name?: string,
): Promise<{ status: string } & FeatureLoadout> {
  const params = new URLSearchParams();
  if (name) params.set("name", name);
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/feature-config/${id}/clone${qs ? `?${qs}` : ""}`, {
    method: "POST",
  });
}

export interface AvailableFeature {
  name: string;
  entity: string;
  source_key: string;
  description: string;
  data_type: string;
  model_types: string[];
}

export interface AvailableFeaturesResponse {
  sport: string;
  total_games_with_data: number;
  plate_appearance_features: AvailableFeature[];
  game_features: AvailableFeature[];
  all_features: AvailableFeature[];
}

export async function getAvailableFeatures(
  sport: string = "mlb",
): Promise<AvailableFeaturesResponse> {
  const params = new URLSearchParams({ sport });
  return fetchJson<AvailableFeaturesResponse>(
    `${base()}/api/analytics/available-features?${params}`,
  );
}

// ---------------------------------------------------------------------------
// Training Pipeline
// ---------------------------------------------------------------------------

export interface TrainingJobRequest {
  feature_config_id?: number | null;
  sport: string;
  model_type: string;
  date_start?: string | null;
  date_end?: string | null;
  test_split?: number;
  algorithm?: string;
  random_state?: number;
  rolling_window?: number;
}

export interface TrainingJob {
  id: number;
  feature_config_id: number | null;
  sport: string;
  model_type: string;
  algorithm: string;
  date_start: string | null;
  date_end: string | null;
  test_split: number;
  random_state: number;
  rolling_window: number;
  status: "pending" | "queued" | "running" | "completed" | "failed";
  celery_task_id: string | null;
  model_id: string | null;
  artifact_path: string | null;
  metrics: Record<string, number> | null;
  train_count: number | null;
  test_count: number | null;
  feature_names: string[] | null;
  feature_importance: { name: string; importance: number }[] | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export async function startTraining(
  req: TrainingJobRequest,
): Promise<{ status: string; job: TrainingJob }> {
  return fetchJson(`${base()}/api/analytics/train`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function listTrainingJobs(
  sport?: string,
  status?: string,
): Promise<{ jobs: TrainingJob[]; count: number }> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  if (status) params.set("status", status);
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/training-jobs${qs ? `?${qs}` : ""}`);
}

export async function getTrainingJob(id: number): Promise<TrainingJob> {
  return fetchJson<TrainingJob>(`${base()}/api/analytics/training-job/${id}`);
}

export async function cancelTrainingJob(id: number): Promise<{ status: string }> {
  return fetchJson(`${base()}/api/analytics/training-job/${id}/cancel`, {
    method: "POST",
  });
}


export interface RegisteredModel {
  model_id: string;
  artifact_path: string;
  metadata_path?: string;
  version: number;
  created_at: string;
  metrics: Record<string, number>;
  sport: string;
  model_type: string;
  active: boolean;
}

export interface ModelsListResponse {
  models: RegisteredModel[];
  count: number;
}

export async function listRegisteredModels(
  sport?: string,
  modelType?: string,
): Promise<ModelsListResponse> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  if (modelType) params.set("model_type", modelType);
  const qs = params.toString();
  return fetchJson<ModelsListResponse>(
    `${base()}/api/analytics/models${qs ? `?${qs}` : ""}`,
  );
}

export async function activateModel(
  sport: string,
  modelType: string,
  modelId: string,
): Promise<{ status: string; active_model?: string; message?: string }> {
  return fetchJson(`${base()}/api/analytics/models/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sport, model_type: modelType, model_id: modelId }),
  });
}


export interface ModelDetails {
  model_id: string;
  sport: string;
  model_type: string;
  version: number;
  active: boolean;
  artifact_path?: string;
  metadata_path?: string;
  created_at?: string;
  metrics: Record<string, number>;
  feature_config?: string;
  training_row_count?: number;
  random_state?: number;
  feature_importance?: { name: string; importance: number }[];
}

export async function getModelDetails(modelId: string): Promise<ModelDetails> {
  const params = new URLSearchParams({ model_id: modelId });
  return fetchJson<ModelDetails>(`${base()}/api/analytics/models/details?${params}`);
}

export interface ModelComparison {
  sport: string;
  model_type: string;
  models: { model_id: string; version?: number; active: boolean; metrics: Record<string, number> }[];
  comparison?: {
    better_model: string;
    metric_differences: Record<string, number>;
    model_a: string;
    model_b: string;
  };
}

export async function compareModels(
  sport: string,
  modelType: string,
  modelIds: string[],
): Promise<ModelComparison> {
  const params = new URLSearchParams({
    sport,
    model_type: modelType,
    model_ids: modelIds.join(","),
  });
  return fetchJson<ModelComparison>(`${base()}/api/analytics/models/compare?${params}`);
}

// ---------------------------------------------------------------------------
// Backtesting
// ---------------------------------------------------------------------------

export interface BacktestRequest {
  model_id: string;
  artifact_path: string;
  sport: string;
  model_type: string;
  date_start?: string | null;
  date_end?: string | null;
  rolling_window?: number;
}

export interface BacktestPrediction {
  predicted: number;
  actual: number;
  correct: boolean;
  home_score?: number;
  away_score?: number;
  probabilities?: Record<string, number>;
}

export interface BacktestJob {
  id: number;
  model_id: string;
  artifact_path: string;
  sport: string;
  model_type: string;
  date_start: string | null;
  date_end: string | null;
  rolling_window: number;
  status: "pending" | "queued" | "running" | "completed" | "failed";
  celery_task_id: string | null;
  game_count: number | null;
  correct_count: number | null;
  metrics: Record<string, number> | null;
  predictions: BacktestPrediction[] | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export async function startBacktest(
  req: BacktestRequest,
): Promise<{ status: string; job: BacktestJob }> {
  return fetchJson(`${base()}/api/analytics/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function listBacktestJobs(
  modelId?: string,
  sport?: string,
): Promise<{ jobs: BacktestJob[]; count: number }> {
  const params = new URLSearchParams();
  if (modelId) params.set("model_id", modelId);
  if (sport) params.set("sport", sport);
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/backtest-jobs${qs ? `?${qs}` : ""}`);
}

// ---------------------------------------------------------------------------
// Batch Simulation
// ---------------------------------------------------------------------------

export interface BatchSimRequest {
  sport: string;
  probability_mode?: string;
  iterations?: number;
  rolling_window?: number;
  date_start?: string;
  date_end?: string;
}

export interface BatchSimGameResult {
  game_id: string;
  game_date: string;
  home_team: string;
  away_team: string;
  home_win_probability: number;
  away_win_probability: number;
  average_home_score: number;
  average_away_score: number;
  probability_source: string;
  has_profiles: boolean;
}

export interface BatchSimJob {
  id: number;
  sport: string;
  probability_mode: string;
  iterations: number;
  rolling_window: number;
  date_start: string | null;
  date_end: string | null;
  status: string;
  celery_task_id: string | null;
  game_count: number | null;
  results: BatchSimGameResult[] | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export async function startBatchSimulation(
  req: BatchSimRequest,
): Promise<{ job: BatchSimJob }> {
  return fetchJson<{ job: BatchSimJob }>(`${base()}/api/analytics/batch-simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function listBatchSimJobs(
  sport?: string,
): Promise<{ jobs: BatchSimJob[]; count: number }> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  return fetchJson<{ jobs: BatchSimJob[]; count: number }>(
    `${base()}/api/analytics/batch-simulate-jobs?${params}`,
  );
}

// ---------------------------------------------------------------------------
// Prediction Outcomes / Calibration
// ---------------------------------------------------------------------------

export interface PredictionOutcome {
  id: number;
  game_id: number;
  sport: string;
  batch_sim_job_id: number | null;
  home_team: string;
  away_team: string;
  predicted_home_wp: number;
  predicted_away_wp: number;
  predicted_home_score: number | null;
  predicted_away_score: number | null;
  probability_mode: string | null;
  game_date: string | null;
  actual_home_score: number | null;
  actual_away_score: number | null;
  home_win_actual: boolean | null;
  correct_winner: boolean | null;
  brier_score: number | null;
  outcome_recorded_at: string | null;
  created_at: string | null;
}

export interface CalibrationReport {
  total_predictions: number;
  resolved: number;
  accuracy: number;
  brier_score: number;
  avg_home_score_error: number;
  avg_away_score_error: number;
  home_bias: number;
}

export async function triggerRecordOutcomes(): Promise<{ status: string; task_id: string }> {
  return fetchJson<{ status: string; task_id: string }>(`${base()}/api/analytics/record-outcomes`, {
    method: "POST",
  });
}

export async function listPredictionOutcomes(opts?: {
  sport?: string;
  resolved?: boolean;
  batch_sim_job_id?: number;
  limit?: number;
}): Promise<{ outcomes: PredictionOutcome[]; count: number }> {
  const params = new URLSearchParams();
  if (opts?.sport) params.set("sport", opts.sport);
  if (opts?.resolved !== undefined) params.set("resolved", String(opts.resolved));
  if (opts?.batch_sim_job_id !== undefined) params.set("batch_sim_job_id", String(opts.batch_sim_job_id));
  if (opts?.limit) params.set("limit", String(opts.limit));
  return fetchJson<{ outcomes: PredictionOutcome[]; count: number }>(
    `${base()}/api/analytics/prediction-outcomes?${params}`,
  );
}

export async function getCalibrationReport(
  sport?: string,
): Promise<CalibrationReport> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  return fetchJson<CalibrationReport>(`${base()}/api/analytics/calibration-report?${params}`);
}

// ---------------------------------------------------------------------------
// Degradation Alerts
// ---------------------------------------------------------------------------

export interface DegradationAlert {
  id: number;
  sport: string;
  alert_type: string;
  baseline_brier: number;
  recent_brier: number;
  baseline_accuracy: number;
  recent_accuracy: number;
  baseline_count: number;
  recent_count: number;
  delta_brier: number;
  delta_accuracy: number;
  severity: string;
  message: string;
  acknowledged: boolean;
  created_at: string | null;
}

export async function triggerDegradationCheck(
  sport: string = "mlb",
): Promise<{ status: string; task_id: string }> {
  const params = new URLSearchParams({ sport });
  return fetchJson<{ status: string; task_id: string }>(
    `${base()}/api/analytics/degradation-check?${params}`,
    { method: "POST" },
  );
}

export async function listDegradationAlerts(opts?: {
  sport?: string;
  acknowledged?: boolean;
  limit?: number;
}): Promise<{ alerts: DegradationAlert[]; count: number }> {
  const params = new URLSearchParams();
  if (opts?.sport) params.set("sport", opts.sport);
  if (opts?.acknowledged !== undefined) params.set("acknowledged", String(opts.acknowledged));
  if (opts?.limit) params.set("limit", String(opts.limit));
  return fetchJson<{ alerts: DegradationAlert[]; count: number }>(
    `${base()}/api/analytics/degradation-alerts?${params}`,
  );
}

export async function acknowledgeDegradationAlert(
  alertId: number,
): Promise<DegradationAlert> {
  return fetchJson<DegradationAlert>(
    `${base()}/api/analytics/degradation-alerts/${alertId}/acknowledge`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Ensemble Configuration
// ---------------------------------------------------------------------------

export interface EnsembleProviderWeight {
  name: string;
  weight: number;
}

export interface EnsembleConfigResponse {
  sport: string;
  model_type: string;
  providers: EnsembleProviderWeight[];
}

export async function listEnsembleConfigs(): Promise<{
  configs: EnsembleConfigResponse[];
  count: number;
}> {
  return fetchJson(`${base()}/api/analytics/ensemble-configs`);
}

// ---------------------------------------------------------------------------
// MLB Teams (for simulator dropdowns)
// ---------------------------------------------------------------------------

export interface MLBTeam {
  id: number;
  name: string;
  short_name: string;
  abbreviation: string;
  games_with_stats: number;
}

export async function listMLBTeams(): Promise<{ teams: MLBTeam[]; count: number }> {
  return fetchJson<{ teams: MLBTeam[]; count: number }>(`${base()}/api/analytics/mlb-teams`);
}

// ---------------------------------------------------------------------------
// MLB Roster (for lineup simulator)
// ---------------------------------------------------------------------------

export interface RosterBatter {
  external_ref: string;
  name: string;
  games_played: number;
}

export interface RosterPitcher {
  external_ref: string;
  name: string;
  games: number;
  avg_ip: number;
}

export interface MLBRosterResponse {
  batters: RosterBatter[];
  pitchers: RosterPitcher[];
  error?: string;
}

export async function getMLBRoster(
  team: string,
): Promise<MLBRosterResponse> {
  const params = new URLSearchParams({ team });
  return fetchJson<MLBRosterResponse>(`${base()}/api/analytics/mlb-roster?${params}`);
}

export async function saveEnsembleConfig(
  sport: string,
  modelType: string,
  providers: EnsembleProviderWeight[],
): Promise<{ status: string } & EnsembleConfigResponse> {
  return fetchJson(`${base()}/api/analytics/ensemble-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sport, model_type: modelType, providers }),
  });
}

