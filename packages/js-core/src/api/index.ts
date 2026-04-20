/**
 * API module exports.
 */

export { APIClient, createClient, type ClientConfig } from "./client";
export { TheoryAPI } from "./theory";
export { HighlightsAPI } from "./highlights";
export { StrategyAPI } from "./strategy";
export {
  fetchGameFlow,
  type BlockMiniBox,
  type ConsumerGameFlowResponse,
  type FlowStatusResponse,
  type GameFlowPlay,
  type NarrativeBlock,
  type ScoreObject,
} from "./games";

