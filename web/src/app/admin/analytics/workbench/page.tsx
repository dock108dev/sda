"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  listFeatureLoadouts,
  getFeatureLoadout,
  createFeatureLoadout,
  updateFeatureLoadout,
  deleteFeatureLoadout,
  cloneFeatureLoadout,
  getAvailableFeatures,
  startTraining,
  listTrainingJobs,
  getTrainingJob,
  type FeatureLoadout,
  type AvailableFeature,
  type TrainingJob,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

type Tab = "loadouts" | "training";

export default function WorkbenchPage() {
  const [tab, setTab] = useState<Tab>("loadouts");

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Workbench</h1>
        <p className={styles.pageSubtitle}>
          Build feature loadouts and train models
        </p>
      </header>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        <button
          className={`${styles.btn} ${tab === "loadouts" ? styles.btnPrimary : ""}`}
          onClick={() => setTab("loadouts")}
        >
          Feature Loadouts
        </button>
        <button
          className={`${styles.btn} ${tab === "training" ? styles.btnPrimary : ""}`}
          onClick={() => setTab("training")}
        >
          Train Model
        </button>
      </div>

      {tab === "loadouts" ? <LoadoutsPanel /> : <TrainingPanel />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feature Loadouts Panel
// ---------------------------------------------------------------------------

function LoadoutsPanel() {
  const [loadouts, setLoadouts] = useState<FeatureLoadout[]>([]);
  const [selected, setSelected] = useState<FeatureLoadout | null>(null);
  const [availableFeatures, setAvailableFeatures] = useState<AvailableFeature[]>([]);
  const [totalGames, setTotalGames] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newModelType, setNewModelType] = useState("game");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [loadoutRes, featRes] = await Promise.all([
        listFeatureLoadouts("mlb"),
        getAvailableFeatures("mlb"),
      ]);
      setLoadouts(loadoutRes.loadouts);
      setAvailableFeatures(featRes.all_features);
      setTotalGames(featRes.total_games_with_data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setError(null);
    try {
      const features = availableFeatures
        .filter((f) => f.model_types.includes(newModelType))
        .map((f) => ({ name: f.name, enabled: true, weight: 1.0 }));

      const res = await createFeatureLoadout({
        name: newName.trim(),
        sport: "mlb",
        model_type: newModelType,
        features,
      });
      setCreating(false);
      setNewName("");
      await refresh();
      setSelected(res as FeatureLoadout);
      setMessage(`Created loadout "${res.name}"`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleClone = async (id: number) => {
    setError(null);
    try {
      const res = await cloneFeatureLoadout(id);
      await refresh();
      setSelected(res as FeatureLoadout);
      setMessage(`Cloned as "${res.name}"`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDelete = async (id: number) => {
    setError(null);
    try {
      await deleteFeatureLoadout(id);
      if (selected?.id === id) setSelected(null);
      await refresh();
      setMessage("Loadout deleted");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleToggle = (featureName: string) => {
    if (!selected) return;
    const updated = selected.features.map((f) =>
      f.name === featureName ? { ...f, enabled: !f.enabled } : f,
    );
    setSelected({ ...selected, features: updated });
  };

  const handleWeightChange = (featureName: string, weight: number) => {
    if (!selected) return;
    const updated = selected.features.map((f) =>
      f.name === featureName ? { ...f, weight } : f,
    );
    setSelected({ ...selected, features: updated });
  };

  const handleSave = async () => {
    if (!selected) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const res = await updateFeatureLoadout(selected.id, {
        name: selected.name,
        features: selected.features,
      });
      setSelected(res as FeatureLoadout);
      await refresh();
      const enabled = selected.features.filter((f) => f.enabled).length;
      setMessage(`Saved: ${enabled} features enabled`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleSelect = async (id: number) => {
    setError(null);
    setMessage(null);
    try {
      const data = await getFeatureLoadout(id);
      setSelected(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (loading && !loadouts.length) {
    return <div className={styles.loading}>Loading...</div>;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "1.5rem" }}>
      {/* Left panel: loadout list */}
      <div>
        <AdminCard title="Loadouts" subtitle={`${loadouts.length} saved`}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {loadouts.map((l) => (
              <div
                key={l.id}
                style={{
                  padding: "0.5rem",
                  cursor: "pointer",
                  borderRadius: "4px",
                  background: selected?.id === l.id ? "var(--color-primary-bg, #e8f0fe)" : "transparent",
                  border: selected?.id === l.id ? "1px solid var(--color-primary, #4285f4)" : "1px solid transparent",
                }}
                onClick={() => handleSelect(l.id)}
              >
                <div style={{ fontWeight: 500, fontSize: "0.875rem" }}>{l.name}</div>
                <div style={{ fontSize: "0.75rem", color: "#666" }}>
                  {l.model_type} &middot; {l.enabled_count}/{l.total_count} features
                </div>
                <div style={{ display: "flex", gap: "0.25rem", marginTop: "0.25rem" }}>
                  <button
                    className={styles.btn}
                    style={{ fontSize: "0.7rem", padding: "2px 6px" }}
                    onClick={(e) => { e.stopPropagation(); handleClone(l.id); }}
                  >
                    Clone
                  </button>
                  <button
                    className={styles.btn}
                    style={{ fontSize: "0.7rem", padding: "2px 6px", color: "#c00" }}
                    onClick={(e) => { e.stopPropagation(); handleDelete(l.id); }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div style={{ marginTop: "0.75rem", borderTop: "1px solid #e0e0e0", paddingTop: "0.75rem" }}>
            {creating ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                <input
                  type="text"
                  placeholder="Loadout name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  style={{ padding: "0.375rem", fontSize: "0.875rem" }}
                />
                <select
                  value={newModelType}
                  onChange={(e) => setNewModelType(e.target.value)}
                  style={{ padding: "0.375rem", fontSize: "0.875rem" }}
                >
                  <option value="game">Game</option>
                  <option value="plate_appearance">Plate Appearance</option>
                </select>
                <div style={{ display: "flex", gap: "0.25rem" }}>
                  <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleCreate}>
                    Create
                  </button>
                  <button className={styles.btn} onClick={() => setCreating(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={() => setCreating(true)}
                style={{ width: "100%" }}
              >
                + New Loadout
              </button>
            )}
          </div>
        </AdminCard>

        {totalGames > 0 && (
          <div style={{ marginTop: "0.75rem", fontSize: "0.8rem", color: "#666" }}>
            {totalGames.toLocaleString()} games with Statcast data
          </div>
        )}
      </div>

      {/* Right panel: feature grid */}
      <div>
        {error && <div className={styles.error}>{error}</div>}
        {message && <div className={styles.success}>{message}</div>}

        {selected ? (
          <AdminCard
            title={selected.name}
            subtitle={`${selected.sport.toUpperCase()} ${selected.model_type} | ${selected.features.filter((f) => f.enabled).length}/${selected.features.length} features enabled`}
          >
            <div style={{ marginBottom: "0.75rem", display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <input
                type="text"
                value={selected.name}
                onChange={(e) => setSelected({ ...selected, name: e.target.value })}
                style={{ padding: "0.375rem", fontSize: "0.875rem", flex: 1 }}
              />
              <button
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>

            <AdminTable headers={["Feature", "Enabled", "Weight", "Description"]}>
              {selected.features.map((feat) => {
                const meta = availableFeatures.find((f) => f.name === feat.name);
                return (
                  <tr key={feat.name}>
                    <td style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>
                      {feat.name}
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        checked={feat.enabled}
                        onChange={() => handleToggle(feat.name)}
                      />
                    </td>
                    <td>
                      <input
                        type="range"
                        min={0}
                        max={2}
                        step={0.1}
                        value={feat.weight}
                        onChange={(e) =>
                          handleWeightChange(feat.name, parseFloat(e.target.value))
                        }
                        disabled={!feat.enabled}
                        style={{ width: "80px" }}
                      />
                      <span style={{ marginLeft: "0.5rem", fontSize: "0.8rem" }}>
                        {feat.weight.toFixed(1)}
                      </span>
                    </td>
                    <td style={{ fontSize: "0.8rem", color: "#666" }}>
                      {meta?.description || ""}
                    </td>
                  </tr>
                );
              })}
            </AdminTable>
          </AdminCard>
        ) : (
          <AdminCard title="Feature Loadout Builder">
            <p style={{ color: "#666" }}>
              Select a loadout from the left panel or create a new one to get started.
            </p>
            <p style={{ color: "#999", fontSize: "0.85rem", marginTop: "0.5rem" }}>
              Feature loadouts define which data features are used when training ML models.
              Toggle features on/off and adjust weights to experiment with different configurations.
            </p>
          </AdminCard>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Training Panel
// ---------------------------------------------------------------------------

function TrainingPanel() {
  const [loadouts, setLoadouts] = useState<FeatureLoadout[]>([]);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [selectedLoadout, setSelectedLoadout] = useState<number | null>(null);
  const [modelType, setModelType] = useState("game");
  const [algorithm, setAlgorithm] = useState("gradient_boosting");
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [testSplit, setTestSplit] = useState(0.2);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [loadoutRes, jobsRes] = await Promise.all([
        listFeatureLoadouts("mlb"),
        listTrainingJobs("mlb"),
      ]);
      setLoadouts(loadoutRes.loadouts);
      setJobs(jobsRes.jobs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll for in-progress jobs
  useEffect(() => {
    const activeJobs = jobs.filter(
      (j) => j.status === "pending" || j.status === "queued" || j.status === "running",
    );
    if (activeJobs.length === 0) return;

    const interval = setInterval(async () => {
      try {
        const jobsRes = await listTrainingJobs("mlb");
        setJobs(jobsRes.jobs);
      } catch {
        // ignore poll errors
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [jobs]);

  const handleTrain = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await startTraining({
        feature_config_id: selectedLoadout,
        sport: "mlb",
        model_type: modelType,
        algorithm,
        date_start: dateStart || undefined,
        date_end: dateEnd || undefined,
        test_split: testSplit,
      });
      setMessage(`Training job #${res.job.id} submitted`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
      {/* Training Form */}
      <AdminCard title="Train Model" subtitle="Configure and start a training job">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Feature Loadout</label>
            <select
              value={selectedLoadout ?? ""}
              onChange={(e) =>
                setSelectedLoadout(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">None (use defaults)</option>
              {loadouts.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.enabled_count} features)
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Model Type</label>
            <select value={modelType} onChange={(e) => setModelType(e.target.value)}>
              <option value="game">Game (Win/Loss)</option>
              <option value="plate_appearance">Plate Appearance</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Algorithm</label>
            <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
              <option value="gradient_boosting">Gradient Boosting</option>
              <option value="random_forest">Random Forest</option>
              <option value="xgboost">XGBoost</option>
            </select>
          </div>
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Date Start</label>
            <input
              type="date"
              value={dateStart}
              onChange={(e) => setDateStart(e.target.value)}
            />
          </div>
          <div className={styles.formGroup}>
            <label>Date End</label>
            <input
              type="date"
              value={dateEnd}
              onChange={(e) => setDateEnd(e.target.value)}
            />
          </div>
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Test Split: {(testSplit * 100).toFixed(0)}%</label>
            <input
              type="range"
              min={0.05}
              max={0.5}
              step={0.05}
              value={testSplit}
              onChange={(e) => setTestSplit(parseFloat(e.target.value))}
            />
          </div>
        </div>

        {error && <div className={styles.error}>{error}</div>}
        {message && <div className={styles.success}>{message}</div>}

        <button
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={handleTrain}
          disabled={submitting}
          style={{ marginTop: "1rem" }}
        >
          {submitting ? "Submitting..." : "Train Model"}
        </button>
      </AdminCard>

      {/* Training Jobs List */}
      <AdminCard title="Training Jobs" subtitle={`${jobs.length} jobs`}>
        {jobs.length === 0 ? (
          <p style={{ color: "#666" }}>No training jobs yet. Start one from the form.</p>
        ) : (
          <AdminTable headers={["ID", "Type", "Algorithm", "Status", "Metrics"]}>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>#{job.id}</td>
                <td style={{ fontSize: "0.85rem" }}>{job.model_type}</td>
                <td style={{ fontSize: "0.85rem" }}>{job.algorithm}</td>
                <td>
                  <StatusBadge status={job.status} />
                </td>
                <td style={{ fontSize: "0.8rem" }}>
                  {job.metrics ? (
                    <span>
                      acc: {((job.metrics.accuracy ?? 0) * 100).toFixed(1)}%
                      {job.metrics.brier_score != null && (
                        <> &middot; brier: {job.metrics.brier_score.toFixed(3)}</>
                      )}
                    </span>
                  ) : job.error_message ? (
                    <span style={{ color: "#c00" }} title={job.error_message}>
                      Error
                    </span>
                  ) : (
                    <span style={{ color: "#999" }}>--</span>
                  )}
                </td>
              </tr>
            ))}
          </AdminTable>
        )}
      </AdminCard>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    pending: { bg: "#f0f0f0", fg: "#666" },
    queued: { bg: "#fff3cd", fg: "#856404" },
    running: { bg: "#cce5ff", fg: "#004085" },
    completed: { bg: "#d4edda", fg: "#155724" },
    failed: { bg: "#f8d7da", fg: "#721c24" },
  };
  const c = colors[status] || colors.pending;
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: "4px",
        fontSize: "0.75rem",
        fontWeight: 600,
        background: c.bg,
        color: c.fg,
      }}
    >
      {status}
    </span>
  );
}
