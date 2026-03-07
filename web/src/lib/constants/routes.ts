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
  SPORTS_GAME: (id: number | string) => `/admin/sports/games/${id}`,

  /** Analytics */
  ANALYTICS: "/admin/analytics",
  ANALYTICS_TEAM: "/admin/analytics/team",
  ANALYTICS_PLAYER: "/admin/analytics/player",
  ANALYTICS_MATCHUP: "/admin/analytics/matchup",
  ANALYTICS_SIMULATOR: "/admin/analytics/simulator",
  ANALYTICS_MODEL_PERFORMANCE: "/admin/analytics/model-performance",
  ANALYTICS_FEATURE_CONFIG: "/admin/analytics/feature-config",
  ANALYTICS_MODELS: "/admin/analytics/models",
  ANALYTICS_ENSEMBLE: "/admin/analytics/ensemble",
  ANALYTICS_BASEBALL_MODELS: "/admin/analytics/baseball-models",
} as const;
