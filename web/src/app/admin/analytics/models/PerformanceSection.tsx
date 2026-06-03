"use client";

import { useCallback, useState } from "react";

import { AdminCard } from "@/components/admin";
import { getCalibrationReport, type CalibrationReport } from "@/lib/api/analytics";

import styles from "../analytics.module.css";
import { CalibrationPanel } from "./CalibrationPanel";
import { DegradationAlertsPanel } from "./DegradationAlertsPanel";

/* ------------------------------------------------------------------ */
/*  Performance Section — calibration + degradation alerts            */
/* ------------------------------------------------------------------ */

export function PerformanceSection() {
  const [sport, setSport] = useState<string>("");
  const [data, setData] = useState<CalibrationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLoad = useCallback(() => {
    setLoading(true);
    setError(null);
    getCalibrationReport(sport || undefined)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [sport]);

  return (
    <>
      <div className={styles.formRow} style={{ marginBottom: "1rem" }}>
        <div className={styles.formGroup}>
          <label>Sport</label>
          <select value={sport} onChange={(e) => setSport(e.target.value)}>
            <option value="">All Sports</option>
            <option value="mlb">MLB</option>
          </select>
        </div>
        <button
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={handleLoad}
          disabled={loading}
        >
          {loading ? "Loading..." : "Load Metrics"}
        </button>
      </div>

      {loading && <div className={styles.loading}>Loading metrics...</div>}
      {error && <div className={styles.error}>{error}</div>}

      {data && !loading && (
        <div className={styles.resultsSection}>
          <AdminCard
            title="Overview"
            subtitle={`Based on ${data.total_predictions} resolved predictions`}
          >
            {data.total_predictions === 0 ? (
              <p style={{ color: "var(--text-muted)" }}>
                No resolved predictions yet. Run a batch simulation, then record outcomes after games finish.
              </p>
            ) : (
              <>
                <div className={styles.statsRow}>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.total_predictions}</div>
                    <div className={styles.statLabel}>Resolved</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{(data.accuracy * 100).toFixed(1)}%</div>
                    <div className={styles.statLabel}>Winner Accuracy</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.brier_score.toFixed(4)}</div>
                    <div className={styles.statLabel}>Brier Score</div>
                  </div>
                </div>

                {/* Model quality context */}
                <div style={{
                  marginTop: "0.5rem",
                  padding: "0.75rem 1rem",
                  background: "rgba(59, 130, 246, 0.05)",
                  border: "1px solid var(--border)",
                  borderRadius: "0.5rem",
                  fontSize: "0.8rem",
                  color: "var(--text-muted)",
                  lineHeight: 1.6,
                }}>
                  <strong>Baselines:</strong>
                  <ul style={{ margin: "0.25rem 0 0 1.25rem", padding: 0 }}>
                    <li>Pitch model (7-class): Random baseline: 14.3%, majority-class baseline: ~46%</li>
                    <li>Brier score: Perfect = 0.0, uninformed = 0.25</li>
                  </ul>
                </div>
                <div className={styles.statsRow}>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.avg_home_score_error.toFixed(1)}</div>
                    <div className={styles.statLabel}>Avg Home Score Error</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.avg_away_score_error.toFixed(1)}</div>
                    <div className={styles.statLabel}>Avg Away Score Error</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>
                      {data.home_bias > 0 ? "+" : ""}{(data.home_bias * 100).toFixed(1)}%
                    </div>
                    <div className={styles.statLabel}>Home Win Bias</div>
                  </div>
                </div>
              </>
            )}
          </AdminCard>
        </div>
      )}

      <DegradationAlertsPanel sport={sport || undefined} />
      <CalibrationPanel sport={sport || undefined} />
    </>
  );
}
