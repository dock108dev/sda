import type { ScoreObject } from "./gameFlowTypes";

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

export type NBAAdvancedTeamStats = {
  team: string;
  isHome: boolean;
  offRating: number | null;
  defRating: number | null;
  netRating: number | null;
  pace: number | null;
  pie: number | null;
  efgPct: number | null;
  tsPct: number | null;
  fgPct: number | null;
  fg3Pct: number | null;
  ftPct: number | null;
  orbPct: number | null;
  drbPct: number | null;
  rebPct: number | null;
  astPct: number | null;
  astRatio: number | null;
  astTovRatio: number | null;
  tovPct: number | null;
  ftRate: number | null;
  contestedShots: number | null;
  deflections: number | null;
  chargesDrawn: number | null;
  looseBallsRecovered: number | null;
  paintPoints: number | null;
  fastbreakPoints: number | null;
  secondChancePoints: number | null;
  pointsOffTurnovers: number | null;
  benchPoints: number | null;
};

export type NBAAdvancedPlayerStats = {
  team: string;
  playerName: string;
  isHome: boolean;
  minutes: number | null;
  offRating: number | null;
  defRating: number | null;
  netRating: number | null;
  usgPct: number | null;
  pie: number | null;
  tsPct: number | null;
  efgPct: number | null;
  contested2ptFga: number | null;
  contested2ptFgm: number | null;
  uncontested2ptFga: number | null;
  uncontested2ptFgm: number | null;
  contested3ptFga: number | null;
  contested3ptFgm: number | null;
  uncontested3ptFga: number | null;
  uncontested3ptFgm: number | null;
  pullUpFga: number | null;
  pullUpFgm: number | null;
  catchShootFga: number | null;
  catchShootFgm: number | null;
  speed: number | null;
  distance: number | null;
  touches: number | null;
  timeOfPossession: number | null;
  contestedShots: number | null;
  deflections: number | null;
  chargesDrawn: number | null;
  looseBallsRecovered: number | null;
  screenAssists: number | null;
};

export type NHLAdvancedTeamStats = {
  team: string;
  isHome: boolean;
  xgoalsFor: number | null;
  xgoalsAgainst: number | null;
  xgoalsPct: number | null;
  corsiFor: number | null;
  corsiAgainst: number | null;
  corsiPct: number | null;
  fenwickFor: number | null;
  fenwickAgainst: number | null;
  fenwickPct: number | null;
  shotsFor: number | null;
  shotsAgainst: number | null;
  shootingPct: number | null;
  savePct: number | null;
  pdo: number | null;
  highDangerShotsFor: number | null;
  highDangerGoalsFor: number | null;
  highDangerShotsAgainst: number | null;
  highDangerGoalsAgainst: number | null;
};

export type NHLSkaterAdvancedStats = {
  team: string;
  playerName: string;
  isHome: boolean;
  xgoalsFor: number | null;
  xgoalsAgainst: number | null;
  onIceXgoalsPct: number | null;
  shots: number | null;
  goals: number | null;
  shootingPct: number | null;
  goalsPer60: number | null;
  assistsPer60: number | null;
  pointsPer60: number | null;
  shotsPer60: number | null;
  gameScore: number | null;
};

export type NHLGoalieAdvancedStats = {
  team: string;
  playerName: string;
  isHome: boolean;
  xgoalsAgainst: number | null;
  goalsAgainst: number | null;
  goalsSavedAboveExpected: number | null;
  savePct: number | null;
  highDangerSavePct: number | null;
  mediumDangerSavePct: number | null;
  lowDangerSavePct: number | null;
  shotsAgainst: number | null;
};

export type NFLAdvancedTeamStats = {
  team: string;
  isHome: boolean;
  totalEpa: number | null;
  passEpa: number | null;
  rushEpa: number | null;
  epaPerPlay: number | null;
  totalWpa: number | null;
  successRate: number | null;
  passSuccessRate: number | null;
  rushSuccessRate: number | null;
  explosivePlayRate: number | null;
  avgCpoe: number | null;
  avgAirYards: number | null;
  avgYac: number | null;
  totalPlays: number | null;
  passPlays: number | null;
  rushPlays: number | null;
};

export type NFLAdvancedPlayerStats = {
  team: string;
  playerName: string;
  isHome: boolean;
  playerRole: string | null;
  totalEpa: number | null;
  epaPerPlay: number | null;
  passEpa: number | null;
  rushEpa: number | null;
  receivingEpa: number | null;
  cpoe: number | null;
  airEpa: number | null;
  yacEpa: number | null;
  airYards: number | null;
  totalWpa: number | null;
  successRate: number | null;
  plays: number | null;
};

export type NCAABAdvancedTeamStats = {
  team: string;
  isHome: boolean;
  possessions: number | null;
  offRating: number | null;
  defRating: number | null;
  netRating: number | null;
  pace: number | null;
  offEfgPct: number | null;
  offTovPct: number | null;
  offOrbPct: number | null;
  offFtRate: number | null;
  defEfgPct: number | null;
  defTovPct: number | null;
  defOrbPct: number | null;
  defFtRate: number | null;
  fgPct: number | null;
  threePtPct: number | null;
  ftPct: number | null;
  threePtRate: number | null;
};

export type NCAABAdvancedPlayerStats = {
  team: string;
  playerName: string;
  isHome: boolean;
  minutes: number | null;
  offRating: number | null;
  usgPct: number | null;
  tsPct: number | null;
  efgPct: number | null;
  gameScore: number | null;
  points: number | null;
  rebounds: number | null;
  assists: number | null;
  steals: number | null;
  blocks: number | null;
  turnovers: number | null;
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
