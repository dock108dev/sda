"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  listFeatureLoadouts,
  startTraining,
  listTrainingJobs,
  cancelTrainingJob,
  type FeatureLoadout,
  type TrainingJob,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    pending: { bg: "#f0f0f0", fg: "#666" },
    queued: { bg: "#fff3cd", fg: "#856404" },
    running: { bg: "#cce5ff", fg: "#004085" },
    completed: { bg: "#d4edda", fg: "#155724" },
    failed: { bg: "#f8d7da", fg: "#721c24" },
  };
  const c = colors[status] || colors.pending;
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "0.75rem",
        fontWeight: 600,
        background: c.bg,
        color: c.fg,
      }}
    >
      {status}
    </span>
  );
}

export function TrainingPanel({ sportCode = "mlb" }: { sportCode?: string }) {
  const [loadouts, setLoadouts] = useState<FeatureLoadout[]>([]);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [expandedJobId, setExpandedJobId] = useState<number | null>(null);
  const [selectedLoadout, setSelectedLoadout] = useState<number | null>(null);
  const modelType = "plate_appearance";
  const [algorithm, setAlgorithm] = useState("gradient_boosting");
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [testSplit, setTestSplit] = useState(0.2);
  const [rollingWindow, setRollingWindow] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [loadoutRes, jobsRes] = await Promise.all([
        listFeatureLoadouts(sportCode),
        listTrainingJobs(sportCode),
      ]);
      setLoadouts(loadoutRes.loadouts);
      setJobs(jobsRes.jobs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [sportCode]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll for in-progress jobs
  useEffect(() => {
    const activeJobs = jobs.filter(
      (j) => j.status === "pending" || j.status === "queued" || j.status === "running",
    );
    if (activeJobs.length === 0) return;

    const interval = setInterval(async () => {
      try {
        const jobsRes = await listTrainingJobs(sportCode);
        setJobs(jobsRes.jobs);
      } catch (err) {
        console.warn("Training job poll failed:", err);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [jobs, sportCode]);

  const [cancelingIds, setCancelingIds] = useState<Set<number>>(new Set());

  const handleCancel = async (jobId: number) => {
    setCancelingIds((prev) => new Set(prev).add(jobId));
    try {
      await cancelTrainingJob(jobId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCancelingIds((prev) => {
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
    }
  };

  const handleTrain = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await startTraining({
        feature_config_id: selectedLoadout,
        sport: sportCode,
        model_type: modelType,
        algorithm,
        date_start: dateStart || undefined,
        date_end: dateEnd || undefined,
        test_split: testSplit,
        rolling_window: rollingWindow,
      });
      setMessage(`Training job #${res.job.id} submitted`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
      {/* Training Form */}
      <AdminCard title="Train Model" subtitle="Configure and start a training job">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Feature Loadout</label>
            <select
              value={selectedLoadout ?? ""}
              onChange={(e) =>
                setSelectedLoadout(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">None (use defaults)</option>
              {loadouts.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.enabled_count} features)
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Algorithm</label>
            <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
              <option value="gradient_boosting">Gradient Boosting</option>
              <option value="random_forest">Random Forest</option>
              <option value="xgboost">XGBoost</option>
            </select>
          </div>
        </div>

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
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Test Split: {(testSplit * 100).toFixed(0)}%</label>
            <input
              type="range"
              min={0.05}
              max={0.5}
              step={0.05}
              value={testSplit}
              onChange={(e) => setTestSplit(parseFloat(e.target.value))}
            />
          </div>
          <div className={styles.formGroup}>
            <label>Rolling Window: {rollingWindow} games</label>
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
          onClick={handleTrain}
          disabled={submitting}
          style={{ marginTop: "1rem" }}
        >
          {submitting ? "Submitting..." : "Train Model"}
        </button>
      </AdminCard>

      {/* Training Jobs List */}
      <AdminCard title="Training Jobs" subtitle={`${jobs.length} jobs`}>
        {jobs.length === 0 ? (
          <p style={{ color: "#666" }}>No training jobs yet. Start one from the form.</p>
        ) : (
          <AdminTable headers={["ID", "Algorithm", "Status", "Metrics", "Actions"]}>
            {jobs.flatMap((job) => [
              <tr key={job.id}>
                <td>#{job.id}</td>
                <td style={{ fontSize: "0.85rem" }}>{job.algorithm}</td>
                <td>
                  <StatusBadge status={job.status} />
                </td>
                <td style={{ fontSize: "0.8rem" }}>
                  {job.metrics ? (
                    <span
                      style={{ cursor: "pointer", textDecoration: "underline dotted" }}
                      onClick={() => setExpandedJobId(expandedJobId === job.id ? null : job.id)}
                    >
                      acc: {((job.metrics.accuracy ?? 0) * 100).toFixed(1)}%
                      {job.metrics.brier_score != null && (
                        <> &middot; brier: {job.metrics.brier_score.toFixed(3)}</>
                      )}
                    </span>
                  ) : job.error_message ? (
                    <span
                      style={{ color: "#c00", cursor: "pointer", textDecoration: "underline dotted" }}
                      onClick={() => setExpandedJobId(expandedJobId === job.id ? null : job.id)}
                    >
                      Error
                    </span>
                  ) : (
                    <span style={{ color: "#999" }}>--</span>
                  )}
                </td>
                <td>
                  {["pending", "queued", "running"].includes(job.status) ? (
                    <button
                      onClick={() => handleCancel(job.id)}
                      disabled={cancelingIds.has(job.id)}
                      style={{
                        padding: "2px 8px",
                        fontSize: "0.75rem",
                        borderRadius: "4px",
                        border: "1px solid #c00",
                        background: "#fff",
                        color: "#c00",
                        cursor: cancelingIds.has(job.id) ? "not-allowed" : "pointer",
                        opacity: cancelingIds.has(job.id) ? 0.6 : 1,
                      }}
                    >
                      {cancelingIds.has(job.id) ? "Canceling..." : "Cancel"}
                    </button>
                  ) : (
                    <span style={{ color: "#999" }}>--</span>
                  )}
                </td>
              </tr>,
              expandedJobId === job.id && (job.error_message || job.metrics) ? (
                <tr key={`${job.id}-detail`}>
                  <td colSpan={5} style={{ padding: "0.5rem 1rem", background: "#fafbfc" }}>
                    {job.error_message && (
                      <pre style={{
                        fontFamily: "monospace",
                        fontSize: "0.8rem",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        maxHeight: "200px",
                        overflow: "auto",
                        margin: 0,
                        color: "#c00",
                      }}>
                        {job.error_message}
                      </pre>
                    )}
                    {job.metrics && (
                      <div style={{ fontSize: "0.8rem" }}>
                        {Object.entries(job.metrics).map(([k, v]) => (
                          <div key={k}>
                            <strong>{k}:</strong> {typeof v === "number" ? v.toFixed(4) : String(v)}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              ) : null,
            ])}
          </AdminTable>
        )}
      </AdminCard>
    </div>
  );
}
