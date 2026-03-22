import { request } from "./client";

export interface SeasonAuditResponse {
  leagueCode: string;
  season: number;
  seasonType: string;

  totalGames: number;
  expectedGames: number | null;
  coveragePct: number | null;

  withBoxscore: number;
  withPlayerStats: number;
  withOdds: number;
  withPbp: number;
  withSocial: number;
  withFlow: number;
  withAdvancedStats: number;

  boxscorePct: number;
  playerStatsPct: number;
  oddsPct: number;
  pbpPct: number;
  socialPct: number;
  flowPct: number;
  advancedStatsPct: number;

  teamsWithGames: number;
  expectedTeams: number | null;

  seasonStart: string | null;
  seasonEnd: string | null;
  seasonPctComplete: number | null;
  expectedGamesToDate: number | null;
}

export interface SeasonAuditParams {
  league: string;
  season: number;
  seasonType?: string;
}

export async function getSeasonAudit(params: SeasonAuditParams): Promise<SeasonAuditResponse> {
  const query = new URLSearchParams();
  query.append("league", params.league);
  query.append("season", String(params.season));
  if (params.seasonType) query.append("seasonType", params.seasonType);
  return request(`/api/admin/sports/season-audit?${query.toString()}`);
}
