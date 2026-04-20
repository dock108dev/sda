/**
 * TypeScript types matching py-core Pydantic schemas.
 * These should stay in sync with packages/py-core/py_core/schemas/theory.py
 */

// =============================================================================
// Sports shared primitives
// =============================================================================

/** Score as a structured {home, away} object. Replaces deprecated [int, int] tuple. */
export type ScoreObject = {
  home: number;
  away: number;
};

/** Canonical game status matching backend GameStatus enum (lowercase wire values). */
export type GameStatus =
  | "scheduled"
  | "pregame"
  | "live"
  | "final"
  | "archived"
  | "postponed"
  | "cancelled";

/** SSE event payload received from game:{gameId}:summary channel. */
export type LiveGameEvent = {
  type: "patch" | "phase_change" | "game_patch" | "epoch_changed" | "subscribed" | "error";
  channel?: string;
  seq?: number;
  boot_epoch?: string;
  ts?: number;
  /** patch / game_patch fields — score/clock differential update */
  gameId?: number;
  score?: ScoreObject;
  clock?: string;
  status?: GameStatus;
  /** phase_change fields — game period/status transition */
  game_phase?: string;
  /** epoch_changed field — new server boot epoch */
  epoch?: string;
};

// =============================================================================
// FairBet / live odds types (SSE + hook)
// =============================================================================

export interface LiveBookOdds {
  book: string;
  price: number;
  evPercent: number | null;
  displayEv: number | null;
  impliedProb: number | null;
  isSharp: boolean;
  evMethod: string | null;
  evConfidenceTier: string | null;
}

/** Per-bet live odds snapshot returned by useLiveOdds. */
export interface OddsSnapshot {
  gameId: number;
  leagueCode: string;
  homeTeam: string;
  awayTeam: string;
  gameDate: string;
  marketKey: string;
  selectionKey: string;
  lineValue: number;
  marketCategory: string | null;
  playerName: string | null;
  description: string | null;
  trueProb: number | null;
  referencePrice: number | null;
  oppositeReferencePrice: number | null;
  estimatedSharpPrice: number | null;
  extrapolationRefLine: number | null;
  extrapolationDistance: number | null;
  consensusBookCount: number | null;
  consensusIqr: number | null;
  perBookFairProbs: Record<string, number> | null;
  books: LiveBookOdds[];
  evMethod: string | null;
  evConfidenceTier: string | null;
  evDisabledReason: string | null;
  hasFair: boolean;
  confidence: number | null;
  confidenceFlags: string[];
}

/** Aggregated EV summary for one game's live odds. */
export interface EVAnalysis {
  gameId: number;
  totalBets: number;
  positiveEvCount: number;
  maxEv: number | null;
  lastUpdatedAt: string | null;
  diagnostics: Record<string, number>;
}

/** SSE event payload received from the fairbet:odds channel. */
export type FairbetOddsEvent = {
  type: "fairbet_patch" | "epoch_changed" | "subscribed" | "error";
  channel?: string;
  seq?: number;
  boot_epoch?: string;
  ts?: number;
  /** Present on fairbet_patch events */
  gameId?: number;
  bets?: OddsSnapshot[];
  total?: number;
  lastUpdatedAt?: string | null;
  evDiagnostics?: Record<string, number>;
  /** Present on epoch_changed events */
  epoch?: string;
};

// =============================================================================
// Theory / strategy types
// =============================================================================

export type Domain = "bets" | "crypto" | "stocks" | "conspiracies" | "playlist";

export interface TheoryRequest {
  text: string;
  domain?: Domain | null;
  user_tier?: string | null;
}

export interface DataSource {
  name: string;
  cache_status: "cached" | "fresh";
  details?: string | null;
}

export interface TheoryResponse {
  summary: string;
  verdict: string;
  confidence: number; // 0-1
  data_used: DataSource[];
  how_we_got_conclusion: string[];
  long_term_outcome_example: string;
  limitations: string[];
  guardrail_flags: string[];
  model_version?: string | null;
  evaluation_date?: string | null;
}

// Domain-specific request types
export interface BetsRequest extends TheoryRequest {
  sport?: string | null;
  league?: string | null;
  horizon?: string | null; // "single_game" | "full_season"
}

// Domain-specific response types
export interface BetsResponse extends TheoryResponse {
  likelihood_grade: string; // A-F
  edge_estimate?: number | null;
  kelly_sizing_example: string;
}

export interface CryptoResponse extends TheoryResponse {
  pattern_frequency: number; // 0-1
  failure_periods: string[];
  remaining_edge?: number | null;
}

export interface StocksResponse extends TheoryResponse {
  correlation_grade: string;
  fundamentals_match: boolean;
  volume_analysis: string;
}

export interface ClaimEvidence {
  claim: string;
  evidence: string;
  verdict: string;
}

export interface ConspiraciesResponse extends TheoryResponse {
  claim_text: string;
  story_sections: string[];
  claims_vs_evidence: ClaimEvidence[];
  verdict_text: string;
  confidence_score: number;
  sources_used: string[];
  fuels_today: string[];
}

