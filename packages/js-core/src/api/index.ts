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

