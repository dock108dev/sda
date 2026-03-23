// ── Task registry (mirrors API whitelist) ──

export type ParamType = "select" | "number" | "text";

export interface TaskParam {
  name: string;
  type: ParamType;
  required: boolean;
  options?: string[];
  default?: string | number;
}

export interface TaskDef {
  name: string;
  label: string;
  description: string;
  category: string;
  queue: "sports-scraper" | "social-scraper";
  params: TaskParam[];
}

export const LEAGUE_OPTIONS = ["NBA", "NHL", "NCAAB", "MLB", "NFL"];

export const TASK_REGISTRY: TaskDef[] = [
  // Ingestion
  {
    name: "run_scheduled_ingestion",
    label: "Scheduled Ingestion",
    description: "Full scheduled ingestion (NBA, NHL, NCAAB, MLB sequentially)",
    category: "Ingestion",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "run_daily_sweep",
    label: "Daily Sweep",
    description: "Daily truth repair and backfill sweep",
    category: "Ingestion",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "ingest_nba_historical",
    label: "NBA Historical Backfill",
    description: "Backfill NBA boxscores and PBP from Basketball Reference (polite scraping, ~14h for 3 seasons)",
    category: "Ingestion",
    queue: "sports-scraper",
    params: [
      { name: "start_date", type: "text", required: true, default: "2024-10-22" },
      { name: "end_date", type: "text", required: true, default: "2025-04-13" },
    ],
  },
  // Polling
  {
    name: "update_game_states",
    label: "Update Game States",
    description: "Update game state machine for all tracked games",
    category: "Polling",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "poll_live_pbp",
    label: "Poll Live PBP",
    description: "Poll live play-by-play and boxscores",
    category: "Polling",
    queue: "sports-scraper",
    params: [],
  },
  // Odds
  {
    name: "sync_mainline_odds",
    label: "Mainline Odds",
    description: "Sync mainline odds (spreads, totals, moneyline)",
    category: "Odds",
    queue: "sports-scraper",
    params: [
      {
        name: "league",
        type: "select",
        required: false,
        options: LEAGUE_OPTIONS,
      },
    ],
  },
  {
    name: "sync_prop_odds",
    label: "Prop Odds",
    description: "Sync player/team prop odds for pregame events",
    category: "Odds",
    queue: "sports-scraper",
    params: [
      {
        name: "league",
        type: "select",
        required: false,
        options: LEAGUE_OPTIONS,
      },
    ],
  },
  // Social
  {
    name: "collect_game_social",
    label: "Game Social",
    description: "Collect social media content for upcoming games",
    category: "Social",
    queue: "social-scraper",
    params: [],
  },
  {
    name: "collect_social_for_league",
    label: "League Social",
    description: "Collect social content for a specific league",
    category: "Social",
    queue: "social-scraper",
    params: [
      {
        name: "league",
        type: "select",
        required: true,
        options: LEAGUE_OPTIONS,
      },
    ],
  },
  {
    name: "map_social_to_games",
    label: "Map Social to Games",
    description: "Map collected social posts to games",
    category: "Social",
    queue: "social-scraper",
    params: [
      {
        name: "batch_size",
        type: "number",
        required: false,
        default: 100,
      },
    ],
  },
  {
    name: "run_final_whistle_social",
    label: "Final Whistle Social",
    description: "Collect post-game social content for a specific game",
    category: "Social",
    queue: "social-scraper",
    params: [
      { name: "game_id", type: "number", required: true },
    ],
  },
  // Flows
  {
    name: "run_scheduled_flow_generation",
    label: "All Flows",
    description: "Run flow generation for all leagues",
    category: "Flows",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "run_scheduled_nba_flow_generation",
    label: "NBA Flows",
    description: "Run flow generation for NBA games",
    category: "Flows",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "run_scheduled_nhl_flow_generation",
    label: "NHL Flows",
    description: "Run flow generation for NHL games",
    category: "Flows",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "run_scheduled_ncaab_flow_generation",
    label: "NCAAB Flows",
    description: "Run flow generation for NCAAB games (max 10)",
    category: "Flows",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "trigger_flow_for_game",
    label: "Flow for Game",
    description: "Trigger flow generation for a specific game",
    category: "Flows",
    queue: "sports-scraper",
    params: [
      { name: "game_id", type: "number", required: true },
    ],
  },
  // Timelines
  {
    name: "run_scheduled_timeline_generation",
    label: "Timeline Generation",
    description: "Run scheduled timeline generation for all leagues",
    category: "Timelines",
    queue: "sports-scraper",
    params: [],
  },
  // Golf (DataGolf API)
  {
    name: "golf_sync_schedule",
    label: "Golf: Sync Schedule",
    description: "Sync PGA Tour tournament schedule from DataGolf",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "golf_sync_players",
    label: "Golf: Sync Players",
    description: "Sync full player catalog from DataGolf",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "golf_sync_field",
    label: "Golf: Sync Field",
    description: "Sync current tournament field and tee times",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "golf_sync_leaderboard",
    label: "Golf: Sync Leaderboard",
    description: "Sync live leaderboard and tournament stats",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "golf_sync_odds",
    label: "Golf: Sync Odds",
    description: "Sync outright odds for all markets (win, top 5, top 10, make cut)",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "golf_sync_dfs",
    label: "Golf: Sync DFS",
    description: "Sync DFS projections for DraftKings, FanDuel, Yahoo",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "golf_sync_stats",
    label: "Golf: Sync Stats",
    description: "Sync player skill ratings and rankings",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  {
    name: "golf_score_pools",
    label: "Golf: Score Pools",
    description: "Score all live golf pools and write materialized results",
    category: "Golf",
    queue: "sports-scraper",
    params: [],
  },
  // Utility
  {
    name: "clear_scraper_cache",
    label: "Clear Cache",
    description: "Clear scraper cache for a league (optionally limit by days)",
    category: "Utility",
    queue: "sports-scraper",
    params: [
      {
        name: "league",
        type: "select",
        required: true,
        options: LEAGUE_OPTIONS,
      },
      { name: "days", type: "number", required: false },
    ],
  },
];

// Group tasks by category preserving insertion order
export const CATEGORIES = Array.from(
  new Set(TASK_REGISTRY.map((t) => t.category))
);
