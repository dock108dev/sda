import type { ScoreObject } from "../gameFlowTypes";

export type ScrapeRunConfig = {
  leagueCode?: string;
  season?: number;
  seasonType?: string;
  startDate?: string;
  endDate?: string;
  boxscores?: boolean;
  odds?: boolean;
  social?: boolean;
  pbp?: boolean;
  advancedStats?: boolean;
  onlyMissing?: boolean;
  updatedBefore?: string;
  books?: string[];
};

export type ScrapeRunResponse = {
  id: number;
  leagueCode: string;
  status: string;
  scraperType: string;
  jobId: string | null;
  season: number | null;
  startDate: string | null;
  endDate: string | null;
  summary: string | null;
  errorDetails: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  requestedBy: string | null;
  config: ScrapeRunConfig | null;
};

export type GameSummary = {
  id: number;
  leagueCode: string;
  gameDate: string;
  homeTeam: string;
  awayTeam: string;
  score: ScoreObject | null;
  hasBoxscore: boolean;
  hasPlayerStats: boolean;
  hasOdds: boolean;
  hasSocial: boolean;
  hasPbp: boolean;
  hasFlow: boolean;
  hasAdvancedStats: boolean;
  playCount: number;
  socialPostCount: number;
  scrapeVersion: number | null;
  lastScrapedAt: string | null;
  lastIngestedAt: string | null;
  lastPbpAt: string | null;
  lastSocialAt: string | null;
  lastOddsAt: string | null;
  lastAdvancedStatsAt: string | null;
  derivedMetrics: Record<string, unknown> | null;
  isLive: boolean;
  isFinal: boolean;
  isPregame: boolean;
};

export type GameListResponse = {
  games: GameSummary[];
  total: number;
  nextOffset: number | null;
  withBoxscoreCount?: number;
  withPlayerStatsCount?: number;
  withOddsCount?: number;
  withSocialCount?: number;
  withPbpCount?: number;
  withFlowCount?: number;
  withAdvancedStatsCount?: number;
};
