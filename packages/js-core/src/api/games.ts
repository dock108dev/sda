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
