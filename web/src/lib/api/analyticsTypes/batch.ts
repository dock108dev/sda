import type { ScoreEntry } from "./simulation";

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
  model_id?: string;
}

export interface BatchSimSummary {
  avg_runs_per_team: number;
  avg_total_per_game: number;
  avg_pa_per_team: number | null;
  home_win_rate: number;
  wp_distribution?: Record<string, number>;
}

export interface EventPARates {
  k_pct: number;
  bb_pct: number;
  single_pct: number;
  double_pct: number;
  triple_pct: number;
  hr_pct: number;
  out_pct: number;
}

// Sport-aware event team summary — shape depends on sport
export interface EventTeamSummary {
  // MLB fields
  avg_pa?: number;
  avg_hits?: number;
  avg_hr?: number;
  avg_bb?: number;
  avg_k?: number;
  avg_runs?: number;
  pa_rates?: EventPARates;
  // NBA/NCAAB fields
  avg_possessions?: number;
  avg_points?: number;
  fg_pct?: number;
  fg3_pct?: number;
  efg_pct?: number;
  avg_orb?: number;
  // NHL fields
  avg_shots?: number;
  avg_goals?: number;
  shooting_pct?: number;
  // NFL fields
  avg_drives?: number;
  avg_tds?: number;
  avg_fgs?: number;
  scoring_drive_pct?: number;
  // All sports: sport-specific rate breakdown
  rates?: Record<string, number>;
}

export interface EventGameSummary {
  avg_total?: number;
  median_total?: number;
  one_score_game_pct?: number;
  // MLB
  avg_total_runs?: number;
  median_total_runs?: number;
  extra_innings_pct?: number;
  shutout_pct?: number;
  one_run_game_pct?: number;
  // NBA/NCAAB/NHL/NFL
  overtime_pct?: number;
  shootout_pct?: number;
}

export interface EventSummary {
  home: EventTeamSummary;
  away: EventTeamSummary;
  game: EventGameSummary;
  sport?: string;
}


export interface BatterLine {
  name: string;
  K: number;
  BB: number;
  "1B": number;
  "2B": number;
  "3B": number;
  HR: number;
  BIP: number;
}

export interface PitcherLine {
  name: string;
  external_ref: string;
  k_rate?: number;
  bb_rate?: number;
  hr_rate?: number;
  whiff_rate?: number;
}

export interface LineupInfo {
  home_batting: BatterLine[];
  away_batting: BatterLine[];
  home_starter?: PitcherLine;
  away_starter?: PitcherLine;
}

export interface LineAnalysis {
  market_home_ml: number;
  market_away_ml: number;
  market_home_wp: number;
  market_away_wp: number;
  model_home_wp: number;
  model_away_wp: number;
  home_edge: number;
  away_edge: number;
  model_home_line: number;
  model_away_line: number;
  home_ev_pct: number;
  away_ev_pct: number;
  provider: string;
  line_type: "closing" | "current";
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
  event_summary?: EventSummary;
  lineup_info?: LineupInfo;
  line_analysis?: LineAnalysis;
  // Projected box score detail
  score_distribution?: Record<string, number>;
  most_common_scores?: ScoreEntry[];
  home_wp_std_dev?: number;
  score_std_home?: number;
  score_std_away?: number;
  iterations?: number;
  profile_games_home?: number;
  profile_games_away?: number;
  feature_snapshot?: {
    home?: Record<string, number>;
    away?: Record<string, number>;
  };
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
  batch_summary?: BatchSimSummary;
  warnings?: string[];
}
