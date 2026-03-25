/**
 * Analytics-specific constants for multi-sport support.
 */

/** Sports that have simulator support. */
export const ANALYTICS_SPORTS = ["MLB", "NBA", "NHL", "NCAAB"] as const;
export type AnalyticsSport = (typeof ANALYTICS_SPORTS)[number];

/** Sport-specific configuration for UI rendering. */
export interface SportConfig {
  code: string;
  label: string;
  hasLineupMode: boolean;
  hasPitcher: boolean;
  hasGoalie: boolean;
  scoringUnit: string;
  periodLabel: string;
  defaultProbMode: string;
}

export const SPORT_CONFIGS: Record<string, SportConfig> = {
  MLB: {
    code: "mlb",
    label: "MLB",
    hasLineupMode: true,
    hasPitcher: true,
    hasGoalie: false,
    scoringUnit: "runs",
    periodLabel: "innings",
    defaultProbMode: "ml",
  },
  NBA: {
    code: "nba",
    label: "NBA",
    hasLineupMode: false,
    hasPitcher: false,
    hasGoalie: false,
    scoringUnit: "points",
    periodLabel: "quarters",
    defaultProbMode: "rule_based",
  },
  NHL: {
    code: "nhl",
    label: "NHL",
    hasLineupMode: false,
    hasPitcher: false,
    hasGoalie: true,
    scoringUnit: "goals",
    periodLabel: "periods",
    defaultProbMode: "rule_based",
  },
  NCAAB: {
    code: "ncaab",
    label: "NCAAB",
    hasLineupMode: false,
    hasPitcher: false,
    hasGoalie: false,
    scoringUnit: "points",
    periodLabel: "halves",
    defaultProbMode: "rule_based",
  },
};
