/**
 * Scroll Down MLB consumer API types — mirror of
 * api/app/scroll_down_mlb/schemas.py (camelCase wire format).
 *
 * Spoiler-safety contract (enforced backend-side by tests):
 *   * /recent — no scores, no winners.
 *   * /deck   — pre-reveal: scoreBefore + runsScoredOnPlay only.
 *   * /reveal — the only endpoint allowed to expose final score & winner.
 */

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

export type ScrollDownMlbTeamSummary = {
  id: string;
  abbreviation: string;
  displayName: string;
  colorLight?: string | null;
  colorDark?: string | null;
};

export type ScrollDownMlbBaseState = {
  first: boolean;
  second: boolean;
  third: boolean;
};

export type ScrollDownMlbScoreState = {
  home: number;
  away: number;
};

export type ScrollDownMlbFinalScore = {
  home: number;
  away: number;
};

export type ScrollDownMlbScoreChange = {
  home: number;
  away: number;
};

export type ScrollDownMlbRunnerSummary = {
  id?: string | null;
  name: string;
};

export type ScrollDownMlbPlayerSummary = {
  id?: string | null;
  name: string;
};

export type ScrollDownMlbBasesSituation = {
  first?: ScrollDownMlbRunnerSummary | null;
  second?: ScrollDownMlbRunnerSummary | null;
  third?: ScrollDownMlbRunnerSummary | null;
};

export type ScrollDownMlbCountSituation = {
  balls: number;
  strikes: number;
};

export type ScrollDownMlbGameSituation = {
  inning: number;
  half: "top" | "bottom";
  outs: number;
  score?: ScrollDownMlbScoreState | null;
  count?: ScrollDownMlbCountSituation | null;
  bases: ScrollDownMlbBasesSituation;
};

export type ScrollDownMlbGameSituationAfter = {
  inning: number;
  half: "top" | "bottom";
  outs: number;
  count?: ScrollDownMlbCountSituation | null;
  bases: ScrollDownMlbBasesSituation;
};

export type ScrollDownMlbBaseMovement = {
  runner: ScrollDownMlbRunnerSummary;
  fromBase: "home" | "first" | "second" | "third";
  toBase: "home" | "first" | "second" | "third" | "out";
  style: "advance" | "score" | "out";
  outAt?: "first" | "second" | "third" | "home" | null;
  reason?: string | null;
};

export type ScrollDownMlbKeyStat = {
  label: string;
  value: string;
  detail?: string | null;
};

// ---------------------------------------------------------------------------
// Validation + planner reporting
// ---------------------------------------------------------------------------

export type ScrollDownMlbValidationSeverity = "warning" | "error";

export type ScrollDownMlbValidationWarning = {
  code: string;
  severity: ScrollDownMlbValidationSeverity;
  message: string;
  playId?: string | null;
};

export type ScrollDownMlbPlannerNote = {
  cardId?: string | null;
  kind: string;
  reason: string;
  afterPlayIndex?: number | null;
  beforePlayIndex?: number | null;
};

export type ScrollDownMlbPlannerReport = {
  rhythm: ScrollDownMlbPlannerNote[];
};

// ---------------------------------------------------------------------------
// Visual payload
// ---------------------------------------------------------------------------

export type ScrollDownMlbVisualIntensity = "low" | "medium" | "high";

export type ScrollDownMlbDisplayHints = {
  showBattedBallOverlay: boolean;
  hitLocation?: string | null;
  suppressMovementLines: boolean;
};

export type ScrollDownMlbVisualPayload = {
  trajectory?: string | null;
  intensity?: ScrollDownMlbVisualIntensity | null;
  animationProfile?: string | null;
  displayHints?: ScrollDownMlbDisplayHints | null;
};

// ---------------------------------------------------------------------------
// Play payload — pre-reveal safe
// ---------------------------------------------------------------------------

export type ScrollDownMlbRunnerNames = Partial<
  Record<"first" | "second" | "third", string>
>;

export type ScrollDownMlbPlayPayload = {
  playId: string;
  eventType?: string | null;
  label?: string | null;
  subLabel?: string | null;
  description?: string | null;
  batterName?: string | null;
  pitcherName?: string | null;
  /** Pre-formatted running stat line for the pitcher at this play —
   *  e.g. "4.1 IP · 6 K · 1 BB · 2 R". Backend produces the string; the
   *  renderer just displays it. Null when the pitcher is unknown. */
  pitcherStatLine?: string | null;
  ballsBefore?: number | null;
  strikesBefore?: number | null;
  outsBefore?: number | null;
  outsAfter?: number | null;
  baseStateBefore?: ScrollDownMlbBaseState | null;
  baseStateAfter?: ScrollDownMlbBaseState | null;
  runnerNamesBefore: ScrollDownMlbRunnerNames;
  runnerNamesAfter: ScrollDownMlbRunnerNames;
  scoreBefore?: ScrollDownMlbScoreState | null;
  runsScoredOnPlay: number;
  scoreChange: ScrollDownMlbScoreChange;
};

