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
