import { base, fetchJson } from "./analyticsShared";

import type {
  ExperimentSuite,
  ExperimentSuiteRequest,
  ReplayJob,
  ReplayRequest,
  TeamProfileResponse,
} from "./analyticsTypes";

// ---------------------------------------------------------------------------
// Team Profile
// ---------------------------------------------------------------------------

export async function getTeamProfile(
  team: string,
  rollingWindow: number = 30,
): Promise<TeamProfileResponse> {
  const params = new URLSearchParams({ team, rolling_window: String(rollingWindow) });
  return fetchJson<TeamProfileResponse>(`${base()}/api/analytics/team-profile?${params}`);
}

// Generic Team Profile (multi-sport)
export async function getTeamProfileMultiSport(
  team: string,
  sport: string,
  rollingWindow: number = 30,
): Promise<TeamProfileResponse> {
  const params = new URLSearchParams({
    team,
    sport: sport.toLowerCase(),
    rolling_window: String(rollingWindow),
  });
  return fetchJson<TeamProfileResponse>(`${base()}/api/analytics/team-profile?${params}`);
}

// ---------------------------------------------------------------------------
// Experiment Suites
// ---------------------------------------------------------------------------

export async function createExperimentSuite(
  req: ExperimentSuiteRequest,
): Promise<{ status: string; suite: ExperimentSuite }> {
  return fetchJson(`${base()}/api/analytics/experiments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function listExperimentSuites(
  sport?: string,
  status?: string,
): Promise<{ suites: ExperimentSuite[]; count: number }> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  if (status) params.set("status", status);
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/experiments${qs ? `?${qs}` : ""}`);
}

export async function getExperimentSuite(
  suiteId: number,
): Promise<ExperimentSuite> {
  return fetchJson<ExperimentSuite>(`${base()}/api/analytics/experiments/${suiteId}`);
}

export async function promoteExperimentVariant(
  suiteId: number,
  variantId: number,
): Promise<{ status: string; model_id: string; suite: ExperimentSuite }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}/promote/${variantId}`, {
    method: "POST",
  });
}

export async function cancelExperimentSuite(
  suiteId: number,
): Promise<{ status: string; suite: ExperimentSuite }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}/cancel`, {
    method: "POST",
  });
}

export async function deleteExperimentSuite(
  suiteId: number,
): Promise<{ status: string; id: number }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}`, {
    method: "DELETE",
  });
}

export async function deleteExperimentVariant(
  suiteId: number,
  variantId: number,
): Promise<{ status: string; variant_id: number }> {
  return fetchJson(`${base()}/api/analytics/experiments/${suiteId}/variant/${variantId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Historical Replay
// ---------------------------------------------------------------------------

export async function startReplay(
  req: ReplayRequest,
): Promise<{ status: string; job: ReplayJob }> {
  return fetchJson(`${base()}/api/analytics/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function listReplayJobs(
  sport?: string,
  suiteId?: number,
): Promise<{ jobs: ReplayJob[]; count: number }> {
  const params = new URLSearchParams();
  if (sport) params.set("sport", sport);
  if (suiteId !== undefined) params.set("suite_id", String(suiteId));
  const qs = params.toString();
  return fetchJson(`${base()}/api/analytics/replay-jobs${qs ? `?${qs}` : ""}`);
}