export type ScrollDownMlbEventResult = {
  label: string;
  description: string;
  eventType?: string | null;
  isOut: boolean;
  isStrikeout: boolean;
  isWalk: boolean;
  isHit: boolean;
  isScoringPlay: boolean;
  isInningEnding: boolean;
};

export type ScrollDownMlbEventMatchup = {
  batter?: ScrollDownMlbPlayerSummary | null;
  pitcher?: ScrollDownMlbPlayerSummary | null;
};

// ---------------------------------------------------------------------------
// Deck cards
// ---------------------------------------------------------------------------

export type ScrollDownMlbDeckCardType =
  | "scene"
  | "play"
  | "rhythm"
  | "final_setup";

export type ScrollDownMlbInningHalf = "top" | "bottom";

export type ScrollDownMlbDeckCard = {
  id: string;
  type: ScrollDownMlbDeckCardType;
  sortOrder: number;
  inning?: number | null;
  half?: ScrollDownMlbInningHalf | null;
  title?: string | null;
  description: string;
  play?: ScrollDownMlbPlayPayload | null;
  visual?: ScrollDownMlbVisualPayload | null;
  leverageTier?: number | null;
};

// ---------------------------------------------------------------------------
// Half-inning containers — full-game event grouping
// ---------------------------------------------------------------------------

export type ScrollDownMlbRevealType =
  | "pitch"
  | "plate_appearance"
  | "play";

export type ScrollDownMlbHalfInningEvent = {
  sequence: number;
  playIndex: number;
  eventType?: string | null;
  outsBefore?: number | null;
  outsAfter?: number | null;
  baseStateBefore?: ScrollDownMlbBaseState | null;
  baseStateAfter?: ScrollDownMlbBaseState | null;
  scoreBefore?: ScrollDownMlbScoreState | null;
  runsScoredOnPlay: number;
  scoreChange: ScrollDownMlbScoreChange;
  movements: ScrollDownMlbBaseMovement[];
  revealType: ScrollDownMlbRevealType;
  result: ScrollDownMlbEventResult;
  matchup: ScrollDownMlbEventMatchup;
  isSelected: boolean;
};

export type ScrollDownMlbHalfInningMeta = {
  scoredRuns: number;
  hadActivity: boolean;
  hadLeadChange: boolean;
  hadTying: boolean;
};

export type ScrollDownMlbHalfInningContainer = {
  gameId: string;
  inning: number;
  half: ScrollDownMlbInningHalf;
  battingTeam: ScrollDownMlbTeamSummary;
  fieldingTeam: ScrollDownMlbTeamSummary;
  events: ScrollDownMlbHalfInningEvent[];
  meta: ScrollDownMlbHalfInningMeta;
  selectedPlayIndices: number[];
};

// ---------------------------------------------------------------------------
// Top-level responses
// ---------------------------------------------------------------------------

export type ScrollDownMlbSpoilerPolicy = "pre_reveal" | "post_reveal";

export type ScrollDownMlbDeckResponse = {
  gameId: string;
  deckVersion: string;
  generatedAt: string;
  isFinal: boolean;
  spoilerPolicy: "pre_reveal";
  homeTeam?: ScrollDownMlbTeamSummary | null;
  awayTeam?: ScrollDownMlbTeamSummary | null;
  lastPlayIndex?: number | null;
  firstPitch?: string | null;
  venue?: string | null;
  homeProbablePitcher?: string | null;
  awayProbablePitcher?: string | null;
  cards: ScrollDownMlbDeckCard[];
  halfInnings: ScrollDownMlbHalfInningContainer[];
  plannerReport?: ScrollDownMlbPlannerReport | null;
  validationWarnings: ScrollDownMlbValidationWarning[];
};

export type ScrollDownMlbRecentGame = {
  gameId: string;
  league: "MLB";
  gameDate?: string | null;
  status?: string | null;
  statusType?: string | null;
  awayTeam: ScrollDownMlbTeamSummary;
  homeTeam: ScrollDownMlbTeamSummary;
  venueName?: string | null;
  startTime?: string | null;
  hasDeck: boolean;
  deckVersion?: string | null;
  isFinal: boolean;
};

export type ScrollDownMlbRecentResponse = {
  games: ScrollDownMlbRecentGame[];
};

export type ScrollDownMlbRevealResponse = {
  gameId: string;
  finalScore: ScrollDownMlbFinalScore;
  winnerTeamId?: string | null;
  summary?: string | null;
  keyStats: ScrollDownMlbKeyStat[];
  gameFlow: unknown[];
  generatedAt?: string | null;
};
