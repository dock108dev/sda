/**
 * Analytics API client.
 *
 * Calls the FastAPI analytics endpoints via the Next.js proxy.
 */

import { getApiBase } from "./apiBase";

import type {
  SimulationRequest,
  SimulationResult,
  FeatureLoadout,
  FeatureLoadoutListResponse,
  AvailableFeaturesResponse,
  TrainingJobRequest,
  TrainingJob,
  RegisteredModel,
  ModelsListResponse,
  ModelDetails,
  ModelComparison,
  BacktestRequest,
  BacktestJob,
  BatchSimRequest,
  BatchSimJob,
  BatchSimGameResult,
  PredictionOutcome,
  CalibrationReport,
  DegradationAlert,
  EnsembleProviderWeight,
  EnsembleConfigResponse,
  MLBTeam,
  MLBRosterResponse,
  TeamProfileResponse,
  ExperimentSuiteRequest,
  ExperimentSuite,
  ExperimentVariant,
  ReplayRequest,
  ReplayJob,
} from "./analyticsTypes";

// Re-export every type so existing consumers of "@/lib/api/analytics" keep working.
export type {
  SimulationRequest,
  PitcherAnalytics,
  ScoreEntry,
  SimulationModelInfo,
  SimulationInfo,
  DataFreshness,
  PredictionEntry,
  SimulationResult,
  FeatureLoadout,
  FeatureLoadoutListResponse,
  AvailableFeature,
  AvailableFeaturesResponse,
  TrainingJobRequest,
  TrainingJob,
  RegisteredModel,
  ModelsListResponse,
  ModelDetails,
  ModelComparison,
  BacktestRequest,
  BacktestPrediction,
  BacktestJob,
  BatchSimRequest,
  BatchSimGameResult,
  BatchSimJob,
  BatchSimSummary,
  EventSummary,
  EventTeamSummary,
  EventGameSummary,
  EventPARates,
  PredictionOutcome,
  CalibrationReport,
  DegradationAlert,
  EnsembleProviderWeight,
  EnsembleConfigResponse,
  MLBTeam,
  RosterBatter,
  RosterPitcher,
  MLBRosterResponse,
  TeamProfileResponse,
  ExperimentSuiteRequest,
  ExperimentSuite,
  ExperimentVariant,
  ReplayRequest,
  ReplayJob,
} from "./analyticsTypes";

const base = () => getApiBase();

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

export async function runSimulation(
  req: SimulationRequest,
): Promise<SimulationResult> {
  return fetchJson<SimulationResult>(`${base()}/api/analytics/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

// ---------------------------------------------------------------------------
// Feature Loadout CRUD (DB-backed)
// ---------------------------------------------------------------------------

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

export async function bulkDeleteFeatureLoadouts(
  ids: number[],
): Promise<{ status: string; deleted: number; ids: number[] }> {
  return fetchJson(`${base()}/api/analytics/feature-configs/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
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

export async function deleteModel(
  modelId: string,
  deleteArtifact: boolean = false,
): Promise<{ status: string; model_id: string; artifact_deleted: boolean }> {
  return fetchJson(`${base()}/api/analytics/models`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, delete_artifact: deleteArtifact }),
  });
}

export async function getModelDetails(modelId: string): Promise<ModelDetails> {
  const params = new URLSearchParams({ model_id: modelId });
  return fetchJson<ModelDetails>(`${base()}/api/analytics/models/details?${params}`);
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

export async function getBatchSimJob(
  jobId: number,
): Promise<BatchSimJob> {
  return fetchJson<BatchSimJob>(
    `${base()}/api/analytics/batch-simulate-job/${jobId}`,
  );
}

export async function deleteBatchSimJob(
  jobId: number,
): Promise<{ status: string; id: number }> {
  return fetchJson(`${base()}/api/analytics/batch-simulate-job/${jobId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Prediction Outcomes / Calibration
// ---------------------------------------------------------------------------

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

export async function listEnsembleConfigs(): Promise<{
  configs: EnsembleConfigResponse[];
  count: number;
}> {
  return fetchJson(`${base()}/api/analytics/ensemble-configs`);
}

// ---------------------------------------------------------------------------
// MLB Teams (for simulator dropdowns)
// ---------------------------------------------------------------------------

export async function listMLBTeams(): Promise<{ teams: MLBTeam[]; count: number }> {
  return fetchJson<{ teams: MLBTeam[]; count: number }>(`${base()}/api/analytics/mlb-teams`);
}

// Generic Teams API (multi-sport)
export async function listTeams(
  sport: string,
): Promise<{ teams: MLBTeam[]; count: number }> {
  return fetchJson<{ teams: MLBTeam[]; count: number }>(
    `${base()}/api/analytics/${sport.toLowerCase()}/teams`,
  );
}

// ---------------------------------------------------------------------------
// MLB Roster (for lineup simulator)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Team Profile
// ---------------------------------------------------------------------------

export async function getTeamProfile(
  team: string,
  rollingWindow: number = 30,
): Promise<TeamProfileResponse> {
  const params = new URLSearchParams({ team, rolling_window: String(rollingWindow) });
  return fetchJson<TeamProfileResponse>(`${base()}/api/analytics/team-profile?${params}`);
}

// Generic Team Profile (multi-sport)
export async function getTeamProfileMultiSport(
  team: string,
  sport: string,
  rollingWindow: number = 30,
): Promise<TeamProfileResponse> {
  const params = new URLSearchParams({
    team,
    sport: sport.toLowerCase(),
    rolling_window: String(rollingWindow),
  });
  return fetchJson<TeamProfileResponse>(`${base()}/api/analytics/team-profile?${params}`);
}

// ---------------------------------------------------------------------------
// Experiment Suites
// ---------------------------------------------------------------------------

export async function createExperimentSuite(
  req: ExperimentSuiteRequest,
): Promise<{ status: string; suite: ExperimentSuite }> {
  return fetchJson(`${base()}/api/analytics/experiments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function listExperimentSuites(
  sport?: string,
  status?: string,
): Promise<{ suites: ExperimentSuite[]; count: number }> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  if (status) params.set("status", status);
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/experiments${qs ? `?${qs}` : ""}`);
}

export async function getExperimentSuite(
  suiteId: number,
): Promise<ExperimentSuite> {
  return fetchJson<ExperimentSuite>(`${base()}/api/analytics/experiments/${suiteId}`);
}

export async function promoteExperimentVariant(
  suiteId: number,
  variantId: number,
): Promise<{ status: string; model_id: string; suite: ExperimentSuite }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}/promote/${variantId}`, {
    method: "POST",
  });
}

export async function cancelExperimentSuite(
  suiteId: number,
): Promise<{ status: string; suite: ExperimentSuite }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}/cancel`, {
    method: "POST",
  });
}

export async function deleteExperimentSuite(
  suiteId: number,
): Promise<{ status: string; id: number }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}`, {
    method: "DELETE",
  });
}

export async function deleteExperimentVariant(
  suiteId: number,
  variantId: number,
): Promise<{ status: string; variant_id: number }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}/variant/${variantId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Historical Replay
// ---------------------------------------------------------------------------

export async function startReplay(
  req: ReplayRequest,
): Promise<{ status: string; job: ReplayJob }> {
  return fetchJson(`${base()}/api/analytics/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function listReplayJobs(
  sport?: string,
  suiteId?: number,
): Promise<{ jobs: ReplayJob[]; count: number }> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  if (suiteId !== undefined) params.set("suite_id", String(suiteId));
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/replay-jobs${qs ? `?${qs}` : ""}`);
}
