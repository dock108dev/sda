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
