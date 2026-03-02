/**
 * Game Flow Types
 *
 * TypeScript definitions for Game Flow API responses.
 * These types are READ-ONLY views of Game Flow data.
 * The UI must not modify, augment, or interpret these structures.
 */

// =============================================================================
// Game Flow API Types (GET /games/{game_id}/flow)
// =============================================================================

/**
 * Player stat entry in cumulative box score.
 */
export type MomentPlayerStat = {
  name: string;
  // Basketball stats
  pts?: number | null;
  reb?: number | null;
  ast?: number | null;
  "3pm"?: number | null;
  // Hockey stats
  goals?: number | null;
  assists?: number | null;
  sog?: number | null;
  plusMinus?: number | null;
  // Baseball stats
  runs?: number | null;
  hits?: number | null;
  rbi?: number | null;
  hr?: number | null;
  sb?: number | null;
  k?: number | null;
};

/**
 * Goalie stat entry for NHL box score.
 */
export type MomentGoalieStat = {
  name: string;
  saves: number;
  ga: number;
  savePct: number;
};

/**
 * Team box score for a moment.
 */
export type MomentTeamBoxScore = {
  team: string;
  score: number;
  players: MomentPlayerStat[];
  goalie?: MomentGoalieStat | null;
};

/**
 * Cumulative box score at a moment in time.
 */
export type MomentBoxScore = {
  home: MomentTeamBoxScore;
  away: MomentTeamBoxScore;
};

/**
 * A moment in the game flow.
 * Uses camelCase to match API JSON response.
 */
export type GameFlowMoment = {
  playIds: number[];
  explicitlyNarratedPlayIds: number[];
  period: number;
  startClock: string | null;
  endClock: string | null;
  scoreBefore: number[];
  scoreAfter: number[];
  narrative: string | null;  // Narrative is in blocks, not moments
  cumulativeBoxScore?: MomentBoxScore | null;
};

/**
 * A play referenced by a game flow moment.
 * Uses camelCase to match API JSON response.
 *
 * IMPORTANT: playId equals playIndex (not a database ID).
 * To join moments to plays: plays.filter(p => moment.playIds.includes(p.playId))
 */
export type GameFlowPlay = {
  /** Play identifier - equals playIndex for joining with moment.playIds */
  playId: number;
  /** Sequential play number in the game */
  playIndex: number;
  period: number;
  clock: string | null;
  playType: string | null;
  description: string | null;
  homeScore: number | null;
  awayScore: number | null;
};

/**
 * Game flow content containing ordered moments.
 */
export type GameFlowContent = {
  moments: GameFlowMoment[];
};

/**
 * Response from GET /games/{game_id}/flow endpoint.
 * Returns the persisted game flow data.
 */
export type GameFlowResponse = {
  gameId: number;
  flow: GameFlowContent;
  plays: GameFlowPlay[];
  validationPassed: boolean;
  validationErrors: string[];
  /** Narrative blocks (4-7 blocks with narratives) */
  blocks?: NarrativeBlock[];
  /** Total word count across all block narratives */
  totalWords?: number;
};

// =============================================================================
// Block-based Narrative Types
// =============================================================================

/**
 * Semantic role for a narrative block.
 * Describes the block's function in the game's narrative arc.
 */
export type SemanticRole =
  | "SETUP"
  | "MOMENTUM_SHIFT"
  | "RESPONSE"
  | "DECISION_POINT"
  | "RESOLUTION";

/**
 * Player stat with delta showing segment production.
 */
export type BlockPlayerStat = {
  name: string;
  // Basketball stats (cumulative)
  pts?: number;
  reb?: number;
  ast?: number;
  "3pm"?: number;
  fgm?: number;
  ftm?: number;
  // Basketball deltas (this block's production)
  deltaPts?: number;
  deltaReb?: number;
  deltaAst?: number;
  // Hockey stats (cumulative)
  goals?: number;
  assists?: number;
  sog?: number;
  plusMinus?: number;
  // Hockey deltas
  deltaGoals?: number;
  deltaAssists?: number;
  // Baseball stats (cumulative)
  runs?: number;
  hits?: number;
  rbi?: number;
  hr?: number;
  sb?: number;
  k?: number;
  // Baseball deltas
  deltaRuns?: number;
  deltaHits?: number;
  deltaRbi?: number;
};

/**
 * Team mini box score for a block.
 */
export type BlockTeamMiniBox = {
  team: string;
  players: BlockPlayerStat[];
};

/**
 * Mini box score for a block with cumulative stats and segment deltas.
 */
export type BlockMiniBox = {
  home: BlockTeamMiniBox;
  away: BlockTeamMiniBox;
  /** Top contributors in this segment (last names) */
  blockStars: string[];
};

/**
 * A narrative block in the collapsed game flow.
 * Replaces moment-level narratives with 1-2 sentences.
 */
export type NarrativeBlock = {
  blockIndex: number;
  role: SemanticRole;
  momentIndices: number[];
  periodStart: number;
  periodEnd: number;
  scoreBefore: number[];
  scoreAfter: number[];
  playIds: number[];
  keyPlayIds: number[];
  narrative: string | null;
  embeddedSocialPostId?: number | null;
  /** Cumulative box score with segment deltas */
  miniBox?: BlockMiniBox | null;
};

/**
 * Social post for expandable sections.
 * Categorized by phase for organization.
 */
export type CategorizedSocialPost = {
  id: string | number;
  text: string;
  author: string;
  postedAt: string;
  phase: string;
  segment?: string | null;
  hasMedia: boolean;
  mediaType?: string | null;
  postUrl?: string;
};

/**
 * Grouped social posts for expandable sections.
 */
export type SocialPostsByPhase = {
  pregame: CategorizedSocialPost[];
  inGame: Record<string, CategorizedSocialPost[]>; // Keyed by segment (q1, q2, etc.)
  postgame: CategorizedSocialPost[];
};

/**
 * Response for block-based game flow.
 */
export type BlockGameFlowResponse = {
  gameId: number;
  leagueCode: string;
  blocks: NarrativeBlock[];
  totalWords: number;
  socialPosts?: SocialPostsByPhase;
  validationPassed: boolean;
  validationErrors: string[];
};
