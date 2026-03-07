/**
 * Analytics API client.
 *
 * Calls the FastAPI analytics endpoints via the Next.js proxy.
 */

import { getApiBase } from "./apiBase";

const base = () => getApiBase();

export interface TeamAnalytics {
  sport: string;
  team_id: string;
  name: string;
  metrics: Record<string, number>;
}

export interface PlayerAnalytics {
  sport: string;
  player_id: string;
  name: string;
  metrics: Record<string, number>;
}

export interface MatchupAnalytics {
  sport: string;
  entity_a: string;
  entity_b: string;
  probabilities: Record<string, number>;
  comparison: Record<string, unknown>;
  advantages: Record<string, string>;
}

export interface SimulationRequest {
  sport: string;
  home_team: string;
  away_team: string;
  iterations?: number;
  seed?: number | null;
  home_probabilities?: Record<string, number>;
  away_probabilities?: Record<string, number>;
  sportsbook?: Record<string, unknown>;
}

export interface ScoreEntry {
  score: string;
  probability: number;
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
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function getTeamAnalytics(
  sport: string,
  teamId: string,
): Promise<TeamAnalytics> {
  const params = new URLSearchParams({ sport, team_id: teamId });
  return fetchJson<TeamAnalytics>(`${base()}/api/analytics/team?${params}`);
}

export async function getPlayerAnalytics(
  sport: string,
  playerId: string,
): Promise<PlayerAnalytics> {
  const params = new URLSearchParams({ sport, player_id: playerId });
  return fetchJson<PlayerAnalytics>(`${base()}/api/analytics/player?${params}`);
}

export async function getMatchupAnalytics(
  sport: string,
  entityA: string,
  entityB: string,
): Promise<MatchupAnalytics> {
  const params = new URLSearchParams({ sport, entity_a: entityA, entity_b: entityB });
  return fetchJson<MatchupAnalytics>(`${base()}/api/analytics/matchup?${params}`);
}

export async function runSimulation(
  req: SimulationRequest,
): Promise<SimulationResult> {
  return fetchJson<SimulationResult>(`${base()}/api/analytics/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export interface LiveSimulateRequest {
  sport: string;
  inning: number;
  half: "top" | "bottom";
  outs: number;
  bases: { first: boolean; second: boolean; third: boolean };
  score: { home: number; away: number };
  iterations?: number;
  seed?: number | null;
  home_probabilities?: Record<string, number>;
  away_probabilities?: Record<string, number>;
}

export interface LiveSimulateResult {
  sport: string;
  inning: number;
  half: string;
  score: { home: number; away: number };
  home_win_probability: number;
  away_win_probability: number;
  expected_final_score: { home: number; away: number };
  iterations: number;
}

export async function runLiveSimulation(
  req: LiveSimulateRequest,
): Promise<LiveSimulateResult> {
  return fetchJson<LiveSimulateResult>(`${base()}/api/analytics/live-simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}
