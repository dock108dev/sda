/**
 * Sports-related constants shared across admin pages.
 * 
 * Centralized configuration to avoid duplication and ensure consistency.
 */

export const SUPPORTED_LEAGUES = ["NBA", "NCAAB", "NFL", "NCAAF", "MLB", "NHL"] as const;

/** Leagues with FairBet odds support — subset of SUPPORTED_LEAGUES */
export const FAIRBET_LEAGUES = ["NBA", "NHL", "NCAAB", "MLB"] as const;

export type LeagueCode = typeof SUPPORTED_LEAGUES[number];

/**
 * Status color mapping for scrape run status indicators.
 */
export const SCRAPE_RUN_STATUS_COLORS: Record<string, string> = {
  success: "#0f9d58",
  running: "#fbbc04",
  pending: "#5f6368",
  error: "#ea4335",
  interrupted: "#f97316", // Orange color for interrupted runs
  canceled: "#94a3b8",
} as const;


