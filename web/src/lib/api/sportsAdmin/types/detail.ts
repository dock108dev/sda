import type { ScoreObject } from "../gameFlowTypes";
import type {
  MLBAdvancedPlayerStats,
  MLBAdvancedTeamStats,
  MLBBatterStat,
  MLBFieldingStat,
  MLBPitcherGameStat,
  MLBPitcherStat,
  NBAAdvancedPlayerStats,
  NBAAdvancedTeamStats,
  NCAABAdvancedPlayerStats,
  NCAABAdvancedTeamStats,
  NFLAdvancedPlayerStats,
  NFLAdvancedTeamStats,
  NHLAdvancedTeamStats,
  NHLGoalieAdvancedStats,
  NHLGoalieStat,
  NHLSkaterAdvancedStats,
  NHLSkaterStat,
  PlayerStat,
  TeamStat,
} from "./stats";

export type OddsEntry = {
  book: string;
  marketType: string;
  marketCategory: string;
  playerName: string | null;
  description: string | null;
  side: string | null;
  line: number | null;
  price: number | null;
  isClosingLine: boolean;
  observedAt: string | null;
};

export type SocialPost = {
  id: number;
  postUrl: string;
  postedAt: string;
  hasVideo: boolean;
  teamAbbreviation: string;
  tweetText: string | null;
  videoUrl: string | null;
  imageUrl: string | null;
  sourceHandle: string | null;
  mediaType: string | null;
};

export type PlayEntry = {
  playIndex: number;
  quarter: number | null;
  gameClock: string | null;
  periodLabel: string | null;
  timeLabel: string | null;
  periodType: string | null;
  playType: string | null;
  teamAbbreviation: string | null;
  playerName: string | null;
  description: string | null;
  score: ScoreObject | null;
  scoreBefore: ScoreObject | null;
  tier: number | null;
};

export type TieredPlayGroup = {
  startIndex: number;
  endIndex: number;
  playIndices: number[];
  summaryLabel: string;
};

export type ScrollDownMlbDebugFinding = {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  playId: string | null;
  scope: string | null;
};

export type ScrollDownMlbHalfInningDebug = {
  inning: number;
  half: "top" | "bottom";
  battingTeam: string;
  fieldingTeam: string;
  eventCount: number;
  selectedCount: number;
  scoredRuns: number;
  hadActivity: boolean;
  hadLeadChange: boolean;
  hadTying: boolean;
  minPlayIndex: number | null;
  maxPlayIndex: number | null;
  status: "ok" | "warning" | "error";
  findings: ScrollDownMlbDebugFinding[];
};

export type ScrollDownMlbDebugResponse = {
  available: boolean;
  status: "available" | "not_available" | "blocked";
  reason: string | null;
  policy: "live" | "official" | null;
  deckVersion: string | null;
  isFinal: boolean | null;
  cardCount: number;
  lastPlayIndex: number | null;
  halfInningCount: number;
  eventCount: number;
  selectedEventCount: number;
  warnings: ScrollDownMlbDebugFinding[];
  errors: ScrollDownMlbDebugFinding[];
  halfInnings: ScrollDownMlbHalfInningDebug[];
  deck: Record<string, unknown> | null;
};

export type AdminGameDetail = {
  game: {
    id: number;
    leagueCode: string;
    season: number;
    seasonType: string | null;
    gameDate: string;
    homeTeam: string;
    awayTeam: string;
    homeTeamId: number | null;
    awayTeamId: number | null;
    score: ScoreObject | null;
    status: string;
    scrapeVersion: number | null;
    lastScrapedAt: string | null;
    lastIngestedAt: string | null;
    lastPbpAt: string | null;
    lastSocialAt: string | null;
    lastOddsAt: string | null;
    lastAdvancedStatsAt: string | null;
    hasBoxscore: boolean;
    hasPlayerStats: boolean;
    hasOdds: boolean;
    hasSocial: boolean;
    hasPbp: boolean;
    hasFlow: boolean;
    hasAdvancedStats: boolean;
    playCount: number;
    socialPostCount: number;
    isLive: boolean;
    isFinal: boolean;
    isPregame: boolean;
  };
  teamStats: TeamStat[];
  playerStats: PlayerStat[];
  // NHL-specific player stats (only populated for NHL games)
  nhlSkaters?: NHLSkaterStat[] | null;
  nhlGoalies?: NHLGoalieStat[] | null;
  // MLB-specific player stats (only populated for MLB games)
  mlbBatters?: MLBBatterStat[] | null;
  mlbPitchers?: MLBPitcherStat[] | null;
  mlbAdvancedStats?: MLBAdvancedTeamStats[] | null;
  mlbAdvancedPlayerStats?: MLBAdvancedPlayerStats[] | null;
  mlbPitcherGameStats?: MLBPitcherGameStat[] | null;
  mlbFieldingStats?: MLBFieldingStat[] | null;
  nbaAdvancedStats?: NBAAdvancedTeamStats[] | null;
  nbaPlayerAdvancedStats?: NBAAdvancedPlayerStats[] | null;
  nhlAdvancedStats?: NHLAdvancedTeamStats[] | null;
  nhlSkaterAdvancedStats?: NHLSkaterAdvancedStats[] | null;
  nhlGoalieAdvancedStats?: NHLGoalieAdvancedStats[] | null;
  nflAdvancedStats?: NFLAdvancedTeamStats[] | null;
  nflPlayerAdvancedStats?: NFLAdvancedPlayerStats[] | null;
  ncaabAdvancedStats?: NCAABAdvancedTeamStats[] | null;
  ncaabPlayerAdvancedStats?: NCAABAdvancedPlayerStats[] | null;
  odds: OddsEntry[];
  socialPosts: SocialPost[];
  plays: PlayEntry[];
  groupedPlays: TieredPlayGroup[] | null;
  derivedMetrics: Record<string, unknown>;
  rawPayloads: Record<string, unknown>;
};
