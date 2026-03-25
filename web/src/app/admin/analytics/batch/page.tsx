"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import Link from "next/link";
import {
  startBatchSimulation,
  listBatchSimJobs,
  getBatchSimJob,
  listPredictionOutcomes,
  deleteBatchSimJob,
  type BatchSimJob,
  type BatchSimGameResult,
  type PredictionOutcome,
} from "@/lib/api/analytics";
import { SportSelector } from "@/components/admin/SportSelector";
import { SPORT_CONFIGS, type AnalyticsSport } from "@/lib/constants/analytics";
import { ROUTES } from "@/lib/constants/routes";
import styles from "../analytics.module.css";

export default function BatchSimsPage() {
  const [sport, setSport] = useState<AnalyticsSport>("MLB");
  const sportCode = sport.toLowerCase();
  const sportConfig = SPORT_CONFIGS[sport] || SPORT_CONFIGS.MLB;
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
  const [accuracyData, setAccuracyData] = useState<Record<number, { outcomes: PredictionOutcome[]; loading: boolean }>>({});
  const [selectedJobs, setSelectedJobs] = useState<Set<number>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  async function expandJob(jobId: number) {
    if (expandedJob === jobId) {
      setExpandedJob(null);
      return;
    }
    setExpandedJob(jobId);
    // Fetch detail endpoint for batch_summary/warnings (only computed there)
    const job = jobs.find((j) => j.id === jobId);
    if (job && job.status === "completed" && !job.batch_summary) {
      try {
        const detail = await getBatchSimJob(jobId);
        setJobs((prev) => prev.map((j) =>
          j.id === jobId
            ? { ...j, batch_summary: detail.batch_summary, warnings: detail.warnings }
            : j
        ));
      } catch {
        // Detail fetch failed — expand still works, just no diagnostics
      }
    }
  }

  async function loadAccuracy(jobId: number) {
    setAccuracyData((prev) => ({ ...prev, [jobId]: { outcomes: [], loading: true } }));
    try {
      const res = await listPredictionOutcomes({ batch_sim_job_id: jobId, resolved: true });
      setAccuracyData((prev) => ({ ...prev, [jobId]: { outcomes: res.outcomes, loading: false } }));
    } catch {
      setAccuracyData((prev) => ({ ...prev, [jobId]: { outcomes: [], loading: false } }));
    }
  }

  function toggleSelectJob(id: number) {
    setSelectedJobs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleBulkDelete() {
    const ids = Array.from(selectedJobs);
    if (ids.length === 0) return;
    if (!window.confirm(`Delete ${ids.length} batch sim job(s)? This cannot be undone.`)) return;
    setBulkDeleting(true);
    try {
      for (const id of ids) {
        await deleteBatchSimJob(id);
      }
      setSelectedJobs(new Set());
      setExpandedJob(null);
      await refresh();
    } catch (err) {
      setJobsError(err instanceof Error ? err.message : String(err));
    } finally {
      setBulkDeleting(false);
    }
  }

  const refresh = useCallback(async () => {
    try {
      const res = await listBatchSimJobs(sportCode);
      setJobs(res.jobs);
      setJobsError(null);
    } catch {
      setJobsError("Failed to load batch sim jobs");
    }
  }, [sportCode]);

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
        sport: sportCode,
        probability_mode: sportConfig.defaultProbMode,
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

      <SportSelector value={sport} onChange={setSport} />

      <AdminCard title="Run New Batch" subtitle="Uses the active ML model — falls back to rule-based if none trained">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Iterations</label>
            <input type="number" value={iterations} onChange={(e) => setIterations(Math.max(100, parseInt(e.target.value) || 100))} min={100} max={50000} />
          </div>
          <div className={styles.formGroup}>
            <label>Rolling Window: {rollingWindow} games</label>
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

        {jobs.length > 0 && (
          <div className={styles.formRow} style={{ marginBottom: "0.5rem" }}>
            <button
              className={styles.btn}
              style={{ fontSize: "0.8rem" }}
              onClick={() => setSelectedJobs(
                selectedJobs.size === jobs.length ? new Set() : new Set(jobs.map((j) => j.id))
              )}
            >
              {selectedJobs.size === jobs.length ? "Deselect All" : "Select All"}
            </button>
            {selectedJobs.size > 0 && (
              <button
                className={styles.btn}
                onClick={handleBulkDelete}
                disabled={bulkDeleting}
                style={{ fontSize: "0.8rem", background: "#ef4444", color: "#fff", border: "none", borderRadius: "4px" }}
              >
                {bulkDeleting ? "Deleting..." : `Delete ${selectedJobs.size} Selected`}
              </button>
            )}
          </div>
        )}

        {jobs.length === 0 && !jobsError ? (
          <p style={{ color: "var(--text-muted)" }}>No batch simulation jobs yet.</p>
        ) : (
          <AdminTable headers={["", "ID", "Iterations", "Window", "Date Range", "Status", "Games", "Created", ""]}>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedJobs.has(job.id)}
                    onChange={() => toggleSelectJob(job.id)}
                  />
                </td>
                <td>#{job.id}</td>
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
                  <div style={{ display: "flex", gap: "4px" }}>
                    {job.results && job.results.length > 0 && (
                      <button
                        className={styles.btn}
                        onClick={() => expandJob(job.id)}
                        style={{ fontSize: "0.8rem", padding: "2px 8px" }}
                      >
                        {expandedJob === job.id ? "Hide" : "Results"}
                      </button>
                    )}
                    {job.status === "completed" && !accuracyData[job.id] && (
                      <button
                        className={styles.btn}
                        onClick={() => loadAccuracy(job.id)}
                        style={{ fontSize: "0.8rem", padding: "2px 8px" }}
                      >
                        Load Accuracy
                      </button>
                    )}
                  </div>
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

              {/* Results Summary */}
              {(() => {
                const results = job.results!;
                const totalGames = results.length;
                const successResults = results.filter((g) => !g.error && g.home_win_probability != null);
                const errorCount = results.filter((g) => g.error).length;
                const avgHomeWP = successResults.length > 0
                  ? successResults.reduce((s, g) => s + (g.home_win_probability ?? 0), 0) / successResults.length
                  : 0;
                const dist = { "50-55": 0, "55-60": 0, "60-70": 0, "70+": 0 };
                successResults.forEach((g) => {
                  const wp = Math.max(g.home_win_probability ?? 0, g.away_win_probability ?? 0) * 100;
                  if (wp >= 70) dist["70+"]++;
                  else if (wp >= 60) dist["60-70"]++;
                  else if (wp >= 55) dist["55-60"]++;
                  else dist["50-55"]++;
                });
                return (
                  <div className={styles.statsRow} style={{ marginBottom: "1rem" }}>
                    <div className={styles.statBox}>
                      <div className={styles.statValue}>{totalGames}</div>
                      <div className={styles.statLabel}>Games</div>
                    </div>
                    {successResults.length > 0 ? (
                      <>
                        <div className={styles.statBox}>
                          <div className={styles.statValue}>{(avgHomeWP * 100).toFixed(1)}%</div>
                          <div className={styles.statLabel}>Avg Home WP</div>
                        </div>
                        <div className={styles.statBox}>
                          <div className={styles.statValue}>{dist["50-55"]}/{dist["55-60"]}/{dist["60-70"]}/{dist["70+"]}</div>
                          <div className={styles.statLabel}>50-55/55-60/60-70/70+%</div>
                        </div>
                      </>
                    ) : null}
                    {errorCount > 0 && (
                      <div className={styles.statBox}>
                        <div className={styles.statValue} style={{ color: "#dc2626" }}>{errorCount}</div>
                        <div className={styles.statLabel}>Errors</div>
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Sanity Warnings */}
              {job.warnings && job.warnings.length > 0 && (
                <div style={{ marginBottom: "1rem" }}>
                  {job.warnings.map((w, i) => (
                    <div key={i} style={{
                      padding: "0.5rem 0.75rem",
                      marginBottom: "0.25rem",
                      background: "#fef3c7",
                      border: "1px solid #f59e0b",
                      borderRadius: "4px",
                      color: "#92400e",
                      fontSize: "0.85rem",
                    }}>
                      {w}
                    </div>
                  ))}
                </div>
              )}

              {/* Simulation Sanity Panel */}
              {(() => {
                // Use first game's event_summary or batch_summary
                const bs = job.batch_summary;
                const firstEvent = job.results?.find((g) => g.event_summary)?.event_summary;
                if (!bs && !firstEvent) return null;

                return (
                  <div style={{
                    marginBottom: "1rem",
                    padding: "0.75rem",
                    background: "#f8fafc",
                    borderRadius: "6px",
                    border: "1px solid #e2e8f0",
                  }}>
                    <h5 style={{ marginBottom: "0.5rem", fontSize: "0.9rem" }}>Simulation Sanity</h5>
                    <div className={styles.statsRow}>
                      {bs && (
                        <>
                          <div className={styles.statBox}>
                            <div className={styles.statValue}>{bs.avg_runs_per_team}</div>
                            <div className={styles.statLabel}>Avg Runs/Team</div>
                          </div>
                          <div className={styles.statBox}>
                            <div className={styles.statValue}>{bs.avg_total_per_game}</div>
                            <div className={styles.statLabel}>Avg Total/Game</div>
                          </div>
                          {bs.avg_pa_per_team != null && (
                            <div className={styles.statBox}>
                              <div className={styles.statValue}>{bs.avg_pa_per_team}</div>
                              <div className={styles.statLabel}>Avg PA/Team</div>
                            </div>
                          )}
                          <div className={styles.statBox}>
                            <div className={styles.statValue}>{(bs.home_win_rate * 100).toFixed(1)}%</div>
                            <div className={styles.statLabel}>Home Win Rate</div>
                          </div>
                        </>
                      )}
                    </div>
                    {firstEvent && (
                      <div style={{ marginTop: "0.5rem" }}>
                        <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", fontSize: "0.8rem" }}>
                          <div>
                            <strong>PA Mix (Home):</strong>{" "}
                            K {(firstEvent.home.pa_rates.k_pct * 100).toFixed(1)}%{" / "}
                            BB {(firstEvent.home.pa_rates.bb_pct * 100).toFixed(1)}%{" / "}
                            HR {(firstEvent.home.pa_rates.hr_pct * 100).toFixed(1)}%{" / "}
                            Hit {((firstEvent.home.pa_rates.single_pct + firstEvent.home.pa_rates.double_pct + firstEvent.home.pa_rates.triple_pct + firstEvent.home.pa_rates.hr_pct) * 100).toFixed(1)}%
                          </div>
                          <div>
                            <strong>PA Mix (Away):</strong>{" "}
                            K {(firstEvent.away.pa_rates.k_pct * 100).toFixed(1)}%{" / "}
                            BB {(firstEvent.away.pa_rates.bb_pct * 100).toFixed(1)}%{" / "}
                            HR {(firstEvent.away.pa_rates.hr_pct * 100).toFixed(1)}%{" / "}
                            Hit {((firstEvent.away.pa_rates.single_pct + firstEvent.away.pa_rates.double_pct + firstEvent.away.pa_rates.triple_pct + firstEvent.away.pa_rates.hr_pct) * 100).toFixed(1)}%
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", fontSize: "0.8rem", marginTop: "0.25rem" }}>
                          <div>
                            <strong>Game Shape:</strong>{" "}
                            Extra inn. {(firstEvent.game.extra_innings_pct * 100).toFixed(1)}%{" / "}
                            Shutout {(firstEvent.game.shutout_pct * 100).toFixed(1)}%{" / "}
                            1-run {(firstEvent.game.one_run_game_pct * 100).toFixed(1)}%
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Accuracy data */}
              {accuracyData[job.id] && (() => {
                const ad = accuracyData[job.id];
                if (ad.loading) return <p style={{ color: "var(--text-muted)" }}>Loading accuracy...</p>;
                if (ad.outcomes.length === 0) return <p style={{ color: "var(--text-muted)" }}>No resolved outcomes yet.</p>;
                const total = ad.outcomes.length;
                const correct = ad.outcomes.filter((o) => o.correct_winner).length;
                const acc = correct / total;
                const brierOutcomes = ad.outcomes.filter((o) => o.brier_score != null);
                const avgBrier = brierOutcomes.length > 0
                  ? brierOutcomes.reduce((s, o) => s + o.brier_score!, 0) / brierOutcomes.length
                  : null;
                return (
                  <div style={{ marginBottom: "1rem", padding: "0.75rem", background: "#fafbfc", borderRadius: "6px" }}>
                    <div className={styles.statsRow}>
                      <div className={styles.statBox}>
                        <div className={styles.statValue}>{correct}/{total}</div>
                        <div className={styles.statLabel}>Correct</div>
                      </div>
                      <div className={styles.statBox}>
                        <div className={styles.statValue}>{(acc * 100).toFixed(1)}%</div>
                        <div className={styles.statLabel}>Accuracy</div>
                      </div>
                      <div className={styles.statBox}>
                        <div className={styles.statValue}>{avgBrier != null ? avgBrier.toFixed(4) : "-"}</div>
                        <div className={styles.statLabel}>Brier Score</div>
                      </div>
                    </div>
                    <Link
                      href={`${ROUTES.ANALYTICS_MODELS}?tab=performance`}
                      style={{ fontSize: "0.8rem", color: "#3b82f6" }}
                    >
                      View in Calibration &rarr;
                    </Link>
                  </div>
                );
              })()}

              <AdminTable headers={["Matchup", "Home WP", "Away WP", "Avg Home", "Avg Away", "Source", "Status"]}>
                {job.results.map((g: BatchSimGameResult, i: number) => (
                  <tr key={i} style={g.error ? { opacity: 0.6 } : {}}>
                    <td>{g.away_team} @ {g.home_team}</td>
                    {g.error ? (
                      <td colSpan={5} style={{ color: "#dc2626", fontSize: "0.8rem" }} title={g.error}>
                        {g.error.length > 80 ? g.error.slice(0, 80) + "..." : g.error}
                      </td>
                    ) : (
                      <>
                        <td>{g.home_win_probability != null ? (g.home_win_probability * 100).toFixed(1) + "%" : "-"}</td>
                        <td>{g.away_win_probability != null ? (g.away_win_probability * 100).toFixed(1) + "%" : "-"}</td>
                        <td>{g.average_home_score != null ? g.average_home_score.toFixed(1) : "-"}</td>
                        <td>{g.average_away_score != null ? g.average_away_score.toFixed(1) : "-"}</td>
                        <td style={{ fontSize: "0.85rem" }}>{g.probability_source ?? "-"}</td>
                        <td>{g.has_profiles ? "Yes" : "No"}</td>
                      </>
                    )}
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
