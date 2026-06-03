/**
 * Type definitions for the Analytics API client.
 *
 * Extracted from analytics.ts to keep type declarations separate from
 * runtime API logic.
 */

import type { EventSummary } from "./batch";

export interface SimulationRequest {
  sport: string;
  home_team: string;
  away_team: string;
  iterations?: number;
  seed?: number | null;
  home_probabilities?: Record<string, number>;
  away_probabilities?: Record<string, number>;
  sportsbook?: Record<string, unknown>;
  probability_mode?: "rule_based" | "ml" | "ensemble" | "pitch_level" | "market_blend";
  blend_alpha?: number;
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
  event_summary?: EventSummary;
}
