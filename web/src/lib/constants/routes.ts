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
  ANALYTICS_SIMULATOR: "/admin/analytics/simulator",
  ANALYTICS_MODELS: "/admin/analytics/models",
  ANALYTICS_BATCH: "/admin/analytics/batch",
  ANALYTICS_EXPLORER: "/admin/analytics/explorer",
  /** System */
  USERS: "/admin/users",
} as const;
