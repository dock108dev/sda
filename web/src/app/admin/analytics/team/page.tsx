"use client";

import { useState } from "react";
import { AdminCard } from "@/components/admin";
import { getTeamAnalytics, type TeamAnalytics } from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function TeamAnalyticsPage() {
  const [sport, setSport] = useState("mlb");
  const [teamId, setTeamId] = useState("");
  const [data, setData] = useState<TeamAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    if (!teamId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getTeamAnalytics(sport, teamId.trim());
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
        <h1 className={styles.pageTitle}>Team Analytics</h1>
        <p className={styles.pageSubtitle}>View team-level performance metrics</p>
      </header>

      <AdminCard title="Select Team">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Team ID</label>
            <input
              type="text"
              value={teamId}
              onChange={(e) => setTeamId(e.target.value)}
              placeholder="e.g. NYY"
              onKeyDown={(e) => e.key === "Enter" && handleFetch()}
            />
          </div>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleFetch}
            disabled={loading || !teamId.trim()}
          >
            {loading ? "Loading..." : "Fetch"}
          </button>
        </div>
      </AdminCard>

      {error && <div className={styles.error}>{error}</div>}

      {data && (
        <div className={styles.resultsSection}>
          <AdminCard title={data.name || data.team_id} subtitle={`${data.sport.toUpperCase()} Team Profile`}>
            {Object.keys(data.metrics).length === 0 ? (
              <p className={styles.empty}>No metrics available yet</p>
            ) : (
              <div className={styles.metricsGrid}>
                {Object.entries(data.metrics).map(([key, value]) => (
                  <div key={key} className={styles.metricItem}>
                    <span className={styles.metricLabel}>{formatMetricName(key)}</span>
                    <span className={styles.metricValue}>{formatMetricValue(value)}</span>
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
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatMetricValue(value: number): string {
  if (value >= 10) return value.toFixed(1);
  return value.toFixed(4);
}
