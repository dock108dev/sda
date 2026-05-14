/**
 * API module exports.
 */

export { APIClient, createClient, type ClientConfig } from "./client";
export { TheoryAPI } from "./theory";
export { HighlightsAPI } from "./highlights";
export { StrategyAPI } from "./strategy";
export {
  fetchGameSummary,
  type FlowStatusResponse,
  type GameSummaryResponse,
  type ScoreObject,
  type SummaryFinalScore,
} from "./games";
export type {
  ActivePool,
  BrandingResponse,
  CheckoutResponse,
  ClubBranding,
  ClubPublic,
  ClubSummary,
  MemberResponse,
  PortalResponse,
} from "./clubs";
export type {
  ScrollDownMlbBaseState,
  ScrollDownMlbDeckCard,
  ScrollDownMlbDeckCardType,
  ScrollDownMlbDeckResponse,
  ScrollDownMlbFinalScore,
  ScrollDownMlbInningHalf,
  ScrollDownMlbKeyStat,
  ScrollDownMlbPlannerNote,
  ScrollDownMlbPlannerReport,
  ScrollDownMlbPlayPayload,
  ScrollDownMlbRecentGame,
  ScrollDownMlbRecentResponse,
  ScrollDownMlbRevealResponse,
  ScrollDownMlbRunnerNames,
  ScrollDownMlbScoreState,
  ScrollDownMlbSpoilerPolicy,
  ScrollDownMlbTeamSummary,
  ScrollDownMlbValidationSeverity,
  ScrollDownMlbValidationWarning,
  ScrollDownMlbVisualIntensity,
  ScrollDownMlbVisualPayload,
} from "./scrollDownMlb";

