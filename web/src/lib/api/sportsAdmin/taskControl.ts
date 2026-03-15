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
  task_name: string;
  task_id: string;
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
