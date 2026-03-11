"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard } from "@/components/admin";
import {
  listDegradationAlerts,
  triggerDegradationCheck,
  acknowledgeDegradationAlert,
  type DegradationAlert,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

const SEVERITY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  critical: { bg: "#fee2e2", text: "#991b1b", border: "#ef4444" },
  warning: { bg: "#fef3c7", text: "#92400e", border: "#f59e0b" },
  info: { bg: "#dbeafe", text: "#1e40af", border: "#3b82f6" },
};

export function DegradationAlertsPanel({ sport }: { sport?: string }) {
  const [alerts, setAlerts] = useState<DegradationAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listDegradationAlerts({ sport, limit: 20 });
      setAlerts(res.alerts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load degradation alerts");
    } finally {
      setLoading(false);
    }
  }, [sport]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCheck = async () => {
    setChecking(true);
    setMessage(null);
    try {
      await triggerDegradationCheck(sport || "mlb");
      setMessage("Degradation check dispatched. Refresh in a few seconds.");
      setTimeout(refresh, 5000);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setChecking(false);
    }
  };

  const handleAcknowledge = async (id: number) => {
    try {
      await acknowledgeDegradationAlert(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to acknowledge alert");
    }
  };

  const unacknowledged = alerts.filter((a) => !a.acknowledged);
  const hasActiveAlerts = unacknowledged.length > 0;

  return (
    <>
      {error && <div className={styles.error}>{error}</div>}
      <AdminCard
        title={hasActiveAlerts ? "Model Degradation Alerts" : "Model Health"}
        subtitle={hasActiveAlerts
          ? `${unacknowledged.length} active alert${unacknowledged.length > 1 ? "s" : ""}`
          : "No active degradation alerts"
        }
      >
        <div className={styles.formRow} style={{ marginBottom: "1rem" }}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleCheck}
            disabled={checking}
          >
            {checking ? "Checking..." : "Run Degradation Check"}
          </button>
          <button className={styles.btn} onClick={refresh} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>

        {message && <div className={styles.success}>{message}</div>}

        {!hasActiveAlerts && alerts.length === 0 && (
          <p style={{ color: "var(--text-muted)" }}>
            No degradation alerts. Run a check after recording enough prediction outcomes.
          </p>
        )}

        {!hasActiveAlerts && alerts.length > 0 && (
          <p style={{ color: "#22c55e", fontWeight: 500 }}>
            Model is healthy. All previous alerts have been acknowledged.
          </p>
        )}

        {alerts.map((alert) => {
          const colors = SEVERITY_COLORS[alert.severity] || SEVERITY_COLORS.info;
          return (
            <div
              key={alert.id}
              style={{
                background: colors.bg,
                border: `1px solid ${colors.border}`,
                borderRadius: "8px",
                padding: "1rem",
                marginBottom: "0.75rem",
                opacity: alert.acknowledged ? 0.6 : 1,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                <div>
                  <span style={{
                    color: colors.text,
                    fontWeight: 700,
                    fontSize: "0.9rem",
                    textTransform: "uppercase",
                  }}>
                    {alert.severity}
                  </span>
                  <span style={{ color: colors.text, fontSize: "0.85rem", marginLeft: "0.75rem" }}>
                    {alert.sport.toUpperCase()} — {alert.alert_type.replace(/_/g, " ")}
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                    {alert.created_at ? new Date(alert.created_at).toLocaleString() : ""}
                  </span>
                  {!alert.acknowledged && (
                    <button
                      className={styles.btn}
                      onClick={() => handleAcknowledge(alert.id)}
                      style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                    >
                      Acknowledge
                    </button>
                  )}
                  {alert.acknowledged && (
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Acknowledged</span>
                  )}
                </div>
              </div>

              <p style={{ color: colors.text, fontSize: "0.85rem", margin: "0 0 0.5rem" }}>
                {alert.message}
              </p>

              <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.8rem", color: colors.text }}>
                <span>Baseline Brier: <strong>{alert.baseline_brier.toFixed(4)}</strong></span>
                <span>Recent Brier: <strong>{alert.recent_brier.toFixed(4)}</strong></span>
                <span>Delta: <strong>+{alert.delta_brier.toFixed(4)}</strong></span>
                <span>Accuracy: <strong>{(alert.baseline_accuracy * 100).toFixed(1)}%</strong> → <strong>{(alert.recent_accuracy * 100).toFixed(1)}%</strong></span>
              </div>
            </div>
          );
        })}
      </AdminCard>
    </>
  );
}
