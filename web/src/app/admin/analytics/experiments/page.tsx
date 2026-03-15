"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  listFeatureLoadouts,
  createExperimentSuite,
  listExperimentSuites,
  getExperimentSuite,
  promoteExperimentVariant,
  type FeatureLoadout,
  type ExperimentSuite,
  type ExperimentVariant,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

const ALGORITHMS = [
  { value: "gradient_boosting", label: "Gradient Boosting" },
  { value: "random_forest", label: "Random Forest" },
  { value: "xgboost", label: "XGBoost" },
];

const ROLLING_WINDOWS = [10, 15, 20, 25, 30, 40, 50, 60];
const TEST_SPLITS = [0.1, 0.15, 0.2, 0.25, 0.3];

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

export default function ExperimentsPage() {
  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Experiments</h1>
        <p className={styles.pageSubtitle}>
          Configure parameter sweeps, run combinatorial training, and compare results
        </p>
      </header>

      <ExperimentBuilder />
      <div style={{ marginTop: "1.5rem" }}>
        <ExperimentHistory />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Experiment Builder — grid configuration form                       */
/* ------------------------------------------------------------------ */

function ExperimentBuilder() {
  const [name, setName] = useState("");
  const [selectedAlgorithms, setSelectedAlgorithms] = useState<Set<string>>(new Set(["gradient_boosting"]));
  const [selectedWindows, setSelectedWindows] = useState<Set<number>>(new Set([30]));
  const [selectedSplits, setSelectedSplits] = useState<Set<number>>(new Set([0.2]));
  const [selectedLoadoutIds, setSelectedLoadoutIds] = useState<Set<number>>(new Set());
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [tags, setTags] = useState("");

  const [loadouts, setLoadouts] = useState<FeatureLoadout[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    listFeatureLoadouts("mlb").then((res) => setLoadouts(res.loadouts)).catch(() => {});
  }, []);

  const loadoutCount = Math.max(selectedLoadoutIds.size, 1); // at least 1 (defaults)
  const totalVariants = selectedAlgorithms.size * selectedWindows.size * selectedSplits.size * loadoutCount;

  function toggleSet<T>(set: Set<T>, value: T): Set<T> {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  }

  async function handleSubmit() {
    if (!name.trim()) { setError("Name is required"); return; }
    if (selectedAlgorithms.size === 0) { setError("Select at least one algorithm"); return; }
    if (selectedLoadoutIds.size === 0) { setError("Select at least one feature loadout"); return; }
    if (totalVariants > 100) { setError("Too many variants (max 100). Reduce parameter combinations."); return; }

    const modelType = "plate_appearance";

    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await createExperimentSuite({
        name: name.trim(),
        sport: "mlb",
        model_type: modelType,
        parameter_grid: {
          algorithms: Array.from(selectedAlgorithms),
          rolling_windows: Array.from(selectedWindows),
          test_splits: Array.from(selectedSplits),
          feature_config_ids: Array.from(selectedLoadoutIds),
          date_start: dateStart || undefined,
          date_end: dateEnd || undefined,
        },
        tags: tags ? tags.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
      });
      setMessage(`Experiment "${res.suite.name}" submitted with ${res.suite.total_variants} variants`);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminCard title="New Experiment" subtitle={`${totalVariants} variant${totalVariants !== 1 ? "s" : ""} will be generated`}>
      <div className={styles.formRow}>
        <div className={styles.formGroup}>
          <label>Experiment Name</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. pitch model sweep v2" />
        </div>
      </div>

      {/* Parameter Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginTop: "0.5rem" }}>
        {/* Algorithms */}
        <div>
          <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: "0.35rem" }}>
            Algorithms
          </label>
          {ALGORITHMS.map((a) => (
            <label key={a.value} style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
              <input
                type="checkbox"
                checked={selectedAlgorithms.has(a.value)}
                onChange={() => setSelectedAlgorithms(toggleSet(selectedAlgorithms, a.value))}
              />
              {a.label}
            </label>
          ))}
        </div>

        {/* Rolling Windows */}
        <div>
          <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: "0.35rem" }}>
            Rolling Windows
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
            {ROLLING_WINDOWS.map((w) => (
              <button
                key={w}
                className={styles.btn}
                style={{
                  fontSize: "0.75rem", padding: "2px 8px",
                  background: selectedWindows.has(w) ? "#3b82f6" : "#f3f4f6",
                  color: selectedWindows.has(w) ? "#fff" : "#374151",
                }}
                onClick={() => setSelectedWindows(toggleSet(selectedWindows, w))}
              >
                {w}
              </button>
            ))}
          </div>
        </div>

        {/* Test Splits */}
        <div>
          <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: "0.35rem" }}>
            Test Splits
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
            {TEST_SPLITS.map((s) => (
              <button
                key={s}
                className={styles.btn}
                style={{
                  fontSize: "0.75rem", padding: "2px 8px",
                  background: selectedSplits.has(s) ? "#3b82f6" : "#f3f4f6",
                  color: selectedSplits.has(s) ? "#fff" : "#374151",
                }}
                onClick={() => setSelectedSplits(toggleSet(selectedSplits, s))}
              >
                {(s * 100).toFixed(0)}%
              </button>
            ))}
          </div>
        </div>

        {/* Feature Loadouts */}
        <div>
          <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: "0.35rem" }}>
            Feature Loadouts
          </label>
          {loadouts.length === 0 && (
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              No loadouts found. Create one in Models &rarr; Loadouts.
            </p>
          )}
          {loadouts.map((l) => (
            <label key={l.id} style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
              <input
                type="checkbox"
                checked={selectedLoadoutIds.has(l.id)}
                onChange={() => setSelectedLoadoutIds(toggleSet(selectedLoadoutIds, l.id))}
              />
              {l.name} ({l.enabled_count} features)
            </label>
          ))}
          {selectedLoadoutIds.size > 0 && (
            <button
              className={styles.btn}
              style={{ fontSize: "0.7rem", padding: "2px 6px", marginTop: "0.25rem" }}
              onClick={() => setSelectedLoadoutIds(new Set())}
            >
              Clear selection
            </button>
          )}
        </div>
      </div>

      {/* Date range + tags */}
      <div className={styles.formRow} style={{ marginTop: "0.75rem" }}>
        <div className={styles.formGroup}>
          <label>Date Start (optional)</label>
          <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)} />
        </div>
        <div className={styles.formGroup}>
          <label>Date End (optional)</label>
          <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} />
        </div>
        <div className={styles.formGroup}>
          <label>Tags (comma-separated)</label>
          <input type="text" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="e.g. baseline, v2" />
        </div>
      </div>

      {error && <div className={styles.error} style={{ marginTop: "0.5rem" }}>{error}</div>}
      {message && <div className={styles.success} style={{ marginTop: "0.5rem" }}>{message}</div>}

      <button
        className={`${styles.btn} ${styles.btnPrimary}`}
        onClick={handleSubmit}
        disabled={submitting || totalVariants === 0}
        style={{ marginTop: "0.75rem" }}
      >
        {submitting ? "Submitting..." : `Run Experiment (${totalVariants} variants)`}
      </button>
    </AdminCard>
  );
}

