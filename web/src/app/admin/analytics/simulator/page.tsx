"use client";

import { useState } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  runSimulation,
  runLiveSimulation,
  type SimulationResult,
  type LiveSimulateResult,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

type Mode = "pregame" | "live";

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
      </div>

      {mode === "pregame" ? <PregameSimulator /> : <LiveSimulator />}
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
