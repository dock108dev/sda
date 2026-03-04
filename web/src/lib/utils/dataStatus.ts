/**
 * Derives a structured data status from a boolean flag, game date, and optional timestamp.
 *
 * Rules:
 * - Future game + non-odds data → not_applicable
 * - hasX === false → missing (with reason)
 * - hasX === true + timestamp stale → stale
 * - Otherwise → present
 */

export type DataStatus = "present" | "missing" | "stale" | "not_applicable";

export interface DataStatusResult {
  status: DataStatus;
  reason: string;
}

/** Staleness thresholds in milliseconds */
const STALE_THRESHOLD_MS: Record<string, number> = {
  boxscore: 7 * 24 * 60 * 60 * 1000,
  playerStats: 7 * 24 * 60 * 60 * 1000,
  odds: 1 * 24 * 60 * 60 * 1000,
  social: 7 * 24 * 60 * 60 * 1000,
  pbp: 7 * 24 * 60 * 60 * 1000,
  flow: 7 * 24 * 60 * 60 * 1000,
  advancedStats: 7 * 24 * 60 * 60 * 1000,
};

/** Data types that don't apply to future games (everything except odds). */
const FUTURE_NOT_APPLICABLE = new Set([
  "boxscore",
  "playerStats",
  "social",
  "pbp",
  "flow",
  "advancedStats",
]);

export type DataField =
  | "boxscore"
  | "playerStats"
  | "odds"
  | "social"
  | "pbp"
  | "flow"
  | "advancedStats";

const MISSING_REASONS: Record<DataField, string> = {
  boxscore: "No boxscore scraped",
  playerStats: "No player stats scraped",
  odds: "No odds scraped",
  social: "No social posts scraped",
  pbp: "No play-by-play scraped",
  flow: "No flow generated",
  advancedStats: "No advanced stats ingested",
};

function isFutureGame(gameDate: string): boolean {
  const d = new Date(gameDate);
  return d.getTime() > Date.now();
}

function isStale(timestamp: string | null | undefined, field: DataField): boolean {
  if (!timestamp) return false;
  const threshold = STALE_THRESHOLD_MS[field] ?? 7 * 24 * 60 * 60 * 1000;
  const age = Date.now() - new Date(timestamp).getTime();
  return age > threshold;
}

function formatAgo(timestamp: string): string {
  const ms = Date.now() - new Date(timestamp).getTime();
  const hours = Math.floor(ms / (1000 * 60 * 60));
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function deriveDataStatus(
  field: DataField,
  hasData: boolean,
  gameDate: string,
  lastUpdated?: string | null,
): DataStatusResult {
  // Future game — most data types are not applicable
  if (isFutureGame(gameDate) && FUTURE_NOT_APPLICABLE.has(field)) {
    return { status: "not_applicable", reason: "Game hasn't been played yet" };
  }

  if (!hasData) {
    // Special case: flow requires PBP, but we can't check that here.
    // The caller can provide a custom reason if needed.
    return { status: "missing", reason: MISSING_REASONS[field] };
  }

  // Has data — check staleness
  if (lastUpdated && isStale(lastUpdated, field)) {
    return {
      status: "stale",
      reason: `Last updated ${formatAgo(lastUpdated)}`,
    };
  }

  return { status: "present", reason: "Up to date" };
}
