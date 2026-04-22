export interface UpcomingTournament {
  tournament_id: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  field_available: boolean;
}

export interface GolfTournament {
  id: number;
  event_id: string;
  tour: string;
  event_name: string;
  course: string | null;
  start_date: string;
  end_date: string | null;
  season: number | null;
  purse: number | null;
  country: string | null;
  status: string;
  current_round: number | null;
}

export interface GolfPlayer {
  id: number;
  dg_id: number;
  player_name: string;
  country: string | null;
  amateur: boolean;
}

export interface GolfFieldEntry {
  dg_id: number;
  player_name: string | null;
  status: string;
  tee_time_r1: string | null;
  tee_time_r2: string | null;
  dk_salary: number | null;
  fd_salary: number | null;
}

export interface GolfLeaderboardEntry {
  dg_id: number;
  player_name: string | null;
  position: number | null;
  total_score: number | null;
  today_score: number | null;
  thru: number | null;
  r1: number | null;
  r2: number | null;
  r3: number | null;
  r4: number | null;
  status: string;
  sg_total: number | null;
  win_prob: number | null;
}

export interface GolfRound {
  dg_id: number;
  round_num: number;
  score: number | null;
  strokes: number | null;
  sg_total: number | null;
  sg_ott: number | null;
  sg_app: number | null;
  sg_arg: number | null;
  sg_putt: number | null;
}

export interface GolfOddsEntry {
  dg_id: number;
  player_name: string | null;
  book: string;
  market: string;
  odds: number;
  dg_prob: number | null;
}

export interface GolfDFSProjection {
  dg_id: number;
  player_name: string | null;
  site: string;
  salary: number | null;
  projected_points: number | null;
  projected_ownership: number | null;
}

export interface GolfPlayerStats {
  dg_id: number;
  period: string;
  sg_total: number | null;
  sg_ott: number | null;
  sg_app: number | null;
  sg_arg: number | null;
  sg_putt: number | null;
  dg_rank: number | null;
  owgr: number | null;
}
