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

export interface ProjectedLineupSlot {
  external_ref: string;
  name: string;
}

export interface MLBRosterResponse {
  batters: RosterBatter[];
  pitchers: RosterPitcher[];
  projected_lineup?: ProjectedLineupSlot[];
  probable_starter?: ProjectedLineupSlot;
  error?: string;
}
