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
  probability_mode?: "rule_based" | "ml";
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
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
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

export interface ModelPerformance {
  total_predictions: number;
  brier_score: number;
  log_loss: number;
  average_score_error: number;
  average_total_error: number;
  winner_accuracy: number;
  mae_score: number;
  mae_total: number;
  prediction_bias: {
    home_bias: number;
    total_bias: number;
    home_score_bias: number;
  };
  calibration_buckets: {
    bucket: string;
    count: number;
    avg_predicted: number;
    avg_actual: number;
  }[];
}

export interface FeatureConfigResponse {
  model: string;
  sport: string;
  enabled_features: string[];
  weights: Record<string, number>;
  features: Record<string, { enabled: boolean; weight: number }>;
}

export interface FeatureConfigListResponse {
  available: string[];
  registered: { name: string; model: string; sport: string; feature_count: number }[];
}

export async function getFeatureConfig(
  model: string,
): Promise<FeatureConfigResponse> {
  const params = new URLSearchParams({ model });
  return fetchJson<FeatureConfigResponse>(
    `${base()}/api/analytics/feature-config?${params}`,
  );
}

export async function listFeatureConfigs(): Promise<FeatureConfigListResponse> {
  return fetchJson<FeatureConfigListResponse>(
    `${base()}/api/analytics/feature-configs`,
  );
}

export async function saveFeatureConfig(
  config: { model: string; sport: string; features: Record<string, { enabled: boolean; weight: number }> },
): Promise<{ status: string; model: string; enabled_features: string[] }> {
  return fetchJson(`${base()}/api/analytics/feature-config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export async function getModelPerformance(
  sport?: string,
): Promise<ModelPerformance> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  const qs = params.toString();
  return fetchJson<ModelPerformance>(
    `${base()}/api/analytics/model-performance${qs ? `?${qs}` : ""}`,
  );
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

export interface ActiveModelResponse {
  sport: string;
  model_type: string;
  active_model: string | null;
  version?: number;
  metrics?: Record<string, number>;
}

export async function getActiveModel(
  sport: string,
  modelType: string,
): Promise<ActiveModelResponse> {
  const params = new URLSearchParams({ sport, model_type: modelType });
  return fetchJson<ActiveModelResponse>(`${base()}/api/analytics/models/active?${params}`);
}

export interface ModelMetricsEntry {
  model_id: string;
  sport: string;
  model_type: string;
  version: number;
  active: boolean;
  metrics: Record<string, number>;
}

export async function getModelMetrics(
  modelId?: string,
  sport?: string,
  modelType?: string,
): Promise<{ models: ModelMetricsEntry[]; count: number }> {
  const params = new URLSearchParams();
  if (modelId) params.set("model_id", modelId);
  if (sport) params.set("sport", sport);
  if (modelType) params.set("model_type", modelType);
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/model-metrics${qs ? `?${qs}` : ""}`);
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

export async function getEnsembleConfig(
  sport: string,
  modelType: string,
): Promise<EnsembleConfigResponse> {
  const params = new URLSearchParams({ sport, model_type: modelType });
  return fetchJson<EnsembleConfigResponse>(`${base()}/api/analytics/ensemble-config?${params}`);
}

export async function listEnsembleConfigs(): Promise<{
  configs: EnsembleConfigResponse[];
  count: number;
}> {
  return fetchJson(`${base()}/api/analytics/ensemble-configs`);
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

// ---------------------------------------------------------------------------
// MLB Advanced Models
// ---------------------------------------------------------------------------

export async function getPitchModel(params: {
  pitcher_k_rate?: number;
  batter_contact_rate?: number;
  count_balls?: number;
  count_strikes?: number;
}): Promise<{ pitch_probabilities: Record<string, number> }> {
  const qs = new URLSearchParams();
  if (params.pitcher_k_rate != null) qs.set("pitcher_k_rate", String(params.pitcher_k_rate));
  if (params.batter_contact_rate != null) qs.set("batter_contact_rate", String(params.batter_contact_rate));
  if (params.count_balls != null) qs.set("count_balls", String(params.count_balls));
  if (params.count_strikes != null) qs.set("count_strikes", String(params.count_strikes));
  return fetchJson(`${base()}/api/analytics/mlb/pitch-model?${qs}`);
}

export async function getPitchSim(params: {
  pitcher_k_rate?: number;
  batter_contact_rate?: number;
}): Promise<{ result: string; pitches: number; final_count: string; batted_ball_result?: string }> {
  const qs = new URLSearchParams();
  if (params.pitcher_k_rate != null) qs.set("pitcher_k_rate", String(params.pitcher_k_rate));
  if (params.batter_contact_rate != null) qs.set("batter_contact_rate", String(params.batter_contact_rate));
  return fetchJson(`${base()}/api/analytics/mlb/pitch-sim?${qs}`);
}

export async function getRunExpectancy(params: {
  base_state?: number;
  outs?: number;
  batter_quality?: number;
  pitcher_quality?: number;
}): Promise<{ expected_runs: number }> {
  const qs = new URLSearchParams();
  if (params.base_state != null) qs.set("base_state", String(params.base_state));
  if (params.outs != null) qs.set("outs", String(params.outs));
  if (params.batter_quality != null) qs.set("batter_quality", String(params.batter_quality));
  if (params.pitcher_quality != null) qs.set("pitcher_quality", String(params.pitcher_quality));
  return fetchJson(`${base()}/api/analytics/mlb/run-expectancy?${qs}`);
}
