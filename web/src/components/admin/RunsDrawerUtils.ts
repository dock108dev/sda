import type { JobRunResponse } from "@/lib/api/sportsAdmin";

/** Maps every phase value written to the DB → human-readable label.
 *  Used for both the filter dropdown and the table cells. */
const PHASE_LABELS: Record<string, string> = {
  // Polling / live
  update_game_states: "Update Game States",
  poll_live_pbp: "Poll Live PBP",
  // Odds
  odds: "Odds Sync",
  sync_mainline_odds: "Mainline Odds",
  sync_prop_odds: "Prop Odds",
  // Ingestion
  ingest: "Boxscore Ingest",
  scheduled_ingestion: "Scheduled Ingestion",
  data_backfill: "Data Backfill",
  nba_historical: "NBA Historical",
  pbp: "Play-by-Play",
  // Advanced stats
  advanced_stats: "Advanced Stats",
  ingest_nba_advanced_stats: "NBA Advanced Stats",
  ingest_nhl_advanced_stats: "NHL Advanced Stats",
  ingest_mlb_advanced_stats: "MLB Advanced Stats",
  ingest_nfl_advanced_stats: "NFL Advanced Stats",
  ingest_ncaab_advanced_stats: "NCAAB Advanced Stats",
  // Social
  social: "Social",
  collect_game_social: "Game Social",
  collect_social_for_league: "League Social",
  map_social_to_games: "Map Social",
  // Flows & timelines
  trigger_flow: "Trigger Flow",
  flow_generation: "Flow Generation",
  timeline_generation: "Timeline Generation",
  // Sweep
  daily_sweep: "Daily Sweep",
  // Golf
  golf_sync_schedule: "Golf: Schedule",
  golf_sync_players: "Golf: Players",
  golf_sync_field: "Golf: Field",
  golf_sync_leaderboard: "Golf: Leaderboard",
  golf_sync_odds: "Golf: Odds",
  golf_sync_dfs: "Golf: DFS",
  golf_sync_stats: "Golf: Stats",
  golf_score_pools: "Golf: Score Pools",
  // Analytics
  analytics_train: "Analytics: Train",
  analytics_experiment: "Analytics: Experiment",
  analytics_replay: "Analytics: Replay",
  analytics_backtest: "Analytics: Backtest",
  analytics_batch_sim: "Analytics: Batch Sim",
  analytics_record_outcomes: "Analytics: Record Outcomes",
  analytics_degradation_check: "Analytics: Degradation Check",
};

export function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? phase;
}

export const PHASE_OPTIONS = [
  { value: "", label: "All phases" },
  ...Object.entries(PHASE_LABELS).map(([value, label]) => ({ value, label })),
];

export const ALL_STATUSES = ["success", "running", "queued", "error", "skipped", "canceled", "interrupted"] as const;
export const STATUS_LABELS: Record<string, string> = {
  success: "Success",
  running: "Running",
  queued: "Queued",
  error: "Error",
  skipped: "Skipped",
  canceled: "Canceled",
  interrupted: "Interrupted",
};

export const AUTO_REFRESH_MS = 30_000;

/** A single run or a group of consecutive runs with the same phase+status. */
export type RunOrGroup =
  | { kind: "single"; run: JobRunResponse }
  | { kind: "group"; phase: string; status: string; count: number; runs: JobRunResponse[] };

/** Collapse consecutive runs with the same phase+status into groups. */
export function groupConsecutiveRuns(runs: JobRunResponse[]): RunOrGroup[] {
  const result: RunOrGroup[] = [];
  let i = 0;
  while (i < runs.length) {
    const run = runs[i];
    let j = i + 1;
    while (
      j < runs.length &&
      runs[j].phase === run.phase &&
      runs[j].status === run.status
    ) {
      j++;
    }
    const count = j - i;
    if (count >= 3) {
      result.push({
        kind: "group",
        phase: run.phase,
        status: run.status,
        count,
        runs: runs.slice(i, j),
      });
    } else {
      for (let k = i; k < j; k++) {
        result.push({ kind: "single", run: runs[k] });
      }
    }
    i = j;
  }
  return result;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
