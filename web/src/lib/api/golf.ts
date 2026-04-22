/** API client functions for golf data endpoints. */

import { request } from "./sportsAdmin/client";
import type {
  GolfTournament,
  GolfPlayer,
  GolfFieldEntry,
  GolfLeaderboardEntry,
  GolfRound,
  GolfOddsEntry,
  GolfDFSProjection,
  GolfPlayerStats,
  UpcomingTournament,
} from "./golfTypes";
import type { TriggerTaskResponse } from "./sportsAdmin/taskControl";

// ── Tournaments ──

export interface TournamentFilters {
  tour?: string;
  season?: number;
  status?: string;
  limit?: number;
}

export async function listUpcomingTournaments(
  daysAhead?: number
): Promise<UpcomingTournament[]> {
  const query = new URLSearchParams();
  if (daysAhead != null) query.append("days_ahead", String(daysAhead));
  const qs = query.toString();
  const res = await request<{ tournaments: UpcomingTournament[]; count: number }>(
    `/api/golf/tournaments/upcoming${qs ? `?${qs}` : ""}`
  );
  return res.tournaments;
}

export async function listTournaments(
  params?: TournamentFilters
): Promise<GolfTournament[]> {
  const query = new URLSearchParams();
  if (params?.tour) query.append("tour", params.tour);
  if (params?.season != null) query.append("season", String(params.season));
  if (params?.status) query.append("status", params.status);
  if (params?.limit != null) query.append("limit", String(params.limit));
  const qs = query.toString();
  const res = await request<{ tournaments: GolfTournament[]; count: number }>(
    `/api/golf/tournaments${qs ? `?${qs}` : ""}`
  );
  return res.tournaments;
}

export async function fetchTournament(
  eventId: string
): Promise<GolfTournament> {
  return request(`/api/golf/tournaments/${eventId}`);
}

export async function fetchTournamentField(
  eventId: string
): Promise<{ field?: GolfFieldEntry[]; buckets?: unknown[]; count?: number }> {
  return request(`/api/golf/tournaments/${eventId}/field`);
}

export async function addFieldPlayer(
  eventId: string,
  playerName: string
): Promise<{ status: string; dg_id: number; player_name: string }> {
  return request(`/api/golf/tournaments/${eventId}/field`, {
    method: "POST",
    body: JSON.stringify({ player_name: playerName }),
  });
}

export async function removeFieldPlayer(
  eventId: string,
  dgId: number
): Promise<{ status: string; dg_id: number; player_name: string }> {
  return request(`/api/golf/tournaments/${eventId}/field/${dgId}`, {
    method: "DELETE",
  });
}

export async function fetchTournamentLeaderboard(
  eventId: string
): Promise<GolfLeaderboardEntry[]> {
  const res = await request<{ leaderboard: GolfLeaderboardEntry[]; count: number }>(
    `/api/golf/tournaments/${eventId}/leaderboard`
  );
  return res.leaderboard;
}

export async function fetchTournamentRounds(
  eventId: string,
  roundNum?: number
): Promise<GolfRound[]> {
  const query = new URLSearchParams();
  if (roundNum != null) query.append("round_num", String(roundNum));
  const qs = query.toString();
  const res = await request<{ rounds: GolfRound[]; count: number }>(
    `/api/golf/tournaments/${eventId}/rounds${qs ? `?${qs}` : ""}`
  );
  return res.rounds;
}

// ── Players ──

export async function searchPlayers(
  q: string,
  limit?: number
): Promise<GolfPlayer[]> {
  const query = new URLSearchParams({ q });
  if (limit != null) query.append("limit", String(limit));
  const res = await request<{ players: GolfPlayer[]; count: number }>(
    `/api/golf/players?${query.toString()}`
  );
  return res.players;
}

export async function fetchPlayer(dgId: number): Promise<GolfPlayer> {
  return request(`/api/golf/players/${dgId}`);
}

export async function fetchPlayerStats(
  dgId: number
): Promise<GolfPlayerStats[]> {
  const res = await request<{ stats: GolfPlayerStats[]; count: number }>(
    `/api/golf/players/${dgId}/stats`
  );
  return res.stats;
}

// ── Odds ──

export interface OddsFilters {
  tournament_id?: number;
  market?: string;
  book?: string;
}

export async function fetchOutrightOdds(
  params?: OddsFilters
): Promise<GolfOddsEntry[]> {
  const query = new URLSearchParams();
  if (params?.tournament_id != null)
    query.append("tournament_id", String(params.tournament_id));
  if (params?.market) query.append("market", params.market);
  if (params?.book) query.append("book", params.book);
  const qs = query.toString();
  const res = await request<{ odds: GolfOddsEntry[]; count: number }>(
    `/api/golf/odds/outrights${qs ? `?${qs}` : ""}`
  );
  return res.odds;
}

// ── DFS ──

export interface DFSFilters {
  tournament_id?: number;
  site?: string;
}

export async function fetchDFSProjections(
  params?: DFSFilters
): Promise<GolfDFSProjection[]> {
  const query = new URLSearchParams();
  if (params?.tournament_id != null)
    query.append("tournament_id", String(params.tournament_id));
  if (params?.site) query.append("site", params.site);
  const qs = query.toString();
  const res = await request<{ projections: GolfDFSProjection[]; count: number }>(
    `/api/golf/dfs/projections${qs ? `?${qs}` : ""}`
  );
  return res.projections;
}

// ── Admin triggers ──

export async function triggerGolfSync(
  taskName: string
): Promise<TriggerTaskResponse> {
  return request("/api/admin/tasks/trigger", {
    method: "POST",
    body: JSON.stringify({ task_name: taskName, args: [] }),
  });
}