/* ------------------------------------------------------------------ */
/*  Experiment History — list + detail view                            */
/* ------------------------------------------------------------------ */

function ExperimentHistory() {
  const [suites, setSuites] = useState<ExperimentSuite[]>([]);
  const [expanded, setExpanded] = useState<ExperimentSuite | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState<number | null>(null);

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
  }, [refresh]);

  // Poll for active suites
  useEffect(() => {
    const active = suites.filter((s) => ["pending", "queued", "running"].includes(s.status));
    if (active.length === 0) return;
    const interval = setInterval(async () => {
      try {
        const res = await listExperimentSuites("mlb");
        setSuites(res.suites);
        // Refresh expanded if it was active
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

  if (loading) return <div className={styles.loading}>Loading experiments...</div>;

  return (
    <AdminCard title="Experiment History" subtitle={`${suites.length} experiment(s)`}>
      {error && <div className={styles.error} style={{ marginBottom: "0.5rem" }}>{error}</div>}

      {suites.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No experiments yet. Configure and run one above.</p>
      ) : (
        <AdminTable headers={["ID", "Name", "Variants", "Progress", "Status", "Promoted", "Created", ""]}>
          {suites.map((s) => (
            <tr key={s.id}>
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
                <button
                  className={styles.btn}
                  style={{ fontSize: "0.8rem", padding: "2px 8px" }}
                  onClick={() => handleExpand(s.id)}
                >
                  {expanded?.id === s.id ? "Hide" : "Details"}
                </button>
              </td>
            </tr>
          ))}
        </AdminTable>
      )}

      {/* Expanded variant detail */}
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

          <AdminTable headers={["Rank", "Algorithm", "Window", "Split", "Loadout", "Status", "Accuracy", "Brier", "Log Loss", "Model ID", ""]}>
            {[...expanded.variants]
              .sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
              .map((v) => (
                <tr key={v.id} style={v.model_id === expanded.promoted_model_id ? { background: "rgba(34, 197, 94, 0.08)" } : {}}>
                  <td style={{ fontWeight: 600 }}>{v.rank ?? "-"}</td>
                  <td style={{ fontSize: "0.85rem" }}>{v.algorithm}</td>
                  <td>{v.rolling_window}</td>
                  <td>{(v.test_split * 100).toFixed(0)}%</td>
                  <td style={{ fontSize: "0.85rem" }}>{v.feature_config_id ?? "default"}</td>
                  <td><StatusBadge status={v.status} /></td>
                  <td>{v.training_metrics?.accuracy != null ? (v.training_metrics.accuracy * 100).toFixed(1) + "%" : "-"}</td>
                  <td>{v.training_metrics?.brier_score != null ? v.training_metrics.brier_score.toFixed(4) : "-"}</td>
                  <td>{v.training_metrics?.log_loss != null ? v.training_metrics.log_loss.toFixed(4) : "-"}</td>
                  <td style={{ fontSize: "0.8rem", fontFamily: "monospace" }}>{v.model_id ?? "-"}</td>
                  <td>
                    {v.model_id && v.status === "completed" && v.model_id !== expanded.promoted_model_id && (
                      <button
                        className={`${styles.btn} ${styles.btnPrimary}`}
                        style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                        onClick={() => handlePromote(expanded.id, v.id)}
                        disabled={promoting === v.id}
                      >
                        {promoting === v.id ? "..." : "Promote"}
                      </button>
                    )}
                    {v.model_id === expanded.promoted_model_id && (
                      <span style={{ fontSize: "0.75rem", color: "#16a34a", fontWeight: 600 }}>Active</span>
                    )}
                    {v.error_message && (
                      <span style={{ fontSize: "0.75rem", color: "#dc2626", cursor: "help" }} title={v.error_message}>
                        Error
                      </span>
                    )}
                  </td>
                </tr>
              ))}
          </AdminTable>

          {/* Parameter grid summary */}
          <div style={{ marginTop: "0.75rem", fontSize: "0.8rem", color: "var(--text-muted)" }}>
            <strong>Grid:</strong>{" "}
            {Object.entries(expanded.parameter_grid)
              .filter(([, v]) => v !== undefined && v !== null)
              .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
              .join(" | ")}
          </div>
        </div>
      )}
    </AdminCard>
  );
}
