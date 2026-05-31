/**
 * Consumer game API client — calls /api/v1/ endpoints.
 *
 * Use this in consumer-facing code. Admin tooling should use the
 * sportsAdmin client directly (web/src/lib/api/sportsAdmin/games.ts).
 */

import { createClient } from "./client";
import type { ScoreObject } from "../types";

export type { ScoreObject };

// ---------------------------------------------------------------------------
// Catch-up list/detail types (mirror /api/v1/games and /api/v1/games/{game_id})
// ---------------------------------------------------------------------------

export type LiveSnapshot = {
  periodLabel?: string | null;
  timeLabel?: string | null;
  score?: ScoreObject | null;
  currentPeriod?: number | null;
  gameClock?: string | null;
};

export type NormalizedStat = {
  key: string;
  displayLabel: string;
  group: string;
  value?: number | string | null;
  formatType: string;
};

export type TeamStat = {
  team: string;
  isHome: boolean;
  stats: Record<string, unknown>;
  source?: string | null;
  updatedAt?: string | null;
  normalizedStats?: NormalizedStat[] | null;
};

export type PlayerStat = {
  team: string;
  playerName: string;
  minutes?: number | null;
  points?: number | null;
  rebounds?: number | null;
  assists?: number | null;
  rawStats: Record<string, unknown>;
  source?: string | null;
  updatedAt?: string | null;
  normalizedStats?: NormalizedStat[] | null;
};

export type PlayModeEligibility = {
  important: boolean;
  standard: boolean;
  all: boolean;
};

export type PlayImportance = {
  level: "primary" | "secondary" | "tertiary";
  rank?: number | null;
  reasons: string[];
  isKeyMoment: boolean;
  isScoringPlay: boolean;
  isLeadChange: boolean;
  isTyingPlay: boolean;
  isLateGame: boolean;
  isFinalPlay: boolean;
  isRunEnding: boolean;
};

export type PlayEntry = {
  playIndex: number;
  quarter?: number | null;
  gameClock?: string | null;
  periodLabel?: string | null;
  timeLabel?: string | null;
  periodType?: string | null;
  playType?: string | null;
  teamAbbreviation?: string | null;
  playerName?: string | null;
  description?: string | null;
  score?: ScoreObject | null;
  tier?: number | null;
  displayType?: string | null;
  clockLabel?: string | null;
  importance?: PlayImportance | null;
  modeEligibility?: PlayModeEligibility | null;
  scoreChanged?: boolean | null;
  scoringTeamAbbr?: string | null;
  pointsScored?: number | null;
  scoreBefore?: ScoreObject | null;
  scoreAfter?: ScoreObject | null;
  scoreDisplay?: string | null;
  phase?: string | null;
};

export type CatchupGameSummary = {
  id: number;
  leagueCode: string;
  gameDate: string;
  localGameDate?: string | null;
  homeTeam: string;
  awayTeam: string;
  homeTeamAbbr?: string | null;
  awayTeamAbbr?: string | null;
  status?: string | null;
  currentPeriod?: number | null;
  gameClock?: string | null;
  currentPeriodLabel?: string | null;
  liveSnapshot?: LiveSnapshot | null;
  hasBoxscore: boolean;
  hasPlayerStats: boolean;
  hasPbp: boolean;
  playCount: number;
  context: string[];
  contextSource: string;
  isLive: boolean;
  isFinal: boolean;
  isPregame: boolean;
};

export type CatchupGameListResponse = {
  games: CatchupGameSummary[];
  total: number;
  nextOffset?: number | null;
  withBoxscoreCount: number;
  withPlayerStatsCount: number;
  withPbpCount: number;
};

export type CatchupGameMeta = CatchupGameSummary & {
  season: number;
  seasonType?: string | null;
  homeTeamId?: number | null;
  awayTeamId?: number | null;
  score?: ScoreObject | null;
  lastScrapedAt?: string | null;
  lastIngestedAt?: string | null;
  lastPbpAt?: string | null;
  lastBoxscoreAt?: string | null;
};

export type CatchupGameDetailResponse = {
  detailContractVersion: number;
  game: CatchupGameMeta;
  plays: PlayEntry[];
  playerStats: PlayerStat[];
  teamStats: TeamStat[];
};

// ---------------------------------------------------------------------------
// Game summary types (mirror GameSummaryResponse on the backend, v3-summary)
// ---------------------------------------------------------------------------

export type SummaryFinalScore = {
  home: number;
  away: number;
  homeAbbr?: string | null;
  awayAbbr?: string | null;
};

/** Response from GET /api/v1/games/{gameId}/summary.
 *
 * `summary` is a 3-5 paragraph narrative recap. `referencedPlayIds` are the
 * `play_index` values of the plays the recap actually leans on, so catch-up
 * cards can link back. */
export type GameSummaryResponse = {
  gameId: number;
  sport: string;
  finalScore: SummaryFinalScore;
  summary: string[];
  referencedPlayIds: number[];
  archetype: string | null;
  generatedAt: string;
  modelUsed: string | null;
  storyVersion: string;
  homeTeam: string | null;
  awayTeam: string | null;
  leagueCode: string | null;
};

export type FlowStatusResponse = {
  gameId: number;
  status: "RECAP_PENDING" | "IN_PROGRESS" | "PREGAME" | "SCHEDULED" | "POSTPONED" | "CANCELED";
  etaMinutes?: number | null;
};

// ---------------------------------------------------------------------------
// API function
// ---------------------------------------------------------------------------

/**
 * Fetch the consumer game summary from /api/v1/games/{gameId}/summary.
 *
 * Returns null only on 404 (game not found).
 * Returns FlowStatusResponse when summary is not yet available.
 * Returns GameSummaryResponse when summary is ready.
 */
export async function fetchGameSummary(
  gameId: number,
  baseURL?: string,
): Promise<GameSummaryResponse | FlowStatusResponse | null> {
  const client = createClient(baseURL);
  try {
    return await client.get<GameSummaryResponse | FlowStatusResponse>(
      `/api/v1/games/${gameId}/summary`,
    );
  } catch (err: unknown) {
    if (
      err instanceof Error &&
      "statusCode" in err &&
      (err as { statusCode: number }).statusCode === 404
    ) {
      return null;
    }
    throw err;
  }
}
