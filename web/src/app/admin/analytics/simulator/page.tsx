"use client";

import { useState } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import { runSimulation, type SimulationResult } from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function SimulatorPage() {
  const [sport, setSport] = useState("mlb");
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [iterations, setIterations] = useState(5000);
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
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Game Simulator</h1>
        <p className={styles.pageSubtitle}>
          Run Monte Carlo simulations to estimate game outcomes
        </p>
      </header>

      <AdminCard title="Simulation Setup">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Home Team</label>
            <input
              type="text"
              value={homeTeam}
              onChange={(e) => setHomeTeam(e.target.value)}
              placeholder="e.g. LAD"
            />
          </div>
          <div className={styles.formGroup}>
            <label>Away Team</label>
            <input
              type="text"
              value={awayTeam}
              onChange={(e) => setAwayTeam(e.target.value)}
              placeholder="e.g. TOR"
            />
          </div>
          <div className={styles.formGroup}>
            <label>Iterations</label>
            <input
              type="number"
              value={iterations}
              onChange={(e) => setIterations(Math.max(1, parseInt(e.target.value) || 1))}
              min={1}
              max={100000}
            />
          </div>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleSimulate}
            disabled={loading || !homeTeam.trim() || !awayTeam.trim()}
          >
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
                <div className={styles.statValue}>
                  {(result.home_win_probability * 100).toFixed(1)}%
                </div>
                <div className={styles.statLabel}>{result.home_team} (Home)</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {(result.away_win_probability * 100).toFixed(1)}%
                </div>
                <div className={styles.statLabel}>{result.away_team} (Away)</div>
              </div>
            </div>

            {/* Win probability bar */}
            <div className={styles.probBar}>
              <span className={styles.probLabel}>{result.home_team}</span>
              <div className={styles.probTrack}>
                <div
                  className={styles.probFill}
                  style={{ width: `${result.home_win_probability * 100}%` }}
                />
              </div>
              <span className={styles.probLabel} style={{ textAlign: "right" }}>
                {result.away_team}
              </span>
            </div>
          </AdminCard>

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
    </div>
  );
}
