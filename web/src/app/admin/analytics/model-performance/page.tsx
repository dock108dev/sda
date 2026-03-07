"use client";

import { useState, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import { getModelPerformance, type ModelPerformance } from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function ModelPerformancePage() {
  const [sport, setSport] = useState<string>("");
  const [data, setData] = useState<ModelPerformance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLoad = useCallback(() => {
    setLoading(true);
    setError(null);
    getModelPerformance(sport || undefined)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [sport]);

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Model Performance</h1>
        <p className={styles.pageSubtitle}>
          Prediction accuracy, calibration metrics, and model bias tracking
        </p>
      </header>

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
            subtitle={`Based on ${data.total_predictions} predictions`}
          >
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.total_predictions}
                </div>
                <div className={styles.statLabel}>Total Predictions</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {(data.winner_accuracy * 100).toFixed(1)}%
                </div>
                <div className={styles.statLabel}>Winner Accuracy</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.brier_score.toFixed(3)}
                </div>
                <div className={styles.statLabel}>Brier Score</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.log_loss.toFixed(3)}
                </div>
                <div className={styles.statLabel}>Log Loss</div>
              </div>
            </div>
          </AdminCard>

          <AdminCard title="Score Accuracy">
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.average_score_error.toFixed(1)}
                </div>
                <div className={styles.statLabel}>Avg Score Error</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.mae_score.toFixed(1)}
                </div>
                <div className={styles.statLabel}>MAE (Score)</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.average_total_error.toFixed(1)}
                </div>
                <div className={styles.statLabel}>Avg Total Error</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.mae_total.toFixed(1)}
                </div>
                <div className={styles.statLabel}>MAE (Total)</div>
              </div>
            </div>
          </AdminCard>

          <AdminCard title="Model Bias">
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.prediction_bias.home_bias > 0 ? "+" : ""}
                  {(data.prediction_bias.home_bias * 100).toFixed(1)}%
                </div>
                <div className={styles.statLabel}>Home Win Bias</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.prediction_bias.total_bias > 0 ? "+" : ""}
                  {data.prediction_bias.total_bias.toFixed(1)} runs
                </div>
                <div className={styles.statLabel}>Total Bias</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>
                  {data.prediction_bias.home_score_bias > 0 ? "+" : ""}
                  {data.prediction_bias.home_score_bias.toFixed(1)} runs
                </div>
                <div className={styles.statLabel}>Home Score Bias</div>
              </div>
            </div>
          </AdminCard>

          {data.calibration_buckets.length > 0 && (
            <AdminCard title="Calibration Buckets">
              <AdminTable
                headers={["Probability Range", "Count", "Avg Predicted", "Avg Actual"]}
              >
                {data.calibration_buckets.map((b) => (
                  <tr key={b.bucket}>
                    <td>{b.bucket}</td>
                    <td>{b.count}</td>
                    <td>{(b.avg_predicted * 100).toFixed(1)}%</td>
                    <td>{(b.avg_actual * 100).toFixed(1)}%</td>
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
