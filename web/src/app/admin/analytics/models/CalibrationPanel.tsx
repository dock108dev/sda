"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  getCalibrationReport,
  listPredictionOutcomes,
  triggerRecordOutcomes,
  type CalibrationReport,
  type PredictionOutcome,
} from "@/lib/api/analytics";
import { CalibrationChart } from "../charts";
import styles from "../analytics.module.css";

export function CalibrationPanel({ sport }: { sport?: string }) {
  const [report, setReport] = useState<CalibrationReport | null>(null);
  const [outcomes, setOutcomes] = useState<PredictionOutcome[]>([]);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rep, oc] = await Promise.all([
        getCalibrationReport(sport),
        listPredictionOutcomes({ sport, limit: 200 }),
      ]);
      setReport(rep);
      setOutcomes(oc.outcomes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load calibration data");
    } finally {
      setLoading(false);
    }
  }, [sport]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void refresh();
    }, 0);
    return () => clearTimeout(timer);
  }, [refresh]);

  const handleRecordOutcomes = async () => {
    setRecording(true);
    setMessage(null);
    try {
      await triggerRecordOutcomes();
      setMessage("Outcome recording task dispatched. Refresh in a few seconds.");
      setTimeout(refresh, 5000);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setRecording(false);
    }
  };

  const resolved = outcomes.filter((o) => o.outcome_recorded_at !== null);
  const pending = outcomes.filter((o) => o.outcome_recorded_at === null);

  return (
    <>
      {error && <div className={styles.error}>{error}</div>}
      <AdminCard
        title="Prediction Calibration (Batch Sims)"
        subtitle="Tracks batch simulation predictions vs actual game outcomes"
      >
        <div className={styles.formRow} style={{ marginBottom: "1rem" }}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleRecordOutcomes}
            disabled={recording}
          >
            {recording ? "Recording..." : "Record Outcomes Now"}
          </button>
          <button className={styles.btn} onClick={refresh} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>

        {message && <div className={styles.success}>{message}</div>}

        {report && report.total_predictions > 0 && (
          <div className={styles.statsRow}>
            <div className={styles.statBox}>
              <div className={styles.statValue}>{report.total_predictions}</div>
              <div className={styles.statLabel}>Resolved Predictions</div>
            </div>
            <div className={styles.statBox}>
              <div className={styles.statValue}>
                {(report.accuracy * 100).toFixed(1)}%
              </div>
              <div className={styles.statLabel}>Winner Accuracy</div>
            </div>
            <div className={styles.statBox}>
              <div className={styles.statValue}>
                {report.brier_score.toFixed(4)}
              </div>
              <div className={styles.statLabel}>Brier Score</div>
            </div>
            <div className={styles.statBox}>
              <div className={styles.statValue}>
                {report.avg_home_score_error.toFixed(1)}
              </div>
              <div className={styles.statLabel}>Avg Home Score Err</div>
            </div>
            <div className={styles.statBox}>
              <div className={styles.statValue}>
                {report.home_bias > 0 ? "+" : ""}
                {(report.home_bias * 100).toFixed(1)}%
              </div>
              <div className={styles.statLabel}>Home Bias</div>
            </div>
          </div>
        )}

        {report && report.total_predictions === 0 && (
          <p style={{ color: "var(--text-muted)" }}>
            No resolved predictions yet. Run a batch simulation, then record outcomes after games finish.
          </p>
        )}
      </AdminCard>

      {/* Calibration curve from resolved predictions */}
      {resolved.length >= 5 && (
        <AdminCard title="Calibration Curve" subtitle="Predicted win probability vs actual win rate by bucket">
          <CalibrationChart
            data={(() => {
              const buckets = [
                { min: 0, max: 0.3, label: "0-30%" },
                { min: 0.3, max: 0.4, label: "30-40%" },
                { min: 0.4, max: 0.5, label: "40-50%" },
                { min: 0.5, max: 0.6, label: "50-60%" },
                { min: 0.6, max: 0.7, label: "60-70%" },
                { min: 0.7, max: 1.01, label: "70-100%" },
              ];
              return buckets.map((b) => {
                const inBucket = resolved.filter(
                  (o) => o.predicted_home_wp >= b.min && o.predicted_home_wp < b.max,
                );
                const avgPred = inBucket.length
                  ? inBucket.reduce((s, o) => s + o.predicted_home_wp, 0) / inBucket.length
                  : (b.min + b.max) / 2;
                const actualWin = inBucket.length
                  ? inBucket.filter((o) => o.home_win_actual).length / inBucket.length
                  : 0;
                return {
                  label: `${b.label} (${inBucket.length})`,
                  predicted: +(avgPred * 100).toFixed(1),
                  actual: +(actualWin * 100).toFixed(1),
                };
              }).filter((b) => {
                const n = parseInt(b.label.match(/\((\d+)\)/)?.[1] ?? "0");
                return n > 0;
              });
            })()}
          />
        </AdminCard>
      )}

      {/* Pending predictions */}
      {pending.length > 0 && (
        <AdminCard title="Pending Predictions" subtitle={`${pending.length} awaiting game outcomes`}>
          <AdminTable headers={["Game", "Matchup", "Home WP", "Mode", "Created"]}>
            {pending.slice(0, 50).map((o) => (
              <tr key={o.id}>
                <td style={{ fontSize: "0.85rem" }}>{o.game_date || `#${o.game_id}`}</td>
                <td>{o.away_team} @ {o.home_team}</td>
                <td>{(o.predicted_home_wp * 100).toFixed(1)}%</td>
                <td style={{ fontSize: "0.85rem" }}>{o.probability_mode}</td>
                <td style={{ fontSize: "0.85rem" }}>
                  {o.created_at ? new Date(o.created_at).toLocaleDateString() : "-"}
                </td>
              </tr>
            ))}
          </AdminTable>
        </AdminCard>
      )}

      {/* Resolved predictions */}
      {resolved.length > 0 && (
        <AdminCard title="Resolved Predictions" subtitle={`${resolved.length} with outcomes recorded`}>
          <div style={{ maxHeight: "400px", overflow: "auto" }}>
            <AdminTable headers={["Game", "Matchup", "Pred WP", "Actual", "Result", "Brier", "Score"]}>
              {resolved.map((o) => (
                <tr
                  key={o.id}
                  style={{ background: o.correct_winner ? undefined : "rgba(239, 68, 68, 0.08)" }}
                >
                  <td style={{ fontSize: "0.85rem" }}>{o.game_date || `#${o.game_id}`}</td>
                  <td>{o.away_team} @ {o.home_team}</td>
                  <td>{(o.predicted_home_wp * 100).toFixed(1)}%</td>
                  <td>{o.home_win_actual ? "Home" : "Away"}</td>
                  <td>
                    <span style={{
                      color: o.correct_winner ? "#22c55e" : "#ef4444",
                      fontWeight: "bold",
                      fontSize: "0.85rem",
                    }}>
                      {o.correct_winner ? "Correct" : "Wrong"}
                    </span>
                  </td>
                  <td style={{ fontSize: "0.85rem" }}>{o.brier_score?.toFixed(4) ?? "-"}</td>
                  <td style={{ fontSize: "0.85rem" }}>
                    {o.actual_home_score != null && o.actual_away_score != null
                      ? `${o.actual_home_score}-${o.actual_away_score}`
                      : "-"}
                  </td>
                </tr>
              ))}
            </AdminTable>
          </div>
        </AdminCard>
      )}
    </>
  );
}
