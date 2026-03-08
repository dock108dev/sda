"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  getModelDetails,
  startBacktest,
  listBacktestJobs,
  type ModelDetails,
  type BacktestJob,
} from "@/lib/api/analytics";
import styles from "../../analytics.module.css";

export default function ModelDetailPage() {
  const params = useParams();
  const modelId = decodeURIComponent(params.modelId as string);
  const [model, setModel] = useState<ModelDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getModelDetails(modelId);
        setModel(res);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [modelId]);

  if (loading) return <div className={styles.container}><p>Loading model details...</p></div>;
  if (error) return <div className={styles.container}><div className={styles.error}>{error}</div></div>;
  if (!model) return <div className={styles.container}><p>Model not found.</p></div>;

  const metricEntries = Object.entries(model.metrics || {}).filter(
    ([, v]) => typeof v === "number",
  );

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <p style={{ marginBottom: "0.5rem" }}>
          <Link href="/admin/analytics/models" style={{ textDecoration: "underline" }}>
            &larr; Back to Models
          </Link>
        </p>
        <h1 className={styles.pageTitle}>{model.model_id}</h1>
        <p className={styles.pageSubtitle}>
          {model.sport?.toUpperCase()} / {model.model_type}
        </p>
      </header>

      {/* Overview */}
      <AdminCard title="Overview">
        <div className={styles.metricsGrid}>
          <div className={styles.metricItem}>
            <span className={styles.metricLabel}>Version</span>
            <span className={styles.metricValue}>v{model.version}</span>
          </div>
          <div className={styles.metricItem}>
            <span className={styles.metricLabel}>Status</span>
            <span className={styles.metricValue}>
              {model.active ? (
                <span style={{ color: "#22c55e" }}>Active</span>
              ) : (
                "Inactive"
              )}
            </span>
          </div>
          <div className={styles.metricItem}>
            <span className={styles.metricLabel}>Created</span>
            <span className={styles.metricValue}>
              {model.created_at ? new Date(model.created_at).toLocaleDateString() : "-"}
            </span>
          </div>
          {model.training_row_count != null && (
            <div className={styles.metricItem}>
              <span className={styles.metricLabel}>Training Rows</span>
              <span className={styles.metricValue}>
                {model.training_row_count.toLocaleString()}
              </span>
            </div>
          )}
        </div>
      </AdminCard>

      {/* Evaluation Metrics */}
      {metricEntries.length > 0 && (
        <AdminCard title="Evaluation Metrics" subtitle="Stored metrics from training evaluation">
          <div className={styles.metricsGrid}>
            {metricEntries.map(([key, val]) => (
              <div key={key} className={styles.metricItem}>
                <span className={styles.metricLabel}>{key}</span>
                <span className={styles.metricValue}>
                  {(val as number).toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </AdminCard>
      )}

      {/* Feature Importance */}
      {model.feature_importance && model.feature_importance.length > 0 && (
        <AdminCard
          title="Feature Importance"
          subtitle="Which features matter most to this model"
        >
          <FeatureImportanceChart features={model.feature_importance} />
        </AdminCard>
      )}

      {/* Backtest Section */}
      <BacktestPanel model={model} />

      {/* Artifact Info */}
      <AdminCard title="Artifact Details">
        <table style={{ width: "100%", fontSize: "0.9rem" }}>
          <tbody>
            {model.artifact_path && (
              <tr>
                <td style={{ padding: "0.4rem 0", color: "var(--text-muted)", width: "180px" }}>Artifact Path</td>
                <td style={{ padding: "0.4rem 0", fontFamily: "monospace", fontSize: "0.85rem" }}>{model.artifact_path}</td>
              </tr>
            )}
            {model.metadata_path && (
              <tr>
                <td style={{ padding: "0.4rem 0", color: "var(--text-muted)" }}>Metadata Path</td>
                <td style={{ padding: "0.4rem 0", fontFamily: "monospace", fontSize: "0.85rem" }}>{model.metadata_path}</td>
              </tr>
            )}
            {model.feature_config && (
              <tr>
                <td style={{ padding: "0.4rem 0", color: "var(--text-muted)" }}>Feature Config</td>
                <td style={{ padding: "0.4rem 0" }}>{model.feature_config}</td>
              </tr>
            )}
            {model.random_state != null && (
              <tr>
                <td style={{ padding: "0.4rem 0", color: "var(--text-muted)" }}>Random State</td>
                <td style={{ padding: "0.4rem 0" }}>{model.random_state}</td>
              </tr>
            )}
          </tbody>
        </table>
      </AdminCard>
    </div>
  );
}


function BacktestPanel({ model }: { model: ModelDetails }) {
  const [jobs, setJobs] = useState<BacktestJob[]>([]);
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [rollingWindow, setRollingWindow] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [expandedJob, setExpandedJob] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await listBacktestJobs(model.model_id);
      setJobs(res.jobs);
    } catch {
      // ignore
    }
  }, [model.model_id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll for in-progress jobs
  useEffect(() => {
    const active = jobs.filter(
      (j) => j.status === "pending" || j.status === "queued" || j.status === "running",
    );
    if (active.length === 0) return;

    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [jobs, refresh]);

  const handleBacktest = async () => {
    if (!model.artifact_path) {
      setError("Model has no artifact path");
      return;
    }
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await startBacktest({
        model_id: model.model_id,
        artifact_path: model.artifact_path,
        sport: model.sport,
        model_type: model.model_type,
        date_start: dateStart || undefined,
        date_end: dateEnd || undefined,
        rolling_window: rollingWindow,
      });
      setMessage(`Backtest job #${res.job.id} submitted`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AdminCard title="Backtest" subtitle="Run model against held-out games">
      <div className={styles.formRow}>
        <div className={styles.formGroup}>
          <label>Date Start</label>
          <input
            type="date"
            value={dateStart}
            onChange={(e) => setDateStart(e.target.value)}
          />
        </div>
        <div className={styles.formGroup}>
          <label>Date End</label>
          <input
            type="date"
            value={dateEnd}
            onChange={(e) => setDateEnd(e.target.value)}
          />
        </div>
        <div className={styles.formGroup}>
          <label>Rolling Window: {rollingWindow}</label>
          <input
            type="range"
            min={5}
            max={80}
            step={5}
            value={rollingWindow}
            onChange={(e) => setRollingWindow(parseInt(e.target.value))}
          />
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {message && <div className={styles.success}>{message}</div>}

      <button
        className={`${styles.btn} ${styles.btnPrimary}`}
        onClick={handleBacktest}
        disabled={submitting || !model.artifact_path}
        style={{ marginTop: "0.5rem" }}
      >
        {submitting ? "Submitting..." : "Run Backtest"}
      </button>

      {/* Backtest Results */}
      {jobs.length > 0 && (
        <div style={{ marginTop: "1.5rem" }}>
          <h4 style={{ marginBottom: "0.5rem" }}>Backtest History</h4>
          <AdminTable headers={["ID", "Date Range", "Window", "Status", "Accuracy", "Brier", "Games", ""]}>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>#{job.id}</td>
                <td style={{ fontSize: "0.85rem" }}>
                  {job.date_start || "all"} - {job.date_end || "all"}
                </td>
                <td>{job.rolling_window}</td>
                <td><StatusBadge status={job.status} /></td>
                <td>
                  {job.metrics?.accuracy != null
                    ? `${(job.metrics.accuracy * 100).toFixed(1)}%`
                    : "-"}
                </td>
                <td>
                  {job.metrics?.brier_score != null
                    ? job.metrics.brier_score.toFixed(4)
                    : "-"}
                </td>
                <td>{job.game_count ?? "-"}</td>
                <td>
                  {job.predictions && job.predictions.length > 0 && (
                    <button
                      className={styles.btn}
                      onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
                      style={{ fontSize: "0.8rem", padding: "2px 8px" }}
                    >
                      {expandedJob === job.id ? "Hide" : "Details"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </AdminTable>

          {/* Expanded prediction details */}
          {expandedJob && (() => {
            const job = jobs.find((j) => j.id === expandedJob);
            if (!job?.predictions) return null;
            return (
              <div style={{ marginTop: "1rem" }}>
                <h4 style={{ marginBottom: "0.5rem" }}>
                  Predictions for Backtest #{job.id}
                  <span style={{ fontWeight: "normal", fontSize: "0.85rem", marginLeft: "0.5rem" }}>
                    ({job.correct_count}/{job.game_count} correct)
                  </span>
                </h4>
                <div style={{ maxHeight: "400px", overflow: "auto" }}>
                  <AdminTable headers={["#", "Predicted", "Actual", "Result", "Score", "Home Win Prob"]}>
                    {job.predictions.map((p, i) => (
                      <tr key={i} style={{ background: p.correct ? undefined : "rgba(239, 68, 68, 0.08)" }}>
                        <td>{i + 1}</td>
                        <td>{p.predicted === 1 ? "Home" : "Away"}</td>
                        <td>{p.actual === 1 ? "Home" : "Away"}</td>
                        <td>
                          <span style={{
                            color: p.correct ? "#22c55e" : "#ef4444",
                            fontWeight: "bold",
                            fontSize: "0.85rem",
                          }}>
                            {p.correct ? "Correct" : "Wrong"}
                          </span>
                        </td>
                        <td style={{ fontSize: "0.85rem" }}>
                          {p.home_score != null && p.away_score != null
                            ? `${p.home_score}-${p.away_score}`
                            : "-"}
                        </td>
                        <td style={{ fontSize: "0.85rem" }}>
                          {p.probabilities?.["1"] != null
                            ? `${(p.probabilities["1"] * 100).toFixed(1)}%`
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </AdminTable>
                </div>
              </div>
            );
          })()}
        </div>
      )}
    </AdminCard>
  );
}


function FeatureImportanceChart({
  features,
}: {
  features: { name: string; importance: number }[];
}) {
  const maxImportance = Math.max(...features.map((f) => f.importance), 0.001);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
      {features.map((f) => {
        const pct = (f.importance / maxImportance) * 100;
        return (
          <div key={f.name} style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <span
              style={{
                width: "180px",
                flexShrink: 0,
                fontSize: "0.85rem",
                textAlign: "right",
                color: "var(--text-muted)",
              }}
            >
              {f.name}
            </span>
            <div
              style={{
                flex: 1,
                background: "var(--bg-secondary, #f3f4f6)",
                borderRadius: "4px",
                height: "20px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: "var(--accent, #3b82f6)",
                  borderRadius: "4px",
                  transition: "width 0.3s ease",
                }}
              />
            </div>
            <span style={{ width: "60px", fontSize: "0.8rem", color: "var(--text-muted)" }}>
              {(f.importance * 100).toFixed(1)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}


function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; text: string }> = {
    pending: { bg: "#fef3c7", text: "#92400e" },
    queued: { bg: "#dbeafe", text: "#1e40af" },
    running: { bg: "#dbeafe", text: "#1e40af" },
    completed: { bg: "#dcfce7", text: "#166534" },
    failed: { bg: "#fee2e2", text: "#991b1b" },
  };
  const c = colors[status] || { bg: "#f3f4f6", text: "#374151" };
  return (
    <span
      style={{
        background: c.bg,
        color: c.text,
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "0.8rem",
        fontWeight: 500,
      }}
    >
      {status}
    </span>
  );
}
