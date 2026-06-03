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
