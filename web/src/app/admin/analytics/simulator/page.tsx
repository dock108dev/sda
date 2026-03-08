"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  runSimulation,
  runLiveSimulation,
  startBatchSimulation,
  listBatchSimJobs,
  type SimulationResult,
  type LiveSimulateResult,
  type BatchSimJob,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

type Mode = "pregame" | "live" | "batch";

export default function SimulatorPage() {
  const [mode, setMode] = useState<Mode>("pregame");

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Game Simulator</h1>
        <p className={styles.pageSubtitle}>
          Run Monte Carlo simulations for pregame or live game states
        </p>
      </header>

      <div className={styles.formRow} style={{ marginBottom: "1rem" }}>
        <button
          className={`${styles.btn} ${mode === "pregame" ? styles.btnPrimary : ""}`}
          onClick={() => setMode("pregame")}
        >
          Pregame
        </button>
        <button
          className={`${styles.btn} ${mode === "live" ? styles.btnPrimary : ""}`}
          onClick={() => setMode("live")}
        >
          Live Game
        </button>
        <button
          className={`${styles.btn} ${mode === "batch" ? styles.btnPrimary : ""}`}
          onClick={() => setMode("batch")}
        >
          Batch Upcoming
        </button>
      </div>

      {mode === "pregame" ? <PregameSimulator /> : mode === "live" ? <LiveSimulator /> : <BatchSimulator />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Pregame Simulator                                                   */
/* ------------------------------------------------------------------ */

function PregameSimulator() {
  const [sport, setSport] = useState("mlb");
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [iterations, setIterations] = useState(5000);
  const [probabilityMode, setProbabilityMode] = useState<"rule_based" | "ml">("rule_based");
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSimulate() {
    if (!homeTeam.trim() || !awayTeam.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await runSimulation({
        sport,
        home_team: homeTeam.trim(),
        away_team: awayTeam.trim(),
        iterations,
        probability_mode: probabilityMode,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <AdminCard title="Pregame Setup">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Home Team</label>
            <input type="text" value={homeTeam} onChange={(e) => setHomeTeam(e.target.value)} placeholder="e.g. LAD" />
          </div>
          <div className={styles.formGroup}>
            <label>Away Team</label>
            <input type="text" value={awayTeam} onChange={(e) => setAwayTeam(e.target.value)} placeholder="e.g. TOR" />
          </div>
          <div className={styles.formGroup}>
            <label>Iterations</label>
            <input type="number" value={iterations} onChange={(e) => setIterations(Math.max(1, parseInt(e.target.value) || 1))} min={1} max={100000} />
          </div>
          <div className={styles.formGroup}>
            <label>Probability Mode</label>
            <select value={probabilityMode} onChange={(e) => setProbabilityMode(e.target.value as "rule_based" | "ml")}>
              <option value="rule_based">Rule Based</option>
              <option value="ml">ML Model</option>
            </select>
          </div>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleSimulate} disabled={loading || !homeTeam.trim() || !awayTeam.trim()}>
            {loading ? "Simulating..." : "Run Simulation"}
          </button>
        </div>
      </AdminCard>

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <div className={styles.resultsSection}>
          <AdminCard title="Win Probability">
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.home_win_probability * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>{result.home_team} (Home)</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.away_win_probability * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>{result.away_team} (Away)</div>
              </div>
            </div>
            <div className={styles.probBar}>
              <span className={styles.probLabel}>{result.home_team}</span>
              <div className={styles.probTrack}>
                <div className={styles.probFill} style={{ width: `${result.home_win_probability * 100}%` }} />
              </div>
              <span className={styles.probLabel} style={{ textAlign: "right" }}>{result.away_team}</span>
            </div>
          </AdminCard>

          {result.probability_source && (
            <AdminCard title="Simulation Mode" subtitle={`Probability source: ${result.probability_source}`}>
              <div className={styles.statsRow}>
                <div className={styles.statBox}>
                  <div className={styles.statValue} style={{ fontSize: "1rem" }}>{result.probability_source}</div>
                  <div className={styles.statLabel}>Source</div>
                </div>
              </div>
            </AdminCard>
          )}

          <AdminCard title="Average Score" subtitle={`Based on ${result.iterations.toLocaleString()} simulations`}>
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.average_home_score}</div>
                <div className={styles.statLabel}>{result.home_team} Avg</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.average_away_score}</div>
                <div className={styles.statLabel}>{result.away_team} Avg</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.average_total}</div>
                <div className={styles.statLabel}>Avg Total</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.median_total}</div>
                <div className={styles.statLabel}>Median Total</div>
              </div>
            </div>
          </AdminCard>

          {result.most_common_scores.length > 0 && (
            <AdminCard title="Most Common Scores">
              <AdminTable headers={["Score", "Probability"]}>
                {result.most_common_scores.map((entry) => (
                  <tr key={entry.score}>
                    <td>{entry.score}</td>
                    <td>{(entry.probability * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </AdminTable>
            </AdminCard>
          )}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Live Game Simulator                                                 */
/* ------------------------------------------------------------------ */

function LiveSimulator() {
  const [sport, setSport] = useState("mlb");
  const [inning, setInning] = useState(1);
  const [half, setHalf] = useState<"top" | "bottom">("top");
  const [outs, setOuts] = useState(0);
  const [first, setFirst] = useState(false);
  const [second, setSecond] = useState(false);
  const [third, setThird] = useState(false);
  const [homeScore, setHomeScore] = useState(0);
  const [awayScore, setAwayScore] = useState(0);
  const [iterations, setIterations] = useState(2000);
  const [result, setResult] = useState<LiveSimulateResult | null>(null);
  const [timeline, setTimeline] = useState<LiveSimulateResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSimulate() {
    setLoading(true);
    setError(null);
    try {
      const res = await runLiveSimulation({
        sport,
        inning,
        half,
        outs,
        bases: { first, second, third },
        score: { home: homeScore, away: awayScore },
        iterations,
      });
      setResult(res);
      setTimeline((prev) => [...prev, res]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <AdminCard title="Live Game State">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Inning</label>
            <input type="number" value={inning} onChange={(e) => setInning(Math.max(1, parseInt(e.target.value) || 1))} min={1} max={20} />
          </div>
          <div className={styles.formGroup}>
            <label>Half</label>
            <select value={half} onChange={(e) => setHalf(e.target.value as "top" | "bottom")}>
              <option value="top">Top</option>
              <option value="bottom">Bottom</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Outs</label>
            <select value={outs} onChange={(e) => setOuts(parseInt(e.target.value))}>
              <option value={0}>0</option>
              <option value={1}>1</option>
              <option value={2}>2</option>
            </select>
          </div>
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Home Score</label>
            <input type="number" value={homeScore} onChange={(e) => setHomeScore(Math.max(0, parseInt(e.target.value) || 0))} min={0} />
          </div>
          <div className={styles.formGroup}>
            <label>Away Score</label>
            <input type="number" value={awayScore} onChange={(e) => setAwayScore(Math.max(0, parseInt(e.target.value) || 0))} min={0} />
          </div>
          <div className={styles.formGroup}>
            <label>Iterations</label>
            <input type="number" value={iterations} onChange={(e) => setIterations(Math.max(1, parseInt(e.target.value) || 1))} min={1} max={50000} />
          </div>
        </div>

        <div className={styles.formRow}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input type="checkbox" checked={first} onChange={(e) => setFirst(e.target.checked)} />
            Runner on 1st
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input type="checkbox" checked={second} onChange={(e) => setSecond(e.target.checked)} />
            Runner on 2nd
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <input type="checkbox" checked={third} onChange={(e) => setThird(e.target.checked)} />
            Runner on 3rd
          </label>
        </div>

        <div className={styles.formRow} style={{ marginTop: "0.75rem" }}>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleSimulate} disabled={loading}>
            {loading ? "Simulating..." : "Run Live Simulation"}
          </button>
          {timeline.length > 0 && (
            <button className={styles.btn} onClick={() => setTimeline([])}>
              Clear Timeline
            </button>
          )}
        </div>
      </AdminCard>

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <div className={styles.resultsSection}>
          <AdminCard
            title="Win Probability"
            subtitle={`${half === "top" ? "Top" : "Bot"} ${inning} | ${outs} out${outs !== 1 ? "s" : ""} | Score: ${awayScore}-${homeScore}`}
          >
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.home_win_probability * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>Home Win</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.away_win_probability * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>Away Win</div>
              </div>
            </div>

            <div className={styles.probBar}>
              <span className={styles.probLabel}>Home</span>
              <div className={styles.probTrack}>
                <div className={styles.probFill} style={{ width: `${result.home_win_probability * 100}%` }} />
              </div>
              <span className={styles.probLabel} style={{ textAlign: "right" }}>Away</span>
            </div>
          </AdminCard>

          <AdminCard title="Expected Final Score">
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.expected_final_score.home}</div>
                <div className={styles.statLabel}>Home</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.expected_final_score.away}</div>
                <div className={styles.statLabel}>Away</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.iterations.toLocaleString()}</div>
                <div className={styles.statLabel}>Iterations</div>
              </div>
            </div>
          </AdminCard>
        </div>
      )}

      {timeline.length > 1 && (
        <AdminCard title="Win Probability Timeline">
          <AdminTable headers={["State", "Home WP", "Away WP", "Score"]}>
            {timeline.map((snap, i) => (
              <tr key={i}>
                <td>{snap.half === "top" ? "T" : "B"}{snap.inning}</td>
                <td>{(snap.home_win_probability * 100).toFixed(1)}%</td>
                <td>{(snap.away_win_probability * 100).toFixed(1)}%</td>
                <td>{snap.score.away}-{snap.score.home}</td>
              </tr>
            ))}
          </AdminTable>
        </AdminCard>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Batch Upcoming Games Simulator                                      */
/* ------------------------------------------------------------------ */

function BatchSimulator() {
  const [sport, setSport] = useState("mlb");
  const [probabilityMode, setProbabilityMode] = useState("ml");
  const [iterations, setIterations] = useState(5000);
  const [rollingWindow, setRollingWindow] = useState(30);
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [jobs, setJobs] = useState<BatchSimJob[]>([]);
  const [expandedJob, setExpandedJob] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await listBatchSimJobs(sport);
      setJobs(res.jobs);
    } catch {
      // ignore
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

  const handleSubmit = async () => {
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
      setMessage(`Batch sim job #${res.job.id} submitted`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <AdminCard title="Simulate Upcoming Games" subtitle="Run Monte Carlo sims on all scheduled/pregame games">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
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
            <input
              type="number"
              value={iterations}
              onChange={(e) => setIterations(Math.max(100, parseInt(e.target.value) || 100))}
              min={100}
              max={50000}
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
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Date Start (optional)</label>
            <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)} />
          </div>
          <div className={styles.formGroup}>
            <label>Date End (optional)</label>
            <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} />
          </div>
        </div>

        {error && <div className={styles.error}>{error}</div>}
        {message && <div className={styles.success}>{message}</div>}

        <button
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={handleSubmit}
          disabled={submitting}
          style={{ marginTop: "0.5rem" }}
        >
          {submitting ? "Submitting..." : "Simulate Upcoming Games"}
        </button>
      </AdminCard>

      {/* Job History */}
      {jobs.length > 0 && (
        <AdminCard title="Batch Simulation History">
          <AdminTable headers={["ID", "Mode", "Iterations", "Window", "Status", "Games", "Created", ""]}>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>#{job.id}</td>
                <td>{job.probability_mode}</td>
                <td>{job.iterations.toLocaleString()}</td>
                <td>{job.rolling_window}</td>
                <td><BatchStatusBadge status={job.status} /></td>
                <td>{job.game_count ?? "-"}</td>
                <td style={{ fontSize: "0.85rem" }}>
                  {job.created_at ? new Date(job.created_at).toLocaleString() : "-"}
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
                  {job.error_message && (
                    <span style={{ color: "#ef4444", fontSize: "0.8rem", marginLeft: "0.5rem" }} title={job.error_message}>
                      Error
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </AdminTable>

          {/* Expanded game results */}
          {expandedJob && (() => {
            const job = jobs.find((j) => j.id === expandedJob);
            if (!job?.results) return null;
            return (
              <div style={{ marginTop: "1rem" }}>
                <h4 style={{ marginBottom: "0.5rem" }}>
                  Results for Batch #{job.id}
                  <span style={{ fontWeight: "normal", fontSize: "0.85rem", marginLeft: "0.5rem" }}>
                    ({job.game_count} games)
                  </span>
                </h4>
                <div style={{ maxHeight: "500px", overflow: "auto" }}>
                  <AdminTable headers={["Date", "Matchup", "Home Win %", "Away Win %", "Avg Score", "Source", "Profiles"]}>
                    {job.results.map((g, i) => (
                      <tr key={i}>
                        <td style={{ fontSize: "0.85rem" }}>{g.game_date}</td>
                        <td style={{ fontWeight: 500 }}>
                          {g.away_team} @ {g.home_team}
                        </td>
                        <td style={{ color: g.home_win_probability > 0.5 ? "#22c55e" : undefined }}>
                          {(g.home_win_probability * 100).toFixed(1)}%
                        </td>
                        <td style={{ color: g.away_win_probability > 0.5 ? "#22c55e" : undefined }}>
                          {(g.away_win_probability * 100).toFixed(1)}%
                        </td>
                        <td style={{ fontSize: "0.85rem" }}>
                          {g.average_home_score.toFixed(1)} - {g.average_away_score.toFixed(1)}
                        </td>
                        <td style={{ fontSize: "0.8rem" }}>{g.probability_source}</td>
                        <td>{g.has_profiles ? "Yes" : "No"}</td>
                      </tr>
                    ))}
                  </AdminTable>
                </div>
              </div>
            );
          })()}
        </AdminCard>
      )}
    </>
  );
}

function BatchStatusBadge({ status }: { status: string }) {
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
