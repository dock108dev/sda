"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  startBatchSimulation,
  listBatchSimJobs,
  type BatchSimJob,
  type BatchSimGameResult,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function BatchSimsPage() {
  const [sport] = useState("mlb");
  const [probabilityMode, setProbabilityMode] = useState("ml");
  const [iterations, setIterations] = useState(5000);
  const [rollingWindow, setRollingWindow] = useState(30);
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [jobs, setJobs] = useState<BatchSimJob[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [expandedJob, setExpandedJob] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await listBatchSimJobs(sport);
      setJobs(res.jobs);
      setJobsError(null);
    } catch {
      setJobsError("Failed to load batch sim jobs");
    }
  }, [sport]);

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

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await startBatchSimulation({
        sport,
        probability_mode: probabilityMode,
        iterations,
        rolling_window: rollingWindow,
        date_start: dateStart || undefined,
        date_end: dateEnd || undefined,
      });
      setMessage(`Batch job #${res.job.id} submitted`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  function statusBadge(status: string) {
    const colors: Record<string, { bg: string; text: string }> = {
      pending: { bg: "#fef3c7", text: "#92400e" },
      queued: { bg: "#dbeafe", text: "#1e40af" },
      running: { bg: "#dbeafe", text: "#1e40af" },
      completed: { bg: "#dcfce7", text: "#166534" },
      failed: { bg: "#fee2e2", text: "#991b1b" },
    };
    const c = colors[status] || { bg: "#f3f4f6", text: "#374151" };
    return (
      <span style={{ background: c.bg, color: c.text, padding: "2px 8px", borderRadius: "4px", fontSize: "0.8rem", fontWeight: 500 }}>
        {status}
      </span>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Batch Simulations</h1>
        <p className={styles.pageSubtitle}>
          Run simulations for upcoming games and track prediction outcomes
        </p>
      </header>

      <AdminCard title="Run New Batch">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} disabled>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Probability Mode</label>
            <select value={probabilityMode} onChange={(e) => setProbabilityMode(e.target.value)}>
              <option value="ml">ML Model</option>
              <option value="rule_based">Rule Based</option>
              <option value="ensemble">Ensemble</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Iterations</label>
            <input type="number" value={iterations} onChange={(e) => setIterations(Math.max(100, parseInt(e.target.value) || 100))} min={100} max={50000} />
          </div>
          <div className={styles.formGroup}>
            <label>Rolling Window: {rollingWindow}</label>
            <input type="range" min={5} max={80} step={5} value={rollingWindow} onChange={(e) => setRollingWindow(parseInt(e.target.value))} />
          </div>
        </div>
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Date Start (optional)</label>
            <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)} />
          </div>
          <div className={styles.formGroup}>
            <label>Date End (optional)</label>
            <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} />
          </div>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleSubmit}
            disabled={submitting}
            style={{ alignSelf: "flex-end" }}
          >
            {submitting ? "Submitting..." : "Run Batch Simulation"}
          </button>
        </div>
        {error && <div className={styles.error} style={{ marginTop: "0.5rem" }}>{error}</div>}
        {message && <div className={styles.success} style={{ marginTop: "0.5rem" }}>{message}</div>}
      </AdminCard>

      {/* Job History */}
      <AdminCard title="Job History" subtitle={`${jobs.length} batch simulation job(s)`}>
        {jobsError && <div className={styles.error} style={{ marginBottom: "0.5rem" }}>{jobsError}</div>}
        {jobs.length === 0 && !jobsError ? (
          <p style={{ color: "var(--text-muted)" }}>No batch simulation jobs yet.</p>
        ) : (
          <AdminTable headers={["ID", "Mode", "Iterations", "Window", "Date Range", "Status", "Games", "Created", ""]}>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>#{job.id}</td>
                <td>{job.probability_mode}</td>
                <td>{job.iterations.toLocaleString()}</td>
                <td>{job.rolling_window}</td>
                <td style={{ fontSize: "0.85rem" }}>
                  {job.date_start || "auto"} - {job.date_end || "auto"}
                </td>
                <td>{statusBadge(job.status)}</td>
                <td>{job.game_count ?? "-"}</td>
                <td style={{ fontSize: "0.85rem" }}>
                  {job.created_at ? new Date(job.created_at).toLocaleDateString() : "-"}
                </td>
                <td>
                  {job.results && job.results.length > 0 && (
                    <button
                      className={styles.btn}
                      onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
                      style={{ fontSize: "0.8rem", padding: "2px 8px" }}
                    >
                      {expandedJob === job.id ? "Hide" : "Results"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </AdminTable>
        )}

        {/* Expanded results */}
        {expandedJob && (() => {
          const job = jobs.find((j) => j.id === expandedJob);
          if (!job?.results) return null;
          return (
            <div style={{ marginTop: "1rem" }}>
              <h4 style={{ marginBottom: "0.5rem" }}>Results for Batch #{job.id}</h4>
              <AdminTable headers={["Matchup", "Home WP", "Away WP", "Avg Home", "Avg Away", "Source", "Profiles"]}>
                {job.results.map((g: BatchSimGameResult, i: number) => (
                  <tr key={i}>
                    <td>{g.away_team} @ {g.home_team}</td>
                    <td>{(g.home_win_probability * 100).toFixed(1)}%</td>
                    <td>{(g.away_win_probability * 100).toFixed(1)}%</td>
                    <td>{g.average_home_score.toFixed(1)}</td>
                    <td>{g.average_away_score.toFixed(1)}</td>
                    <td style={{ fontSize: "0.85rem" }}>{g.probability_source}</td>
                    <td>{g.has_profiles ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </AdminTable>
            </div>
          );
        })()}
      </AdminCard>
    </div>
  );
}
