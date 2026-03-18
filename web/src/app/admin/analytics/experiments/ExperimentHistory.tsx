"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  listExperimentSuites,
  getExperimentSuite,
  promoteExperimentVariant,
  cancelExperimentSuite,
  deleteExperimentSuite,
  deleteExperimentVariant,
  type ExperimentSuite,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    pending: { bg: "#f0f0f0", fg: "#666" },
    queued: { bg: "#fff3cd", fg: "#856404" },
    running: { bg: "#cce5ff", fg: "#004085" },
    completed: { bg: "#d4edda", fg: "#155724" },
    failed: { bg: "#f8d7da", fg: "#721c24" },
    cancelled: { bg: "#f0f0f0", fg: "#666" },
  };
  const c = colors[status] || colors.pending;
  return (
    <span style={{ padding: "2px 8px", borderRadius: "4px", fontSize: "0.75rem", fontWeight: 600, background: c.bg, color: c.fg }}>
      {status}
    </span>
  );
}

export function ExperimentHistory({ refreshKey }: { refreshKey: number }) {
  const [suites, setSuites] = useState<ExperimentSuite[]>([]);
  const [expanded, setExpanded] = useState<ExperimentSuite | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState<number | null>(null);
  const [selectedSuites, setSelectedSuites] = useState<Set<number>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await listExperimentSuites("mlb");
      setSuites(res.suites);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  // Poll for active suites
  useEffect(() => {
    const active = suites.filter((s) => ["pending", "queued", "running"].includes(s.status));
    if (active.length === 0) return;
    const interval = setInterval(async () => {
      try {
        const res = await listExperimentSuites("mlb");
        setSuites(res.suites);
        if (expanded && active.some((s) => s.id === expanded.id)) {
          const detail = await getExperimentSuite(expanded.id);
          setExpanded(detail);
        }
      } catch { /* ignore poll errors */ }
    }, 5000);
    return () => clearInterval(interval);
  }, [suites, expanded]);

  async function handleExpand(suiteId: number) {
    if (expanded?.id === suiteId) { setExpanded(null); return; }
    try {
      const detail = await getExperimentSuite(suiteId);
      setExpanded(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCancel(suiteId: number) {
    if (!window.confirm("Cancel this experiment? Running variants will be stopped.")) return;
    try {
      await cancelExperimentSuite(suiteId);
      await refresh();
      if (expanded?.id === suiteId) {
        const detail = await getExperimentSuite(suiteId);
        setExpanded(detail);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDeleteSuite(suiteId: number) {
    if (!window.confirm("Delete this experiment and all its variants? This cannot be undone.")) return;
    try {
      await deleteExperimentSuite(suiteId);
      if (expanded?.id === suiteId) setExpanded(null);
      setSelectedSuites((prev) => { const n = new Set(prev); n.delete(suiteId); return n; });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleBulkDelete() {
    const ids = Array.from(selectedSuites);
    if (!window.confirm(`Delete ${ids.length} experiment(s) and all their variants? This cannot be undone.`)) return;
    setBulkDeleting(true);
    try {
      for (const id of ids) {
        await deleteExperimentSuite(id);
      }
      setSelectedSuites(new Set());
      setExpanded(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBulkDeleting(false);
    }
  }

  async function handlePromote(suiteId: number, variantId: number) {
    if (!window.confirm("Promote this variant's model to active? This will replace the currently active model.")) return;
    setPromoting(variantId);
    try {
      await promoteExperimentVariant(suiteId, variantId);
      const detail = await getExperimentSuite(suiteId);
      setExpanded(detail);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPromoting(null);
    }
  }

  async function handleDeleteVariant(suiteId: number, variantId: number) {
    if (!window.confirm("Delete this variant?")) return;
    try {
      await deleteExperimentVariant(suiteId, variantId);
      const detail = await getExperimentSuite(suiteId);
      setExpanded(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (loading) return <div className={styles.loading}>Loading experiments...</div>;

  return (
    <AdminCard title="Experiment History" subtitle={`${suites.length} experiment(s)`}>
      {error && <div className={styles.error} style={{ marginBottom: "0.5rem" }}>{error}</div>}

      {suites.length > 0 && (
        <div className={styles.formRow} style={{ marginBottom: "0.5rem" }}>
          <button
            className={styles.btn}
            style={{ fontSize: "0.8rem" }}
            onClick={() => setSelectedSuites(
              selectedSuites.size === suites.length ? new Set() : new Set(suites.map((s) => s.id))
            )}
          >
            {selectedSuites.size === suites.length ? "Deselect All" : "Select All"}
          </button>
          {selectedSuites.size > 0 && (
            <button
              className={styles.btn}
              onClick={handleBulkDelete}
              disabled={bulkDeleting}
              style={{ fontSize: "0.8rem", background: "#ef4444", color: "#fff", border: "none", borderRadius: "4px" }}
            >
              {bulkDeleting ? "Deleting..." : `Delete ${selectedSuites.size} Selected`}
            </button>
          )}
        </div>
      )}

      {suites.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No experiments yet. Configure and run one above.</p>
      ) : (
        <AdminTable headers={["", "ID", "Name", "Variants", "Progress", "Status", "Promoted", "Created", ""]}>
          {suites.map((s) => (
            <tr key={s.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedSuites.has(s.id)}
                  onChange={() => setSelectedSuites((prev) => {
                    const n = new Set(prev);
                    if (n.has(s.id)) n.delete(s.id); else n.add(s.id);
                    return n;
                  })}
                />
              </td>
              <td>#{s.id}</td>
              <td style={{ fontWeight: 500 }}>{s.name}</td>
              <td>{s.total_variants}</td>
              <td>
                {s.completed_variants}/{s.total_variants}
                {s.failed_variants > 0 && <span style={{ color: "#dc2626" }}> ({s.failed_variants} failed)</span>}
              </td>
              <td><StatusBadge status={s.status} /></td>
              <td style={{ fontSize: "0.8rem" }}>{s.promoted_model_id || "-"}</td>
              <td style={{ fontSize: "0.85rem" }}>{s.created_at ? new Date(s.created_at).toLocaleDateString() : "-"}</td>
              <td>
                <div style={{ display: "flex", gap: "4px" }}>
                  <button
                    className={styles.btn}
                    style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                    onClick={() => handleExpand(s.id)}
                  >
                    {expanded?.id === s.id ? "Hide" : "Details"}
                  </button>
                  {["pending", "queued", "running"].includes(s.status) && (
                    <button
                      className={styles.btn}
                      style={{ fontSize: "0.75rem", padding: "2px 8px", color: "#c00", border: "1px solid #c00", background: "#fff" }}
                      onClick={() => handleCancel(s.id)}
                    >
                      Stop
                    </button>
                  )}
                  <button
                    className={styles.btn}
                    style={{ fontSize: "0.75rem", padding: "2px 8px", background: "#ef4444", color: "#fff", border: "none", borderRadius: "4px" }}
                    onClick={() => handleDeleteSuite(s.id)}
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </AdminTable>
      )}

      {/* Expanded variant leaderboard */}
      {expanded?.variants && (
        <div style={{ marginTop: "1rem" }}>
          <h4 style={{ marginBottom: "0.25rem" }}>
            {expanded.name} — Variant Leaderboard
            {expanded.description && <span style={{ fontWeight: 400, color: "var(--text-muted)", marginLeft: "0.5rem" }}>{expanded.description}</span>}
          </h4>
          {expanded.tags && expanded.tags.length > 0 && (
            <div style={{ marginBottom: "0.5rem" }}>
              {expanded.tags.map((t) => (
                <span key={t} style={{ display: "inline-block", background: "#e5e7eb", borderRadius: "4px", padding: "1px 6px", fontSize: "0.7rem", marginRight: "0.25rem" }}>
                  {t}
                </span>
              ))}
            </div>
          )}

          <AdminTable headers={["Rank", "Algorithm", "Window", "Split", "Features", "Status", "Accuracy", "Brier", "Log Loss", "Model ID", ""]}>
            {[...expanded.variants]
              .sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
              .map((v) => (
                <tr key={v.id} style={v.model_id === expanded.promoted_model_id ? { background: "rgba(34, 197, 94, 0.08)" } : {}}>
                  <td style={{ fontWeight: 600 }}>{v.rank ?? "-"}</td>
                  <td style={{ fontSize: "0.85rem" }}>{v.algorithm}</td>
                  <td>{v.rolling_window}</td>
                  <td>{(v.test_split * 100).toFixed(0)}%</td>
                  <td style={{ fontSize: "0.8rem" }}>{v.feature_config_id ?? "default"}</td>
                  <td><StatusBadge status={v.status} /></td>
                  <td>{v.training_metrics?.accuracy != null ? (v.training_metrics.accuracy * 100).toFixed(1) + "%" : "-"}</td>
                  <td>{v.training_metrics?.brier_score != null ? v.training_metrics.brier_score.toFixed(4) : "-"}</td>
                  <td>{v.training_metrics?.log_loss != null ? v.training_metrics.log_loss.toFixed(4) : "-"}</td>
                  <td style={{ fontSize: "0.8rem", fontFamily: "monospace" }}>{v.model_id ?? "-"}</td>
                  <td>
                    <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                      {v.model_id && v.status === "completed" && v.model_id !== expanded.promoted_model_id && (
                        <button
                          className={`${styles.btn} ${styles.btnPrimary}`}
                          style={{ fontSize: "0.7rem", padding: "2px 6px" }}
                          onClick={() => handlePromote(expanded.id, v.id)}
                          disabled={promoting === v.id}
                        >
                          {promoting === v.id ? "..." : "Promote"}
                        </button>
                      )}
                      {v.model_id === expanded.promoted_model_id && (
                        <span style={{ fontSize: "0.7rem", color: "#16a34a", fontWeight: 600 }}>Active</span>
                      )}
                      <button
                        className={styles.btn}
                        style={{ fontSize: "0.7rem", padding: "2px 6px", background: "#ef4444", color: "#fff", border: "none", borderRadius: "4px" }}
                        onClick={() => handleDeleteVariant(expanded.id, v.id)}
                      >
                        Del
                      </button>
                      {v.error_message && (
                        <span style={{ fontSize: "0.7rem", color: "#dc2626", cursor: "help" }} title={v.error_message}>
                          Err
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
          </AdminTable>

          <div style={{ marginTop: "0.75rem", fontSize: "0.8rem", color: "var(--text-muted)" }}>
            <strong>Grid:</strong>{" "}
            {Object.entries(expanded.parameter_grid)
              .filter(([k, v]) => v !== undefined && v !== null && k !== "feature_grid")
              .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
              .join(" | ")}
          </div>
        </div>
      )}
    </AdminCard>
  );
}
