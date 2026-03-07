"use client";

import { useState } from "react";
import { AdminCard } from "@/components/admin";
import { getPitchModel, getPitchSim, getRunExpectancy } from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function BaseballModelsPage() {
  // Pitch model state
  const [pitchProbs, setPitchProbs] = useState<Record<string, number> | null>(null);
  const [pitchK, setPitchK] = useState(0.22);
  const [pitchContact, setPitchContact] = useState(0.8);
  const [pitchBalls, setPitchBalls] = useState(0);
  const [pitchStrikes, setPitchStrikes] = useState(0);

  // Pitch sim state
  const [simResult, setSimResult] = useState<{
    result: string;
    pitches: number;
    final_count: string;
    batted_ball_result?: string;
  } | null>(null);

  // Run expectancy state
  const [reResult, setReResult] = useState<number | null>(null);
  const [reBase, setReBase] = useState(0);
  const [reOuts, setReOuts] = useState(0);

  const [loading, setLoading] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handlePitchModel() {
    setLoading("pitch");
    setError(null);
    try {
      const res = await getPitchModel({
        pitcher_k_rate: pitchK,
        batter_contact_rate: pitchContact,
        count_balls: pitchBalls,
        count_strikes: pitchStrikes,
      });
      setPitchProbs(res.pitch_probabilities);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading("");
    }
  }

  async function handlePitchSim() {
    setLoading("sim");
    setError(null);
    try {
      const res = await getPitchSim({
        pitcher_k_rate: pitchK,
        batter_contact_rate: pitchContact,
      });
      setSimResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading("");
    }
  }

  async function handleRunExpectancy() {
    setLoading("re");
    setError(null);
    try {
      const res = await getRunExpectancy({
        base_state: reBase,
        outs: reOuts,
      });
      setReResult(res.expected_runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading("");
    }
  }

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>MLB Advanced Models</h1>
        <p className={styles.pageSubtitle}>
          Pitch outcome, batted ball, and run expectancy models
        </p>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      {/* Pitch Outcome Model */}
      <AdminCard title="Pitch Outcome Model" subtitle="Predict individual pitch results">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Pitcher K Rate</label>
            <input type="number" step="0.01" value={pitchK} onChange={(e) => setPitchK(+e.target.value)} />
          </div>
          <div className={styles.formGroup}>
            <label>Batter Contact Rate</label>
            <input type="number" step="0.01" value={pitchContact} onChange={(e) => setPitchContact(+e.target.value)} />
          </div>
          <div className={styles.formGroup}>
            <label>Balls</label>
            <select value={pitchBalls} onChange={(e) => setPitchBalls(+e.target.value)}>
              {[0, 1, 2, 3].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Strikes</label>
            <select value={pitchStrikes} onChange={(e) => setPitchStrikes(+e.target.value)}>
              {[0, 1, 2].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handlePitchModel} disabled={loading === "pitch"}>
            {loading === "pitch" ? "..." : "Get Probabilities"}
          </button>
        </div>
        {pitchProbs && (
          <div className={styles.metricsGrid} style={{ marginTop: "1rem" }}>
            {Object.entries(pitchProbs).map(([k, v]) => (
              <div key={k} className={styles.metricItem}>
                <span className={styles.metricLabel}>{k}</span>
                <span className={styles.metricValue}>{(v * 100).toFixed(1)}%</span>
              </div>
            ))}
          </div>
        )}
      </AdminCard>

      {/* Pitch Simulation */}
      <AdminCard title="Pitch-Level PA Simulation" subtitle="Simulate a plate appearance pitch-by-pitch">
        <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handlePitchSim} disabled={loading === "sim"}>
          {loading === "sim" ? "Simulating..." : "Simulate PA"}
        </button>
        {simResult && (
          <div className={styles.statsRow} style={{ marginTop: "1rem" }}>
            <div className={styles.statBox}>
              <div className={styles.statValue}>{simResult.result}</div>
              <div className={styles.statLabel}>Result</div>
            </div>
            <div className={styles.statBox}>
              <div className={styles.statValue}>{simResult.pitches}</div>
              <div className={styles.statLabel}>Pitches</div>
            </div>
            <div className={styles.statBox}>
              <div className={styles.statValue}>{simResult.final_count}</div>
              <div className={styles.statLabel}>Final Count</div>
            </div>
          </div>
        )}
      </AdminCard>

      {/* Run Expectancy */}
      <AdminCard title="Run Expectancy Model" subtitle="Expected runs by game state">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Base State (0-7)</label>
            <select value={reBase} onChange={(e) => setReBase(+e.target.value)}>
              {[
                { v: 0, l: "Empty" },
                { v: 1, l: "1B" },
                { v: 2, l: "2B" },
                { v: 3, l: "1B+2B" },
                { v: 4, l: "3B" },
                { v: 5, l: "1B+3B" },
                { v: 6, l: "2B+3B" },
                { v: 7, l: "Loaded" },
              ].map((o) => (
                <option key={o.v} value={o.v}>{o.l}</option>
              ))}
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Outs</label>
            <select value={reOuts} onChange={(e) => setReOuts(+e.target.value)}>
              {[0, 1, 2].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleRunExpectancy} disabled={loading === "re"}>
            {loading === "re" ? "..." : "Calculate"}
          </button>
        </div>
        {reResult != null && (
          <div className={styles.statsRow} style={{ marginTop: "1rem" }}>
            <div className={styles.statBox}>
              <div className={styles.statValue}>{reResult.toFixed(3)}</div>
              <div className={styles.statLabel}>Expected Runs</div>
            </div>
          </div>
        )}
      </AdminCard>
    </div>
  );
}
