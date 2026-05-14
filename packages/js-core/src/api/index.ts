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
  ArcadeDailyPressurePackResponse,
  ArcadePressureMomentResponse,
  ArcadePressureTier,
  ScrollDownMlbBaseMovement,
  ScrollDownMlbBaseState,
  ScrollDownMlbBasesSituation,
  ScrollDownMlbCountSituation,
  ScrollDownMlbDeckCard,
  ScrollDownMlbDeckCardType,
  ScrollDownMlbDeckResponse,
  ScrollDownMlbDisplayHints,
  ScrollDownMlbEventMatchup,
  ScrollDownMlbEventResult,
  ScrollDownMlbFinalScore,
  ScrollDownMlbGameSituation,
  ScrollDownMlbGameSituationAfter,
  ScrollDownMlbHalfInningContainer,
  ScrollDownMlbHalfInningEvent,
  ScrollDownMlbHalfInningMeta,
  ScrollDownMlbInningHalf,
  ScrollDownMlbKeyStat,
  ScrollDownMlbPlannerNote,
  ScrollDownMlbPlannerReport,
  ScrollDownMlbPlayerSummary,
  ScrollDownMlbPlayPayload,
  ScrollDownMlbRecentGame,
  ScrollDownMlbRecentResponse,
  ScrollDownMlbRevealType,
  ScrollDownMlbRevealResponse,
  ScrollDownMlbRunnerSummary,
  ScrollDownMlbRunnerNames,
  ScrollDownMlbScoreChange,
  ScrollDownMlbScoreState,
  ScrollDownMlbSpoilerPolicy,
  ScrollDownMlbTeamSummary,
  ScrollDownMlbValidationSeverity,
  ScrollDownMlbValidationWarning,
  ScrollDownMlbVisualIntensity,
  ScrollDownMlbVisualPayload,
} from "./scrollDownMlb";
