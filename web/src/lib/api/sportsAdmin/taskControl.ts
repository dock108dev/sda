import { request } from "./client";
import type { ScrapeRunConfig, ScrapeRunResponse } from "./types";

// ── Hold status ──

export interface HoldStatus {
  held: boolean;
}

export async function getHoldStatus(): Promise<HoldStatus> {
  return request("/api/admin/tasks/hold");
}

export async function setHoldStatus(held: boolean): Promise<HoldStatus> {
  return request("/api/admin/tasks/hold", {
    method: "PUT",
    body: JSON.stringify({ held }),
  });
}

// ── Task trigger ──

export interface TriggerTaskResponse {
  status: string;
  taskName: string;
  taskId: string;
}

export async function triggerTask(
  taskName: string,
  args: unknown[]
): Promise<TriggerTaskResponse> {
  return request("/api/admin/tasks/trigger", {
    method: "POST",
    body: JSON.stringify({ task_name: taskName, args }),
  });
}

// ── Backfill endpoints ──

export async function createScrapeRun(
  config: ScrapeRunConfig
): Promise<ScrapeRunResponse> {
  return request("/api/admin/sports/scraper/runs", {
    method: "POST",
    body: JSON.stringify({
      requestedBy: "admin-backfill",
      config,
    }),
  });
}

// ── Bulk backfill ──

export interface BulkBackfillParams {
  leagues: string[];
  startDate: string;
  endDate: string;
  boxscores?: boolean;
  odds?: boolean;
  pbp?: boolean;
  social?: boolean;
  advancedStats?: boolean;
  onlyMissing?: boolean;
}

export interface BulkBackfillChunk {
  leagueCode: string;
  startDate: string;
  endDate: string;
  runId?: number | null;
  jobId?: string | null;
  error?: string | null;
}

export interface BulkBackfillResponse {
  totalChunks: number;
  chunksDispatched: number;
  chunks: BulkBackfillChunk[];
}

export async function previewBulkBackfill(
  params: BulkBackfillParams
): Promise<{ totalChunks: number; chunks: BulkBackfillChunk[] }> {
  return request("/api/admin/sports/scraper/runs/bulk-preview", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function createBulkBackfill(
  params: BulkBackfillParams
): Promise<BulkBackfillResponse> {
  return request("/api/admin/sports/scraper/runs/bulk", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export interface BulkFlowParams {
  start_date: string;
  end_date: string;
  leagues: string[];
  force: boolean;
}

export interface BulkFlowResponse {
  job_id: string;
  message: string;
}

export async function triggerBulkFlowGeneration(
  params: BulkFlowParams
): Promise<BulkFlowResponse> {
  return request("/api/admin/sports/pipeline/bulk-generate-async", {
    method: "POST",
    body: JSON.stringify(params),
  });
}
