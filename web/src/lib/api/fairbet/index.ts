/**
 * FairBet API client
 */

import { getApiBase } from "../apiBase";

/** Build headers including API key if configured. */
function buildHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // Add API key for authentication (server-side only)
  const apiKey = process.env.SPORTS_API_KEY;
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }

  return headers;
}

export interface BookOdds {
  book: string;
  price: number;
  observedAt: string;
  evPercent: number | null;
  displayEv: number | null;
  impliedProb: number | null;
  isSharp: boolean;
  evMethod: string | null;
  evConfidenceTier: string | null;
}

export interface BetDefinition {
  gameId: number;
  leagueCode: string;
  homeTeam: string;
  awayTeam: string;
  gameDate: string;
  marketKey: string;
  selectionKey: string;
  lineValue: number;
  marketCategory: string | null;
  playerName: string | null;
  description: string | null;
  trueProb: number | null;
  referencePrice: number | null;
  oppositeReferencePrice: number | null;
  evConfidenceTier: string | null;
  evDisabledReason: string | null;
  evMethod: string | null;
  hasFair: boolean;
  confidence: number | null;
  confidenceFlags: string[];
  books: BookOdds[];
  estimatedSharpPrice: number | null;
  extrapolationRefLine: number | null;
  extrapolationDistance: number | null;
  consensusBookCount: number | null;
  consensusIqr: number | null;
  perBookFairProbs: Record<string, number> | null;
}

export interface GameOption {
  gameId: number;
  matchup: string;
  gameDate: string | null;
}

export interface FairbetOddsResponse {
  bets: BetDefinition[];
  total: number;
  booksAvailable: string[];
  marketCategoriesAvailable: string[];
  gamesAvailable: GameOption[];
}

export interface FairbetLiveResponse {
  gameId: number;
  leagueCode: string;
  homeTeam: string;
  awayTeam: string;
  bets: BetDefinition[];
  total: number;
  booksAvailable: string[];
  marketCategoriesAvailable: string[];
  lastUpdatedAt: string | null;
  evDiagnostics: Record<string, number>;
}

export interface FairbetOddsFilters {
  league?: string;
  market_category?: string;
  exclude_categories?: string[];
  game_id?: number;
  book?: string;
  player_name?: string;
  min_ev?: number;
  sort_by?: string;
  limit?: number;
  offset?: number;
}

export interface FairbetLiveFilters {
  game_id: number;
  market_category?: string;
  sort_by?: string;
}

export async function fetchFairbetOdds(
  filters: FairbetOddsFilters = {}
): Promise<FairbetOddsResponse> {
  const params = new URLSearchParams();

  if (filters.league) params.set("league", filters.league);
  if (filters.market_category) params.set("market_category", filters.market_category);
  if (filters.exclude_categories) {
    for (const cat of filters.exclude_categories) {
      params.append("exclude_categories", cat);
    }
  }
  if (filters.game_id) params.set("game_id", filters.game_id.toString());
  if (filters.book) params.set("book", filters.book);
  if (filters.player_name) params.set("player_name", filters.player_name);
  if (filters.min_ev !== undefined) params.set("min_ev", filters.min_ev.toString());
  if (filters.sort_by) params.set("sort_by", filters.sort_by);
  if (filters.limit) params.set("limit", filters.limit.toString());
  if (filters.offset) params.set("offset", filters.offset.toString());

  const url = `${getApiBase()}/api/fairbet/odds?${params.toString()}`;
  const res = await fetch(url, {
    headers: buildHeaders(),
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch FairBet odds: ${res.statusText}`);
  }

  return res.json();
}

export interface LiveGameInfo {
  gameId: number;
  leagueCode: string;
  homeTeam: string;
  awayTeam: string;
  gameDate: string | null;
  status: string | null;
}

export async function fetchLiveGames(
  league?: string
): Promise<LiveGameInfo[]> {
  const params = new URLSearchParams();
  if (league) params.set("league", league);

  const url = `${getApiBase()}/api/fairbet/live/games?${params.toString()}`;
  const res = await fetch(url, {
    headers: buildHeaders(),
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch live games: ${res.statusText}`);
  }

  return res.json();
}

