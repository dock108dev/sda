import { request } from "./client";
import type { AdminGameDetail, GameFilters, GameListResponse, JobResponse } from "./types";
import type { FlowStatusResponse, GameFlowResponse } from "./gameFlowTypes";

export async function listGames(filters: GameFilters): Promise<GameListResponse> {
  const query = new URLSearchParams();
  const leagues = filters?.leagues ?? [];
  if (leagues.length) {
    leagues.forEach((lg) => query.append("league", lg));
  }
  if (filters?.season) query.append("season", String(filters.season));
  if (filters?.team) query.append("team", filters.team);
  if (filters?.startDate) query.append("startDate", filters.startDate);
  if (filters?.endDate) query.append("endDate", filters.endDate);
  if (filters?.missingBoxscore) query.append("missingBoxscore", "true");
  if (filters?.missingPlayerStats) query.append("missingPlayerStats", "true");
  if (filters?.missingOdds) query.append("missingOdds", "true");
  if (filters?.missingSocial) query.append("missingSocial", "true");
  if (filters?.missingAny) query.append("missingAny", "true");
  if (filters?.hasPbp) query.append("hasPbp", "true");
  if (filters?.finalOnly) query.append("finalOnly", "true");
  if (typeof filters?.limit === "number") query.append("limit", String(filters.limit));
  if (typeof filters?.offset === "number") query.append("offset", String(filters.offset));
  const qs = query.toString();
  return request(`/api/admin/sports/games${qs ? `?${qs}` : ""}`);
}

export async function fetchGame(gameId: number | string): Promise<AdminGameDetail> {
  const idStr = String(gameId);
  if (!/^\d+$/.test(idStr)) {
    throw new Error(`Invalid game id: ${idStr}`);
  }
  return request(`/api/admin/sports/games/${idStr}`);
}

export async function resyncGame(gameId: number): Promise<JobResponse> {
  return request(`/api/admin/sports/games/${gameId}/resync`, { method: "POST" });
}

/**
 * Fetch the game flow for a game.
 * Returns null only on 404 (game not found).
 * Returns FlowStatusResponse when the flow is not yet available (RECAP_PENDING, PREGAME, etc.).
 * Returns GameFlowResponse when the flow is available.
 */
export async function fetchGameFlow(
  gameId: number,
): Promise<GameFlowResponse | FlowStatusResponse | null> {
  try {
    return await request(`/api/admin/sports/games/${gameId}/flow`);
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("Request failed (404)")) {
      return null;
    }
    throw err;
  }
}
