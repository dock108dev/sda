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
// Consumer Game Flow types (mirrors ConsumerGameFlowResponse on the backend)
// ---------------------------------------------------------------------------

export type GameFlowPlay = {
  playId: number;
  playIndex: number;
  period: number;
  clock: string | null;
  playType: string | null;
  description: string | null;
  score: ScoreObject | null;
};

/** Mini box score returned in a narrative block. home/away are flexible dicts per the API contract. */
export type BlockMiniBox = {
  home: Record<string, unknown>;
  away: Record<string, unknown>;
  blockStars: string[];
};

export type NarrativeBlock = {
  blockIndex: number;
  role: string;
  momentIndices: number[];
  periodStart: number;
  periodEnd: number;
  scoreBefore: ScoreObject;
  scoreAfter: ScoreObject;
  playIds: number[];
  keyPlayIds: number[];
  narrative: string | null;
  embeddedSocialPostId?: number | null;
  miniBox?: BlockMiniBox | null;
  startClock?: string | null;
  endClock?: string | null;
};

/** Consumer game flow response — blocks are the contract; moments are pipeline-internal. */
export type ConsumerGameFlowResponse = {
  gameId: number;
  plays: GameFlowPlay[];
  blocks: NarrativeBlock[];
  totalWords?: number | null;
  homeTeam?: string | null;
  awayTeam?: string | null;
  homeTeamAbbr?: string | null;
  awayTeamAbbr?: string | null;
  homeTeamColorLight?: string | null;
  homeTeamColorDark?: string | null;
  awayTeamColorLight?: string | null;
  awayTeamColorDark?: string | null;
  leagueCode?: string | null;
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
 * Fetch the consumer game flow from /api/v1/games/{gameId}/flow.
 *
 * Returns null only on 404 (game not found).
 * Returns FlowStatusResponse when flow is not yet available.
 * Returns ConsumerGameFlowResponse when flow is ready.
 */
export async function fetchGameFlow(
  gameId: number,
  baseURL?: string,
): Promise<ConsumerGameFlowResponse | FlowStatusResponse | null> {
  const client = createClient(baseURL);
  try {
    return await client.get<ConsumerGameFlowResponse | FlowStatusResponse>(
      `/api/v1/games/${gameId}/flow`,
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