export async function fetchFairbetLiveOdds(
  filters: FairbetLiveFilters
): Promise<FairbetLiveResponse> {
  const params = new URLSearchParams();
  params.set("game_id", filters.game_id.toString());
  if (filters.market_category) params.set("market_category", filters.market_category);
  if (filters.sort_by) params.set("sort_by", filters.sort_by);

  const url = `${getApiBase()}/api/fairbet/live?${params.toString()}`;
  const res = await fetch(url, {
    headers: buildHeaders(),
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch live odds: ${res.statusText}`);
  }

  return res.json();
}

/**
 * Format American odds for display
 */
export function formatOdds(price: number): string {
  if (price >= 0) {
    return `+${price}`;
  }
  return price.toString();
}

/**
 * Get the best odds (highest for positive, lowest magnitude for negative)
 */
export function getBestOdds<T extends { price: number }>(books: T[]): T | null {
  if (books.length === 0) return null;

  return books.reduce((best, current) => {
    // For positive odds, higher is better
    // For negative odds, closer to 0 is better (e.g., -105 > -110)
    if (current.price > best.price) {
      return current;
    }
    return best;
  });
}

/**
 * Format selection key for display
 */
export function formatSelectionKey(key: string): string {
  // team:los_angeles_lakers -> Los Angeles Lakers
  // total:over -> Over
  // player:lebron_james:over -> LeBron James Over
  const parts = key.split(":");
  if (parts.length < 2) return key;

  const value = parts.slice(1).join(" ");
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Format market key for display
 */
export function formatMarketKey(key: string): string {
  const mapping: Record<string, string> = {
    h2h: "Moneyline",
    spreads: "Spread",
    totals: "Total",
    moneyline: "Moneyline",
    spread: "Spread",
    total: "Total",
    // Player prop markets
    player_points: "Points",
    player_rebounds: "Rebounds",
    player_assists: "Assists",
    player_threes: "3-Pointers",
    player_points_rebounds_assists: "PRA",
    player_blocks: "Blocks",
    player_steals: "Steals",
    player_goals: "Goals",
    player_shots_on_goal: "SOG",
    player_total_saves: "Saves",
    // MLB prop markets
    batter_hits: "Hits",
    batter_total_bases: "Total Bases",
    batter_rbis: "RBIs",
    batter_runs_scored: "Runs",
    batter_home_runs: "Home Runs",
    batter_stolen_bases: "Stolen Bases",
    pitcher_strikeouts: "Pitcher Ks",
    pitcher_outs: "Pitcher Outs",
    pitcher_hits_allowed: "Hits Allowed",
    pitcher_walks: "Pitcher Walks",
    pitcher_earned_runs: "Earned Runs",
    // Other markets
    team_totals: "Team Total",
    alternate_spreads: "Alt Spread",
    alternate_totals: "Alt Total",
  };
  return mapping[key.toLowerCase()] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Format market category for display
 */
export function formatMarketCategory(category: string): string {
  const mapping: Record<string, string> = {
    mainline: "Mainline",
    player_prop: "Player Prop",
    team_prop: "Team Prop",
    alternate: "Alternate",
    period: "Period",
    game_prop: "Game Prop",
  };
  return mapping[category] || category;
}

/**
 * Format EV percentage for display
 */
export function formatEv(ev: number | null): string {
  if (ev === null || ev === undefined) return "—";
  const sign = ev >= 0 ? "+" : "";
  return `${sign}${ev.toFixed(1)}%`;
}

/**
 * Get EV color class
 */
export function getEvColor(ev: number | null): "positive" | "negative" | "neutral" {
  if (ev === null || ev === undefined) return "neutral";
  if (ev > 0) return "positive";
  if (ev < 0) return "negative";
  return "neutral";
}

/**
 * Convert a true probability (0-1) to American odds
 */
export function trueProbToAmerican(prob: number): number {
  if (prob >= 1) return -10000;
  if (prob <= 0) return 10000;
  if (prob > 0.5) {
    return Math.round(-(prob / (1 - prob)) * 100);
  }
  return Math.round(((1 - prob) / prob) * 100);
}

/**
 * Convert American odds to implied probability (0-1)
 */
export function americanToImplied(price: number): number {
  if (price >= 100) return 100 / (price + 100);
  if (price <= -100) return Math.abs(price) / (Math.abs(price) + 100);
  return 0.5;
}

/**
 * Shin devig: remove vig accounting for favorite-longshot bias.
 * Returns true probability for `impliedThis` given both sides.
 */
export function shinDevig(impliedThis: number, impliedOther: number): number {
  const total = impliedThis + impliedOther;
  if (total <= 0) return impliedThis;

  const z = 1.0 - 1.0 / total;

  // Fall back to additive when no meaningful overround
  if (z <= 0) return impliedThis / total;

  const numerator = Math.sqrt(z * z + (4.0 * (1.0 - z) * impliedThis * impliedThis) / total) - z;
  const denominator = 2.0 * (1.0 - z);
  return numerator / denominator;
}

/**
 * Map ev_disabled_reason codes to human-readable popover content
 */
export function formatDisabledReason(reason: string | null): { title: string; detail: string } {
  switch (reason) {
    case "no_strategy":
      return { title: "Not Supported", detail: "Fair odds aren't calculated for this market type." };
    case "reference_missing":
      return { title: "No Sharp Line", detail: "Pinnacle doesn't have odds on both sides of this market." };
    case "reference_stale":
      return { title: "Stale Data", detail: "The Pinnacle line is too old to use as a reference." };
    case "insufficient_books":
      return { title: "Too Few Books", detail: "Need at least 3 books on each side to calculate fair odds." };
    case "extrapolation_exceeds_pinnacle":
      return { title: "Extrapolation Invalid", detail: "Estimated fair odds exceed Pinnacle's actual price — extrapolation unreliable for this line." };
    case "extrapolation_out_of_range":
      return { title: "Too Far From Reference", detail: "The closest Pinnacle reference line is too far away for reliable extrapolation." };
    default:
      return { title: "Unavailable", detail: "Fair odds can't be calculated for this bet." };
  }
}
