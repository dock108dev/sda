import { request } from "./client";

export interface PipelineStageStatus {
  stage: string;
  stageOrder: number;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  startedAt: string | null;
  finishedAt: string | null;
  durationSeconds: number | null;
  errorDetails: string | null;
  hasOutput: boolean;
  outputSummary: Record<string, unknown> | null;
  logCount: number;
  canExecute: boolean;
}

export interface PipelineRunSummary {
  runId: number;
  runUuid: string;
  gameId: number;
  triggeredBy: string;
  status: "pending" | "running" | "completed" | "failed" | "paused";
  currentStage: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  stagesCompleted: number;
  stagesTotal: number;
  progressPercent: number;
  stages: PipelineStageStatus[];
}

export interface RunFullPipelineResponse {
  runId: number;
  runUuid: string;
  gameId: number;
  status: string;
  stagesCompleted: number;
  stagesFailed: number;
  durationSeconds: number | null;
  artifactId: number | null;
  message: string;
}

export interface GamePipelineRunsResponse {
  gameId: number;
  gameInfo: Record<string, unknown>;
  runs: PipelineRunSummary[];
  totalRuns: number;
  hasSuccessfulRun: boolean;
  latestArtifactAt: string | null;
}

export async function runFullPipeline(
  gameId: number,
  triggeredBy: string = "admin_ui"
): Promise<RunFullPipelineResponse> {
  return request(`/api/admin/sports/pipeline/${gameId}/run-full`, {
    method: "POST",
    body: JSON.stringify({
      triggered_by: triggeredBy,
    }),
  });
}

export async function getPipelineRuns(
  gameId: number
): Promise<GamePipelineRunsResponse> {
  return request(`/api/admin/sports/pipeline/game/${gameId}`);
}
