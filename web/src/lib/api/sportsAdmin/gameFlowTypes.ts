/**
 * Game Summary types (v3-summary).
 *
 * READ-ONLY views of the catch-up summary returned by
 * GET /api/v1/games/{gameId}/summary.
 */

export type ScoreObject = {
  home: number;
  away: number;
};

export type SummaryFinalScore = {
  home: number;
  away: number;
  homeAbbr?: string | null;
  awayAbbr?: string | null;
};

/**
 * Response from GET /api/v1/games/{gameId}/summary.
 *
 * `summary` is a 3-5 paragraph narrative recap. `referencedPlayIds` are the
 * play_index values of the plays the recap actually leans on, so catch-up
 * cards can link back.
 */
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

/**
 * Returned when a summary is not yet available for a game.
 */
export type FlowStatusResponse = {
  gameId: number;
  status: "RECAP_PENDING" | "IN_PROGRESS" | "PREGAME" | "SCHEDULED" | "POSTPONED" | "CANCELED";
  etaMinutes?: number | null;
};
