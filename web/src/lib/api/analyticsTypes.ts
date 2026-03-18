/**
 * Type definitions for the Analytics API client.
 *
 * Extracted from analytics.ts to keep type declarations separate from
 * runtime API logic.
 */

export interface SimulationRequest {
  sport: string;
  home_team: string;
  away_team: string;
  iterations?: number;
  seed?: number | null;
  home_probabilities?: Record<string, number>;
  away_probabilities?: Record<string, number>;
  sportsbook?: Record<string, unknown>;
  probability_mode?: "rule_based" | "ml" | "ensemble" | "pitch_level";
  rolling_window?: number;
  // Lineup-level simulation (optional)
  home_lineup?: { external_ref: string; name: string }[];
  away_lineup?: { external_ref: string; name: string }[];
  home_starter?: { external_ref: string; name: string; avg_ip?: number };
  away_starter?: { external_ref: string; name: string; avg_ip?: number };
  starter_innings?: number;
  exclude_playoffs?: boolean;
}

export interface PitcherAnalytics {
  name: string | null;
  avg_ip: number | null;
  raw_profile: Record<string, number> | null;
  adjusted_profile: Record<string, number> | null;
  is_regressed: boolean;
}

export interface ScoreEntry {
  score: string;
  probability: number;
}

export interface SimulationModelInfo {
  model_id: string;
  version: number;
  trained_at: string | null;
  metrics: Record<string, number>;
}

export interface SimulationInfo {
  requested_mode: string;
  executed_mode: string;
  model_info: SimulationModelInfo | null;
  warnings: string[];
}

export interface DataFreshness {
  games_used: number;
  newest_game: string;
  oldest_game: string;
}

export interface PredictionEntry {
  home_win_probability: number | null;
  method: string;
  probability_inputs?: string;
  model_id?: string;
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
    lineup_mode?: boolean;
    home_pitcher?: PitcherAnalytics;
    away_pitcher?: PitcherAnalytics;
    home_bullpen?: Record<string, number>;
    away_bullpen?: Record<string, number>;
    data_freshness?: { home: DataFreshness; away: DataFreshness };
    [key: string]: unknown;
  };
  model_home_win_probability?: number;
  home_pa_probabilities?: Record<string, number>;
  away_pa_probabilities?: Record<string, number>;
  simulation_info?: SimulationInfo;
  predictions?: {
    monte_carlo: PredictionEntry;
    game_model?: PredictionEntry;
  };
}

// ---------------------------------------------------------------------------
// Experiment Suite
// ---------------------------------------------------------------------------

export interface ExperimentSuiteRequest {
  name: string;
  description?: string;
  sport?: string;
  model_type?: string;
  parameter_grid: {
    algorithms?: string[];
    rolling_windows?: number[];
    feature_config_ids?: (number | null)[];
    test_splits?: number[];
    date_start?: string;
    date_end?: string;
    feature_grid?: {
      features: { name: string; enabled: boolean; weight_min: number; weight_max: number; vary_enabled?: boolean }[];
      max_combos?: number;
    };
  };
  tags?: string[];
}

export interface ExperimentVariant {
  id: number;
  suite_id: number;
  variant_index: number;
  algorithm: string;
  rolling_window: number;
  feature_config_id: number | null;
  training_date_start: string | null;
  training_date_end: string | null;
  test_split: number;
  extra_params: Record<string, unknown> | null;
  training_job_id: number | null;
  replay_job_id: number | null;
  model_id: string | null;
  status: string;
  training_metrics: Record<string, number> | null;
  replay_metrics: Record<string, number> | null;
  rank: number | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface ExperimentSuite {
  id: number;
  name: string;
  description: string | null;
  sport: string;
  model_type: string;
  parameter_grid: Record<string, unknown>;
  tags: string[] | null;
  total_variants: number;
  completed_variants: number;
  failed_variants: number;
  status: string;
  leaderboard: { model_id: string; rank: number; metrics: Record<string, number> }[] | null;
  promoted_model_id: string | null;
  promoted_at: string | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
  variants?: ExperimentVariant[];
}

// ---------------------------------------------------------------------------
// Replay Job
// ---------------------------------------------------------------------------

export interface ReplayRequest {
  sport?: string;
  model_id: string;
  model_type?: string;
  date_start?: string;
  date_end?: string;
  game_count?: number;
  rolling_window?: number;
  probability_mode?: string;
  iterations?: number;
  suite_id?: number;
}

export interface ReplayJob {
  id: number;
  sport: string;
  model_id: string;
  model_type: string;
  date_start: string | null;
  date_end: string | null;
  game_count_requested: number | null;
  rolling_window: number;
  probability_mode: string;
  iterations: number;
  suite_id: number | null;
  status: string;
  celery_task_id: string | null;
  game_count: number | null;
  results: Record<string, unknown>[] | null;
  metrics: Record<string, number> | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

// ---------------------------------------------------------------------------
// Team Profile
// ---------------------------------------------------------------------------

export interface TeamProfileResponse {
  team: string;
  games_used: number;
  date_range: [string | null, string | null];
  season_breakdown: Record<string, number>;
  metrics: Record<string, number>;
  baselines: Record<string, number>;
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
  artifact_status?: "valid" | "missing" | "no_path";
}

export interface ModelsListResponse {
  models: RegisteredModel[];
  count: number;
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
  home_win_probability?: number;
  away_win_probability?: number;
  average_home_score?: number;
  average_away_score?: number;
  probability_source?: string;
  has_profiles?: boolean;
  error?: string;
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
