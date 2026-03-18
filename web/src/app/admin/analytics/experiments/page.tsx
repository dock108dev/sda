"use client";

import { useState, useEffect } from "react";
import { AdminCard } from "@/components/admin";
import {
  getAvailableFeatures,
  createExperimentSuite,
  type AvailableFeature,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";
import { ExperimentHistory } from "./ExperimentHistory";

const ALGORITHMS = [
  { value: "gradient_boosting", label: "Gradient Boosting" },
  { value: "random_forest", label: "Random Forest" },
  { value: "xgboost", label: "XGBoost" },
];

const ROLLING_WINDOWS = [10, 15, 20, 25, 30, 40, 50, 60];
const TEST_SPLITS = [0.1, 0.15, 0.2, 0.25, 0.3];

export default function ExperimentsPage() {
  // Bump to trigger history refresh after a new experiment is submitted
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Experiments</h1>
        <p className={styles.pageSubtitle}>
          Configure feature combinations and parameter sweeps, then compare results
        </p>
      </header>

      <ExperimentBuilder onSubmitted={() => setRefreshKey((k) => k + 1)} />
      <div style={{ marginTop: "1.5rem" }}>
        <ExperimentHistory refreshKey={refreshKey} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Feature grid entry — per-feature config for the experiment         */
/* ------------------------------------------------------------------ */

interface FeatureGridEntry {
  name: string;
  description: string;
  enabled: boolean;
  vary_enabled: boolean; // whether to include on/off as a dimension
  weight_min: number;
  weight_max: number;
}

/* ------------------------------------------------------------------ */
/*  Experiment Builder                                                 */
/* ------------------------------------------------------------------ */

function ExperimentBuilder({ onSubmitted }: { onSubmitted: () => void }) {
  const [name, setName] = useState("");
  const [selectedAlgorithms, setSelectedAlgorithms] = useState<Set<string>>(new Set(["gradient_boosting"]));
  const [selectedWindows, setSelectedWindows] = useState<Set<number>>(new Set([30]));
  const [selectedSplits, setSelectedSplits] = useState<Set<number>>(new Set([0.2]));
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [tags, setTags] = useState("");
  const [maxCombos, setMaxCombos] = useState(50);

  // Feature grid
  const [availableFeatures, setAvailableFeatures] = useState<AvailableFeature[]>([]);
  const [featureGrid, setFeatureGrid] = useState<FeatureGridEntry[]>([]);
  const [featuresLoading, setFeaturesLoading] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Load available features on mount
  useEffect(() => {
    getAvailableFeatures("mlb")
      .then((res) => {
        setAvailableFeatures(res.plate_appearance_features || res.all_features || []);
        // Initialize grid: all features enabled, weight 1.0, no variation
        const grid = (res.plate_appearance_features || res.all_features || []).map((f) => ({
          name: f.name,
          description: f.description,
          enabled: true,
          vary_enabled: false,
          weight_min: 1.0,
          weight_max: 1.0,
        }));
        setFeatureGrid(grid);
      })
      .catch(() => {})
      .finally(() => setFeaturesLoading(false));
  }, []);

  const enabledFeatures = featureGrid.filter((f) => f.enabled);
  const variableFeatures = featureGrid.filter((f) => f.enabled && (f.vary_enabled || f.weight_min !== f.weight_max));
  const hasFeatureVariation = variableFeatures.length > 0;

  // Feature combos are generated server-side; estimate here for display
  const featureComboEstimate = hasFeatureVariation
    ? Math.min(maxCombos, variableFeatures.length + 3 + Math.max(0, maxCombos - variableFeatures.length - 3))
    : 1;
  const totalVariants = selectedAlgorithms.size * selectedWindows.size * selectedSplits.size * featureComboEstimate;

  function toggleSet<T>(set: Set<T>, value: T): Set<T> {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  }

  function updateFeature(name: string, update: Partial<FeatureGridEntry>) {
    setFeatureGrid((prev) =>
      prev.map((f) => (f.name === name ? { ...f, ...update } : f)),
    );
  }

  async function handleSubmit() {
    if (!name.trim()) { setError("Name is required"); return; }
    if (selectedAlgorithms.size === 0) { setError("Select at least one algorithm"); return; }
    if (enabledFeatures.length === 0) { setError("Enable at least one feature"); return; }
    if (totalVariants > 1000) { setError("Too many estimated variants (max 1000). Reduce parameters or max feature combos."); return; }

    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await createExperimentSuite({
        name: name.trim(),
        sport: "mlb",
        model_type: "plate_appearance",
        parameter_grid: {
          algorithms: Array.from(selectedAlgorithms),
          rolling_windows: Array.from(selectedWindows),
          test_splits: Array.from(selectedSplits),
          date_start: dateStart || undefined,
          date_end: dateEnd || undefined,
          feature_grid: {
            features: featureGrid
              .filter((f) => f.enabled)
              .map((f) => ({
                name: f.name,
                enabled: true,
                weight_min: f.weight_min,
                weight_max: f.weight_max,
                vary_enabled: f.vary_enabled || undefined,
              })),
            max_combos: maxCombos,
          },
        },
        tags: tags ? tags.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
      });
      setMessage(`Experiment "${res.suite.name}" submitted — variants will be generated by the worker`);
      setName("");
      onSubmitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminCard title="New Experiment" subtitle={`~${totalVariants} variant${totalVariants !== 1 ? "s" : ""} (${featureComboEstimate} feature combo${featureComboEstimate !== 1 ? "s" : ""} x ${selectedAlgorithms.size} algo x ${selectedWindows.size} window x ${selectedSplits.size} split)`}>
      <div className={styles.formRow}>
        <div className={styles.formGroup}>
          <label>Experiment Name</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. feature sweep v3" />
        </div>
      </div>

      {/* Parameter Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem", marginTop: "0.5rem" }}>
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
                onChange={() => setSelectedAlgorithms((prev) => toggleSet(prev, a.value))}
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
                onClick={() => setSelectedWindows((prev) => toggleSet(prev, w))}
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
                onClick={() => setSelectedSplits((prev) => toggleSet(prev, s))}
              >
                {(s * 100).toFixed(0)}%
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Feature Grid */}
      <div style={{ marginTop: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
          <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)" }}>
            Features ({enabledFeatures.length} enabled, {variableFeatures.length} variable)
          </label>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <label style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Max combos:</label>
            <input
              type="number"
              value={maxCombos}
              onChange={(e) => setMaxCombos(Math.max(1, Math.min(1000, parseInt(e.target.value) || 1)))}
              min={1}
              max={1000}
              style={{ width: "60px", padding: "2px 4px", fontSize: "0.8rem" }}
            />
            <button
              className={styles.btn}
              style={{ fontSize: "0.7rem", padding: "2px 6px" }}
              onClick={() => setFeatureGrid((prev) => prev.map((f) => ({ ...f, enabled: true })))}
            >
              All on
            </button>
            <button
              className={styles.btn}
              style={{ fontSize: "0.7rem", padding: "2px 6px" }}
              onClick={() => setFeatureGrid((prev) => prev.map((f) => ({ ...f, enabled: false })))}
            >
              All off
            </button>
          </div>
        </div>

        {featuresLoading ? (
          <p style={{ color: "var(--text-muted)" }}>Loading features...</p>
        ) : (
          <div style={{ maxHeight: "350px", overflowY: "auto", border: "1px solid var(--border)", borderRadius: "6px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", position: "sticky", top: 0, background: "#fff" }}>
                  <th style={{ textAlign: "left", padding: "0.35rem 0.5rem" }}>Feature</th>
                  <th style={{ textAlign: "center", padding: "0.35rem 0.5rem", width: "50px" }}>On</th>
                  <th style={{ textAlign: "center", padding: "0.35rem 0.5rem", width: "50px" }}>Vary</th>
                  <th style={{ textAlign: "center", padding: "0.35rem 0.5rem", width: "140px" }}>Weight Range</th>
                </tr>
              </thead>
              <tbody>
                {featureGrid.map((f) => (
                  <tr key={f.name} style={{ borderBottom: "1px solid #f1f5f9", opacity: f.enabled ? 1 : 0.4 }}>
                    <td style={{ padding: "0.3rem 0.5rem" }}>
                      <span style={{ fontFamily: "monospace", fontSize: "0.75rem" }}>{f.name}</span>
                      {f.description && (
                        <span style={{ color: "var(--text-muted)", marginLeft: "0.5rem", fontSize: "0.7rem" }}>{f.description}</span>
                      )}
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={f.enabled}
                        onChange={(e) => updateFeature(f.name, { enabled: e.target.checked })}
                      />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={f.vary_enabled}
                        disabled={!f.enabled}
                        onChange={(e) => updateFeature(f.name, { vary_enabled: e.target.checked })}
                        title="Include on/off as a variation dimension"
                      />
                    </td>
                    <td style={{ textAlign: "center", padding: "0.2rem 0.25rem" }}>
                      <div style={{ display: "flex", gap: "0.25rem", alignItems: "center", justifyContent: "center" }}>
                        <input
                          type="number"
                          value={f.weight_min}
                          onChange={(e) => updateFeature(f.name, { weight_min: parseFloat(e.target.value) || 0 })}
                          disabled={!f.enabled}
                          min={0}
                          max={3}
                          step={0.1}
                          style={{ width: "50px", padding: "1px 3px", fontSize: "0.75rem", textAlign: "center" }}
                        />
                        <span style={{ color: "var(--text-muted)" }}>-</span>
                        <input
                          type="number"
                          value={f.weight_max}
                          onChange={(e) => updateFeature(f.name, { weight_max: parseFloat(e.target.value) || 0 })}
                          disabled={!f.enabled}
                          min={0}
                          max={3}
                          step={0.1}
                          style={{ width: "50px", padding: "1px 3px", fontSize: "0.75rem", textAlign: "center" }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {hasFeatureVariation && (
          <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
            Up to {maxCombos} feature combinations will be generated (baseline + ablation + boundary + random samples)
          </p>
        )}
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
        disabled={submitting || enabledFeatures.length === 0 || totalVariants > 1000}
        style={{ marginTop: "0.75rem" }}
      >
        {submitting ? "Submitting..." : `Run Experiment (~${totalVariants} variants)`}
      </button>
    </AdminCard>
  );
}

