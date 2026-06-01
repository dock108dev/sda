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

export type NHLSkaterStat = {
  team: string;
  playerName: string;
  toi?: string | null;
  goals?: number | null;
  assists?: number | null;
  points?: number | null;
  shotsOnGoal?: number | null;
  plusMinus?: number | null;
  penaltyMinutes?: number | null;
  hits?: number | null;
  blockedShots?: number | null;
  rawStats: Record<string, unknown>;
  source?: string | null;
  updatedAt?: string | null;
};

export type NHLGoalieStat = {
  team: string;
  playerName: string;
  toi?: string | null;
  shotsAgainst?: number | null;
  saves?: number | null;
  goalsAgainst?: number | null;
  savePercentage?: number | null;
  rawStats: Record<string, unknown>;
  source?: string | null;
  updatedAt?: string | null;
};

export type MLBBatterStat = {
  team: string;
  playerName: string;
  position?: string | null;
  atBats?: number | null;
  hits?: number | null;
  runs?: number | null;
  rbi?: number | null;
  homeRuns?: number | null;
  baseOnBalls?: number | null;
  strikeOuts?: number | null;
  stolenBases?: number | null;
  avg?: string | null;
  obp?: string | null;
  slg?: string | null;
  ops?: string | null;
  rawStats: Record<string, unknown>;
  source?: string | null;
  updatedAt?: string | null;
};

export type MLBPitcherStat = {
  team: string;
  playerName: string;
  inningsPitched?: string | null;
  hits?: number | null;
  runs?: number | null;
  earnedRuns?: number | null;
  baseOnBalls?: number | null;
  strikeOuts?: number | null;
  homeRuns?: number | null;
  era?: string | null;
  pitchCount?: number | null;
  strikes?: number | null;
  rawStats: Record<string, unknown>;
  source?: string | null;
  updatedAt?: string | null;
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

export type PlaySituation = {
  display?: Record<string, unknown> | null;
  sportState?: Record<string, unknown> | null;
  [key: string]: unknown;
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
  situationBefore?: PlaySituation | null;
  situationAfter?: PlaySituation | null;
  sportMetadata?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  rawFeedText?: string | null;
  rawFeedSource?: string | null;
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
  estimatedReadingMinutes?: number | null;
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
  nhlSkaters?: NHLSkaterStat[] | null;
  nhlGoalies?: NHLGoalieStat[] | null;
  mlbBatters?: MLBBatterStat[] | null;
  mlbPitchers?: MLBPitcherStat[] | null;
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
// Normalized card-feed types (mirror /api/v1/feed/games/{gameId}/cards)
// ---------------------------------------------------------------------------

export type CardFeedStatus =
  | "ready"
  | "no_pbp_yet"
  | "unsupported_sport"
  | "generation_pending"
  | "validation_blocked"
  | "stale_regenerating";

export type CardFieldSpoilerLevel = "none" | "earnedAtPlay" | "revealOnly";

export type ScoreRevealBoundary = "allowed" | "hidden_until_reveal" | "unavailable";

export type CompletedGameRevealBoundary = {
  finalScore: ScoreRevealBoundary;
  winner: ScoreRevealBoundary;
  stats: ScoreRevealBoundary;
  payoffCopy: ScoreRevealBoundary;
};

export type RevealAvailability = {
  available: boolean;
  status: "ready" | "unavailable" | "not_final";
  scoresInCards: boolean;
  revealRequiredForScores: boolean;
  completedGameBoundary?: CompletedGameRevealBoundary | null;
};

export type CardFeedGeneration = {
  status: CardFeedStatus;
  cardCount: number;
  lastPlayIndex?: number | null;
  generatedAt?: string | null;
  isStale: boolean;
  validationIssues: string[];
};

export type CardFeedGameMetadata = {
  gameId: number;
  sport: string;
  league: string;
  status?: string | null;
  homeTeam?: string | null;
  awayTeam?: string | null;
  homeTeamId?: number | null;
  awayTeamId?: number | null;
  homeTeamAbbr?: string | null;
  awayTeamAbbr?: string | null;
};

export type CardPeriod = {
  ordinal?: number | null;
  label?: string | null;
  type?: string | null;
};

export type CardTeam = {
  abbreviation?: string | null;
  name?: string | null;
  side: "home" | "away" | "neutral" | "unknown" | string;
};

export type ScoreChange = {
  home: number;
  away: number;
};

export type CardSituation = {
  summary?: string | null;
  raw?: Record<string, unknown> | null;
};

export type CardTextSpoilerLevels = {
  leadIn: CardFieldSpoilerLevel;
  stageSetting: CardFieldSpoilerLevel;
  headline: CardFieldSpoilerLevel;
  description: CardFieldSpoilerLevel;
  impact?: CardFieldSpoilerLevel | null;
  situationSummary?: CardFieldSpoilerLevel | null;
  tags: CardFieldSpoilerLevel;
};

export type NarrativeCard = {
  id: string;
  gameId: number;
  sourcePlayId: string;
  playIndex: number;
  sport: string;
  league: string;
  tier: number;
  contentDepth: "extended" | "standard" | "brief" | string;
  modeEligibility: PlayModeEligibility;
  importance: PlayImportance;
  visualImportance: "critical" | "high" | "medium" | "low";
  period: CardPeriod;
  displayTime?: string | null;
  clock?: string | null;
  team: CardTeam;
  scoreBefore?: ScoreObject | null;
  scoreChange?: ScoreChange | null;
  scoreAfter?: ScoreObject | null;
  situation: CardSituation;
  leadIn: string;
  stageSetting: string;
  headline: string;
  description: string;
  impact?: string | null;
  tags: string[];
  spoilerLevel: "none" | "score_revealed" | string;
  textFieldSpoilerLevels: CardTextSpoilerLevels;
};

export type CardSectionLeadIn = {
  id: string;
  kind: "period" | string;
  ordinal?: number | null;
  period: CardPeriod;
  label: string;
  title: string;
  leadIn: string;
  startPlayIndex: number;
  endPlayIndex: number;
  textFieldSpoilerLevel: CardFieldSpoilerLevel;
  source: "deterministic" | string;
};

export type CardFeedResponse = {
  contractVersion: number;
  game: CardFeedGameMetadata;
  spoilerPolicy: "pre_reveal" | "revealed" | string;
  generation: CardFeedGeneration;
  reveal: RevealAvailability;
  sections: CardSectionLeadIn[];
  cards: NarrativeCard[];
};

export type CardGenerationDebugFinding = {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  playId?: string | null;
  scope?: string | null;
};

export type CardGenerationDebugResponse = {
  available: boolean;
  status: "available" | "not_available" | "blocked";
  reason?: string | null;
  policy?: "live" | "official" | null;
  cardCount: number;
  lastPlayIndex?: number | null;
  generationVersion?: string | null;
  sourceHash?: string | null;
  cacheState: string;
  warnings: CardGenerationDebugFinding[];
  errors: CardGenerationDebugFinding[];
  feed?: CardFeedResponse | Record<string, unknown> | null;
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
