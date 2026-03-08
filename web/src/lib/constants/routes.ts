/**
 * Canonical route paths for the admin UI.
 *
 * Import these instead of hardcoding path strings across components.
 */
export const ROUTES = {
  /** Admin dashboard / overview */
  OVERVIEW: "/admin",

  GAMES: "/admin/sports/browser",
  LOGS: "/admin/sports/logs",

  CONTROL_PANEL: "/admin/control-panel",
  FAIRBET_ODDS: "/admin/fairbet/odds",
  FAIRBET_LIVE: "/admin/fairbet/live",
  SPORTS_GAME: (id: number | string) => `/admin/sports/games/${id}`,

  /** Analytics */
  ANALYTICS: "/admin/analytics",
  ANALYTICS_WORKBENCH: "/admin/analytics/workbench",
  ANALYTICS_MODELS: "/admin/analytics/models",
  ANALYTICS_SIMULATOR: "/admin/analytics/simulator",
  ANALYTICS_MODEL_PERFORMANCE: "/admin/analytics/model-performance",
  ANALYTICS_EXPLORER: "/admin/analytics/explorer",
} as const;
