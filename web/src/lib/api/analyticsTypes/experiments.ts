import type { SimulationRequest } from "./simulation";

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
    probability_modes?: SimulationRequest["probability_mode"][];
    blend_alphas?: number[];
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
