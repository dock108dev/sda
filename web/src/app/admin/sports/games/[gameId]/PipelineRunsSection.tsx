"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  getPipelineRuns,
  runFullPipeline,
  type PipelineRunSummary,
  type PipelineStageStatus,
} from "@/lib/api/sportsAdmin/pipeline";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

interface PipelineRunsSectionProps {
  gameId: number;
}

const PIPELINE_STAGES = [
  "NORMALIZE_PBP",
  "GENERATE_MOMENTS",
  "VALIDATE_MOMENTS",
  "ANALYZE_DRAMA",
  "GROUP_BLOCKS",
  "RENDER_BLOCKS",
  "VALIDATE_BLOCKS",
  "FINALIZE_MOMENTS",
];

function formatDuration(start: string, end: string | null): string {
  if (!end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}m ${remaining}s`;
}

function formatTime(ts: string): string {
  return new Date(ts).toLocaleString();
}

function stageStatusColor(status: PipelineStageStatus["status"]): string {
  switch (status) {
    case "success":
      return "#16a34a";
    case "failed":
      return "#dc2626";
    case "running":
      return "#2563eb";
    case "skipped":
      return "#94a3b8";
    case "pending":
    default:
      return "#d1d5db";
  }
}

function runStatusLabel(status: PipelineRunSummary["status"]): { text: string; color: string } {
  switch (status) {
    case "completed":
      return { text: "Completed", color: "#16a34a" };
    case "failed":
      return { text: "Failed", color: "#dc2626" };
    case "running":
      return { text: "Running", color: "#2563eb" };
    case "paused":
      return { text: "Paused", color: "#f59e0b" };
    case "pending":
    default:
      return { text: "Pending", color: "#94a3b8" };
  }
}

export function PipelineRunsSection({ gameId }: PipelineRunsSectionProps) {
  const [runs, setRuns] = useState<PipelineRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null);
  const [runningPipeline, setRunningPipeline] = useState(false);
  const [runMessage, setRunMessage] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getPipelineRuns(gameId);
      setRuns(response.runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [gameId]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const handleRunPipeline = async () => {
    setRunningPipeline(true);
    setRunMessage(null);
    try {
      const result = await runFullPipeline(gameId, "admin_ui");
      setRunMessage(result.message || "Pipeline run started");
      loadRuns();
    } catch (err) {
      setRunMessage(err instanceof Error ? err.message : "Failed to start pipeline");
    } finally {
      setRunningPipeline(false);
    }
  };

  const toggleExpand = (id: number) => {
    setExpandedRunId((prev) => (prev === id ? null : id));
  };

  return (
    <CollapsibleSection title="Pipeline Runs" defaultOpen={false}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
        <button
          type="button"
          onClick={handleRunPipeline}
          disabled={runningPipeline}
          style={{
            padding: "0.5rem 1rem",
            borderRadius: 8,
            border: "1px solid #cbd5e1",
            background: "#2563eb",
            color: "#fff",
            fontWeight: 600,
            cursor: runningPipeline ? "not-allowed" : "pointer",
            opacity: runningPipeline ? 0.6 : 1,
          }}
        >
          {runningPipeline ? "Running..." : "Run Pipeline"}
        </button>
        {runMessage && (
          <span style={{ fontSize: "0.85rem", color: "#475569" }}>{runMessage}</span>
        )}
      </div>

      {loading && <div style={{ color: "#475569" }}>Loading pipeline runs...</div>}
      {error && <div style={{ color: "#dc2626" }}>Error: {error}</div>}

      {!loading && !error && runs.length === 0 && (
        <div style={{ color: "#475569", fontStyle: "italic" }}>No pipeline runs for this game</div>
      )}

      {!loading && !error && runs.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Triggered By</th>
              <th>Status</th>
              <th>Started</th>
              <th>Duration</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const statusInfo = runStatusLabel(run.status);
              const isExpanded = expandedRunId === run.runId;
              return (
                <React.Fragment key={run.runId}>
                  <tr style={{ cursor: "pointer" }} onClick={() => toggleExpand(run.runId)}>
                    <td>{run.runId}</td>
                    <td>{run.triggeredBy}</td>
                    <td>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "0.2rem 0.6rem",
                          borderRadius: "999px",
                          fontSize: "0.8rem",
                          fontWeight: 600,
                          color: "#fff",
                          background: statusInfo.color,
                        }}
                      >
                        {statusInfo.text}
                      </span>
                    </td>
                    <td>{run.startedAt ? formatTime(run.startedAt) : "—"}</td>
                    <td>{run.startedAt ? formatDuration(run.startedAt, run.finishedAt) : "—"}</td>
                    <td style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
                      {isExpanded ? "▲" : "▼"}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={6} style={{ padding: "0.5rem 1rem", background: "#f8fafc" }}>
                        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                          {PIPELINE_STAGES.map((stageName, idx) => {
                            const stage = run.stages.find(
                              (s) => s.stage === stageName
                            );
                            const color = stage
                              ? stageStatusColor(stage.status)
                              : "#d1d5db";
                            const label = stage?.status ?? "pending";
                            return (
                              <div key={stageName} style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                                <span
                                  title={`${stageName}: ${label}${stage?.errorDetails ? ` — ${stage.errorDetails}` : ""}`}
                                  style={{
                                    display: "inline-block",
                                    padding: "0.2rem 0.5rem",
                                    borderRadius: "4px",
                                    fontSize: "0.7rem",
                                    fontWeight: 600,
                                    color: "#fff",
                                    background: color,
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {stageName.replace(/_/g, " ")}
                                </span>
                                {idx < PIPELINE_STAGES.length - 1 && (
                                  <span style={{ color: "#cbd5e1", fontSize: "0.7rem" }}>→</span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                        {run.stages.some((s) => s.errorDetails) && (
                          <div style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "#dc2626" }}>
                            {run.stages
                              .filter((s) => s.errorDetails)
                              .map((s) => (
                                <div key={s.stage}>
                                  <strong>{s.stage}:</strong> {s.errorDetails}
                                </div>
                              ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </CollapsibleSection>
  );
}
