"use client";

import { useState } from "react";
import { AdminCard } from "@/components/admin";
import { getMatchupAnalytics, type MatchupAnalytics } from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function MatchupPage() {
  const [sport, setSport] = useState("mlb");
  const [entityA, setEntityA] = useState("");
  const [entityB, setEntityB] = useState("");
  const [data, setData] = useState<MatchupAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    if (!entityA.trim() || !entityB.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getMatchupAnalytics(sport, entityA.trim(), entityB.trim());
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Matchup Explorer</h1>
        <p className={styles.pageSubtitle}>Compare two entities and view probability distributions</p>
      </header>

      <AdminCard title="Select Matchup">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Player A (Batter)</label>
            <input
              type="text"
              value={entityA}
              onChange={(e) => setEntityA(e.target.value)}
              placeholder="e.g. batter_123"
            />
          </div>
          <div className={styles.formGroup}>
            <label>Player B (Pitcher)</label>
            <input
              type="text"
              value={entityB}
              onChange={(e) => setEntityB(e.target.value)}
              placeholder="e.g. pitcher_456"
              onKeyDown={(e) => e.key === "Enter" && handleFetch()}
            />
          </div>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleFetch}
            disabled={loading || !entityA.trim() || !entityB.trim()}
          >
            {loading ? "Loading..." : "Analyze"}
          </button>
        </div>
      </AdminCard>

      {error && <div className={styles.error}>{error}</div>}

      {data && (
        <div className={styles.resultsSection}>
          <AdminCard
            title={`${data.entity_a} vs ${data.entity_b}`}
            subtitle="Probability Distribution"
          >
            {Object.keys(data.probabilities).length === 0 ? (
              <p className={styles.empty}>No probability data available</p>
            ) : (
              <div>
                {Object.entries(data.probabilities).map(([key, value]) => (
                  <div key={key} className={styles.probBar}>
                    <span className={styles.probLabel}>{formatMetricName(key)}</span>
                    <div className={styles.probTrack}>
                      <div
                        className={styles.probFill}
                        style={{ width: `${Math.min(value * 100, 100)}%` }}
                      />
                    </div>
                    <span className={styles.probValue}>{(value * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            )}
          </AdminCard>
        </div>
      )}
    </div>
  );
}

function formatMetricName(key: string): string {
  return key.replace(/_probability/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