// FastAPI/Pydantic validation error shapes (shared across API endpoints).
export interface ApiValidationErrorItem {
  loc: Array<string | number>;
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface ApiErrorResponse {
  detail: string | ApiValidationErrorItem[];
}

// API Error types
export class APIError extends Error {
  constructor(
    message: string,
    public statusCode: number,
    public detail?: string
  ) {
    super(message);
    this.name = "APIError";
  }
}

export class NetworkError extends Error {
  constructor(message: string, public originalError?: unknown) {
    super(message);
    this.name = "NetworkError";
  }
}

// Strategy types
export interface StrategyIndicator {
  name: string;
  source: string;
  params: Record<string, unknown>;
}

export interface StrategyEntry {
  side: "long" | "short";
  condition?: string; // Entry condition (e.g., "If ruling is positive AND BTC breaks above 94,500")
  method?: string; // "breakout" | "mean-reversion" | "catalyst" | "trend" | "sentiment"
  tranchePercent?: number; // Percentage of allocation (if capital provided)
  allocateUsd?: number; // USD amount to allocate (only if capital provided)
  logic: string;
  confidence: number; // 1-5
  tags: string[];
  notes?: string;
}

export interface StrategyExit {
  logic: string;
  type: "stop" | "target" | "timed" | "conditional";
  notes?: string;
}

export interface StrategyRisk {
  maxCapitalAtRiskPct: number;
  maxOpenPositions: number;
  positionSizing: string;
}

export interface EntryTranche {
  trigger: string;
  capitalPct: number;
  allocateUsd?: number; // Only present if capital provided
  comments?: string;
}

export interface EntryPlan {
  tranches: EntryTranche[];
  maxDeploymentPct: number;
}

export interface StrategySpec {
  name: string;
  market: string;
  timeframe: string;
  thesis: string;
  ticker?: string;
  sector?: string;
  units?: string; // "USD" | "thousands" | "percentage"
  entryPlan?: EntryPlan;
  indicators: StrategyIndicator[];
  entries: StrategyEntry[];
  exits: StrategyExit[];
  risk: StrategyRisk;
}

export interface DatasetSpec {
  name: string;
  source: string;
  resolution: string;
  fields: string[];
}

export interface BacktestBlueprint {
  datasets: DatasetSpec[];
  metrics: string[];
  assumptions: string[];
  scenarios?: string[]; // ["lump sum", "3-tranche DCA", etc.]
  period?: string; // "2017-01-01 to today"
}

export interface EdgeDiagnostics {
  strengths: string[];
  risks: string[];
  monitoring: string[];
}

export interface AlertTrigger {
  name: string;
  condition: string;
  channel: string;
  cooldownMinutes: number;
}

export interface AlertSpec {
  triggers: AlertTrigger[];
}

export interface CurrentMarketContext {
  price?: string;
  drawdownFromATH?: string;
  volatility30d?: string;
  funding?: string;
  oiTrend?: string;
  etfFlows?: string;
}

export interface PlaybookText {
  title: string;
  summary: string;
  currentMarketContext?: CurrentMarketContext;
  narrativeSummary?: string;
  deepDive?: string[];
  gamePlan: string[];
  guardrails: string[];
  dataSources: string[];
}

export interface Assumptions {
  normalizations: string[];
  uncertainties: string[];
  userSaid90Means?: string;
}

export interface HistoricalAnalog {
  event: string;
  cryptoReaction: string;
  coinsReactedMost: string[];
  coinsReactedLeast: string[];
  liquiditySimilar?: string;
  confidence: "High" | "Medium" | "Low";
}

export interface ProbableMarketReactions {
  ifCatalystPositive: string;
  ifCatalystNegative: string;
  ifCatalystNeutral: string;
}

export interface ConfidenceScores {
  overall: "High" | "Medium" | "Low";
  assetMapping: "High" | "Medium" | "Low";
  timing: "High" | "Medium" | "Low";
  magnitude: "High" | "Medium" | "Low";
}

export interface CatalystAnalysis {
  type: string; // "macro_legal" | "macro_regulatory" | "trade_policy" | etc.
  description: string;
  affectedCategories: string[];
  historicalAnalogs: HistoricalAnalog[];
  probableMarketReactions?: ProbableMarketReactions;
  confidenceScores?: ConfidenceScores;
}

export interface AssetBreakdownItem {
  asset: string;
  reasoning: string;
  reaction: string;
  entryPlan: string[];
  risks: string[];
  confidence: "High" | "Medium" | "Low";
}

export interface PatternAnalysis {
  trend?: string;
  valuation?: string;
  volume?: string;
  historicalSetups?: string[];
  confidence?: string;
}

export interface StrategyInterpretation {
  interpretation?: string;
  playbookText?: PlaybookText;
  catalystAnalysis?: CatalystAnalysis;
  assetBreakdown?: AssetBreakdownItem[];
  patternAnalysis?: PatternAnalysis;
  strategySpec: StrategySpec;
  backtestBlueprint: BacktestBlueprint;
  edgeDiagnostics: EdgeDiagnostics;
  alertSpec: AlertSpec;
  assumptions?: Assumptions;
}

export interface StrategyResponse extends StrategyInterpretation {
  id: string;
  ideaText: string;
  createdAt?: string;
}

export interface StrategySaveRequest extends StrategyInterpretation {
  strategyId?: string;
  ideaText: string;
  userId?: number;
}

export interface BacktestRequest {
  strategyId: string;
  strategySpec: StrategySpec;
}

export interface BacktestMetrics {
  winRate: number;
  expectancy: number;
  maxDrawdown: number;
  sharpe: number;
  bestTrade: number;
  worstTrade: number;
  numberOfTrades: number;
}

export interface BacktestResult {
  id: string;
  strategyId: string;
  equityCurve: Array<{ timestamp: string; equity: number }>;
  metrics: BacktestMetrics;
  trades: Array<{
    id: string;
    timestamp: string;
    side: "long" | "short";
    pnl: number;
    notes?: string;
  }>;
  regimeNotes: string[];
  generatedAt: string;
}

export interface AlertEvent {
  id: string;
  strategyId: string;
  triggeredAt: string;
  reason: string;
}

export interface ToggleAlertsRequest {
  strategyId: string;
  enabled: boolean;
}

