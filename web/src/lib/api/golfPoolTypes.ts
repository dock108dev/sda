/** TypeScript types for golf pool API responses. */

export interface GolfPool {
  id: number;
  club_code: string;
  tournament_id: number;
  tournament_name: string | null;
  name: string;
  status: string;
  scoring_enabled: boolean;
  rules: Record<string, unknown> | null;
  entry_deadline: string | null;
  max_entries_per_email: number | null;
  entries_count: number;
  last_scored_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface GolfPoolEntry {
  id: number;
  pool_id: number;
  email: string;
  entry_name: string | null;
  picks_count: number;
  picks?: { dg_id: number; player_name: string; pick_slot: number }[];
  created_at: string;
}

export interface GolfPoolEntryPick {
  id: number;
  entry_id: number;
  dg_id: number;
  player_name: string;
  pick_slot: number;
  bucket_number: number | null;
}

export interface GolfPoolLeaderboardPick {
  dg_id: number;
  player_name: string;
  pick_slot: number;
  bucket_number: number | null;
  status: string;
  position: number | null;
  total_score: number | null;
  thru: number | null;
  r1: number | null;
  r2: number | null;
  r3: number | null;
  r4: number | null;
  made_cut: boolean;
  counts_toward_total: boolean;
  is_dropped: boolean;
}

export interface GolfPoolLeaderboardEntry {
  entry_id: number;
  email: string;
  entry_name: string | null;
  rank: number | null;
  is_tied: boolean;
  aggregate_score: number | null;
  qualified_golfers_count: number;
  counted_golfers_count: number;
  qualification_status: string;
  is_complete: boolean;
  picks: GolfPoolLeaderboardPick[];
}
