/** API client functions for golf pool endpoints. */

import { request } from "./sportsAdmin/client";
import type {
  GolfPool,
  GolfPoolEntry,
  GolfPoolLeaderboardEntry,
} from "./golfPoolTypes";
import type { TriggerTaskResponse } from "./sportsAdmin/taskControl";

// ── Pool listing ──

export interface PoolFilters {
  club_code?: string;
  tournament_id?: number;
  status?: string;
  active_only?: boolean;
  limit?: number;
}

export async function listPools(
  params?: PoolFilters
): Promise<GolfPool[]> {
  const query = new URLSearchParams();
  if (params?.club_code) query.append("club_code", params.club_code);
  if (params?.tournament_id != null) query.append("tournament_id", String(params.tournament_id));
  if (params?.status) query.append("status", params.status);
  if (params?.active_only) query.append("active_only", "true");
  if (params?.limit != null) query.append("limit", String(params.limit));
  const qs = query.toString();
  const res = await request<{ pools: GolfPool[]; count: number }>(
    `/api/golf/pools${qs ? `?${qs}` : ""}`
  );
  return res.pools;
}

// ── Pool detail ──

export async function fetchPool(poolId: number | string): Promise<GolfPool> {
  return request(`/api/golf/pools/${poolId}`);
}

// ── Pool field (available golfers) ──

export interface PoolFieldResponse {
  pool_id: number;
  format: "flat" | "bucketed";
  field?: { dg_id: number; player_name: string | null; status: string }[];
  buckets?: { bucket_number: number; label: string | null; players: { dg_id: number; player_name: string }[] }[];
  count?: number;
}

export async function fetchPoolField(
  poolId: number | string
): Promise<PoolFieldResponse> {
  return request(`/api/golf/pools/${poolId}/field`);
}

// ── Pool leaderboard (materialized scores) ──

export async function fetchPoolLeaderboard(
  poolId: number | string
): Promise<GolfPoolLeaderboardEntry[]> {
  const res = await request<{ pool_id: number; leaderboard: GolfPoolLeaderboardEntry[]; count: number }>(
    `/api/golf/pools/${poolId}/leaderboard`
  );
  return res.leaderboard;
}

// ── Pool entries ──

export async function fetchPoolEntries(
  poolId: number | string,
  filters?: { email?: string; status?: string; source?: string }
): Promise<GolfPoolEntry[]> {
  const query = new URLSearchParams();
  if (filters?.email) query.append("email", filters.email);
  if (filters?.status) query.append("status", filters.status);
  if (filters?.source) query.append("source", filters.source);
  const qs = query.toString();
  const res = await request<{ entries: GolfPoolEntry[]; count: number }>(
    `/api/golf/pools/${poolId}/entries${qs ? `?${qs}` : ""}`
  );
  return res.entries;
}

// ── Entries by email ──

export async function fetchEntriesByEmail(
  poolId: number | string,
  email: string
): Promise<GolfPoolEntry[]> {
  const res = await request<{ entries: GolfPoolEntry[]; count: number }>(
    `/api/golf/pools/${poolId}/entries/by-email?email=${encodeURIComponent(email)}`
  );
  return res.entries;
}

// ── Submit entry ──

export interface SubmitEntryPayload {
  email: string;
  entry_name?: string;
  picks: { dg_id: number; pick_slot: number; bucket_number?: number }[];
}

export async function submitPoolEntry(
  poolId: number | string,
  payload: SubmitEntryPayload
): Promise<{ status: string; entry: GolfPoolEntry }> {
  return request(`/api/golf/pools/${poolId}/entries`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ── Create pool ──

export interface CreatePoolPayload {
  code: string;
  name: string;
  club_code: string;
  tournament_id: number;
  rules_json?: Record<string, unknown>;
  entry_deadline?: string;
  entry_open_at?: string;
  status?: string;
  max_entries_per_email?: number;
  scoring_enabled?: boolean;
  require_upload?: boolean;
  allow_self_service_entry?: boolean;
  notes?: string;
}

export async function createPool(
  payload: CreatePoolPayload
): Promise<GolfPool> {
  return request("/api/golf/pools", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ── Admin operations ──

export async function rescorePool(
  poolId: number | string
): Promise<TriggerTaskResponse> {
  return request(`/api/golf/pools/${poolId}/rescore`, {
    method: "POST",
  });
}

export async function goLivePool(
  poolId: number | string
): Promise<GolfPool> {
  return request(`/api/golf/pools/${poolId}/go-live`, {
    method: "POST",
  });
}

export async function lockPool(
  poolId: number | string
): Promise<GolfPool> {
  return request(`/api/golf/pools/${poolId}/lock`, {
    method: "POST",
  });
}

// ── Delete entry ──

export async function deletePoolEntry(
  poolId: number | string,
  entryId: number
): Promise<{ status: string; entry_id: number; email: string }> {
  return request(`/api/golf/pools/${poolId}/entries/${entryId}`, {
    method: "DELETE",
  });
}

// ── Export entries CSV ──

export function entriesExportUrl(poolId: number | string): string {
  return `/proxy/api/golf/pools/${poolId}/entries/export`;
}
