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
  league_code: string;
  status: string;
  scraper_type: string;
  job_id: string | null;
  season: number | null;
  start_date: string | null;
  end_date: string | null;
  summary: string | null;
  error_details: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  requested_by: string | null;
  config: ScrapeRunConfig | null;
};

export type GameSummary = {
  id: number;
  leagueCode: string;
  gameDate: string;
  homeTeam: string;
  awayTeam: string;
  homeScore: number | null;
  awayScore: number | null;
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

export type NormalizedStat = {
  key: string;
  displayLabel: string;
  group: string;
  value: number | string | null;
  formatType: string;
};

export type TeamStat = {
  team: string;
  isHome: boolean;
  stats: Record<string, unknown>;
  normalizedStats?: NormalizedStat[] | null;
  source?: string | null;
  updatedAt?: string | null;
};

export type PlayerStat = {
  team: string;
  playerName: string;
  minutes: number | null;
  points: number | null;
  rebounds: number | null;
  assists: number | null;
  rawStats: Record<string, unknown>;
};

export type NHLSkaterStat = {
  team: string;
  playerName: string;
  toi: string | null;
  goals: number | null;
  assists: number | null;
  points: number | null;
  shotsOnGoal: number | null;
  plusMinus: number | null;
  penaltyMinutes: number | null;
  hits: number | null;
  blockedShots: number | null;
  rawStats: Record<string, unknown>;
};

export type NHLGoalieStat = {
  team: string;
  playerName: string;
  toi: string | null;
  shotsAgainst: number | null;
  saves: number | null;
  goalsAgainst: number | null;
  savePercentage: number | null;
  rawStats: Record<string, unknown>;
};

export type MLBBatterStat = {
  team: string;
  playerName: string;
  position: string | null;
  atBats: number | null;
  hits: number | null;
  runs: number | null;
  rbi: number | null;
  homeRuns: number | null;
  baseOnBalls: number | null;
  strikeOuts: number | null;
  stolenBases: number | null;
  avg: string | null;
  obp: string | null;
  slg: string | null;
  ops: string | null;
  rawStats: Record<string, unknown>;
};

export type MLBPitcherStat = {
  team: string;
  playerName: string;
  inningsPitched: string | null;
  hits: number | null;
  runs: number | null;
  earnedRuns: number | null;
  baseOnBalls: number | null;
  strikeOuts: number | null;
  homeRuns: number | null;
  era: string | null;
  pitchCount: number | null;
  strikes: number | null;
  rawStats: Record<string, unknown>;
};

export type MLBPitcherGameStat = {
  team: string;
  playerName: string;
  isStarter: boolean;
  inningsPitched: number | null;
  battersFaced: number | null;
  pitchesThrown: number | null;
  strikeouts: number | null;
  walks: number | null;
  zonePitches: number | null;
  zoneSwings: number | null;
  zoneContact: number | null;
  outsidePitches: number | null;
  outsideSwings: number | null;
  outsideContact: number | null;
  ballsInPlay: number | null;
  avgExitVeloAgainst: number | null;
  hardHitAgainst: number | null;
  barrelAgainst: number | null;
};

export type MLBFieldingStat = {
  team: string;
  playerName: string;
  position: string | null;
  outsAboveAverage: number | null;
  defensiveRunsSaved: number | null;
  uzr: number | null;
  errors: number | null;
  assists: number | null;
  putouts: number | null;
};

export type MLBAdvancedTeamStats = {
  team: string;
  isHome: boolean;
  totalPitches: number;
  zSwingPct: number | null;
  oSwingPct: number | null;
  zContactPct: number | null;
  oContactPct: number | null;
  ballsInPlay: number;
  avgExitVelo: number | null;
  hardHitPct: number | null;
  barrelPct: number | null;
};

export type MLBAdvancedPlayerStats = {
  team: string;
  playerName: string;
  isHome: boolean;
  totalPitches: number;
  zonePitches: number;
  zoneSwings: number;
  zoneContact: number;
  outsidePitches: number;
  outsideSwings: number;
  outsideContact: number;
  ballsInPlay: number;
  avgExitVelo: number | null;
  hardHitCount: number;
  barrelCount: number;
};

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
  playType: string | null;
  teamAbbreviation: string | null;
  playerName: string | null;
  description: string | null;
  homeScore: number | null;
  awayScore: number | null;
  tier: number | null;
};

export type TieredPlayGroup = {
  startIndex: number;
  endIndex: number;
  playIndices: number[];
  summaryLabel: string;
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
    homeScore: number | null;
    awayScore: number | null;
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
  odds: OddsEntry[];
  socialPosts: SocialPost[];
  plays: PlayEntry[];
  groupedPlays: TieredPlayGroup[] | null;
  derivedMetrics: Record<string, unknown>;
  rawPayloads: Record<string, unknown>;
};

export type GameFilters = {
  leagues: string[];
  season?: number;
  team?: string;
  startDate?: string;
  endDate?: string;
  missingBoxscore?: boolean;
  missingPlayerStats?: boolean;
  missingOdds?: boolean;
  missingSocial?: boolean;
  missingAny?: boolean;
  hasPbp?: boolean;
  finalOnly?: boolean;
  limit?: number;
  offset?: number;
};

export type TeamSummary = {
  id: number;
  name: string;
  shortName: string;
  abbreviation: string;
  leagueCode: string;
  gamesCount: number;
  colorLightHex: string | null;
  colorDarkHex: string | null;
};

export type TeamListResponse = {
  teams: TeamSummary[];
  total: number;
};

export type TeamGameSummary = {
  id: number;
  gameDate: string;
  opponent: string;
  isHome: boolean;
  score: string;
  result: string;
};

export type TeamDetail = {
  id: number;
  name: string;
  shortName: string;
  abbreviation: string;
  leagueCode: string;
  location: string | null;
  externalRef: string | null;
  colorLightHex: string | null;
  colorDarkHex: string | null;
  recentGames: TeamGameSummary[];
};


export type JobResponse = {
  runId: number;
  jobId: string | null;
  message: string;
};
