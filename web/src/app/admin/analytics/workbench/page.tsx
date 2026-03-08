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
  cancelTrainingJob,
  listEnsembleConfigs,
  saveEnsembleConfig,
  type FeatureLoadout,
  type AvailableFeature,
  type TrainingJob,
  type EnsembleConfigResponse,
  type EnsembleProviderWeight,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

type Tab = "loadouts" | "training" | "ensemble";

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
        <button
          className={`${styles.btn} ${tab === "ensemble" ? styles.btnPrimary : ""}`}
          onClick={() => setTab("ensemble")}
        >
          Ensemble Config
        </button>
      </div>

      {tab === "loadouts" ? <LoadoutsPanel /> : tab === "training" ? <TrainingPanel /> : <EnsemblePanel />}
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
  const [rollingWindow, setRollingWindow] = useState(30);
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

  const [cancelingIds, setCancelingIds] = useState<Set<number>>(new Set());

  const handleCancel = async (jobId: number) => {
    setCancelingIds((prev) => new Set(prev).add(jobId));
    try {
      await cancelTrainingJob(jobId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCancelingIds((prev) => {
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
    }
  };

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
        rolling_window: rollingWindow,
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
              <option value="plate_appearance" disabled>Plate Appearance (coming soon)</option>
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
          <div className={styles.formGroup}>
            <label>Rolling Window: {rollingWindow} games</label>
            <input
              type="range"
              min={5}
              max={80}
              step={5}
              value={rollingWindow}
              onChange={(e) => setRollingWindow(parseInt(e.target.value))}
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
          <AdminTable headers={["ID", "Type", "Algorithm", "Status", "Metrics", "Actions"]}>
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
                <td>
                  {["pending", "queued", "running"].includes(job.status) ? (
                    <button
                      onClick={() => handleCancel(job.id)}
                      disabled={cancelingIds.has(job.id)}
                      style={{
                        padding: "2px 8px",
                        fontSize: "0.75rem",
                        borderRadius: "4px",
                        border: "1px solid #c00",
                        background: "#fff",
                        color: "#c00",
                        cursor: cancelingIds.has(job.id) ? "not-allowed" : "pointer",
                        opacity: cancelingIds.has(job.id) ? 0.6 : 1,
                      }}
                    >
                      {cancelingIds.has(job.id) ? "Canceling..." : "Cancel"}
                    </button>
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

// ---------------------------------------------------------------------------
// Ensemble Configuration Panel
// ---------------------------------------------------------------------------

const KNOWN_PROVIDERS = ["rule_based", "ml", "ensemble"];

function EnsemblePanel() {
  const [configs, setConfigs] = useState<EnsembleConfigResponse[]>([]);
  const [selected, setSelected] = useState<EnsembleConfigResponse | null>(null);
  const [editing, setEditing] = useState<EnsembleProviderWeight[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listEnsembleConfigs();
      setConfigs(res.configs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSelect = (cfg: EnsembleConfigResponse) => {
    setSelected(cfg);
    setEditing(cfg.providers.map((p) => ({ ...p })));
    setMessage(null);
    setError(null);
  };

  const handleWeightChange = (index: number, weight: number) => {
    setEditing((prev) => prev.map((p, i) => (i === index ? { ...p, weight } : p)));
  };

  const handleRemoveProvider = (index: number) => {
    setEditing((prev) => prev.filter((_, i) => i !== index));
  };

  const handleAddProvider = () => {
    const existing = new Set(editing.map((p) => p.name));
    const available = KNOWN_PROVIDERS.filter((n) => !existing.has(n));
    const name = available[0];
    if (!name) return;
    setEditing((prev) => [...prev, { name, weight: 0.5 }]);
  };

  const totalWeight = editing.reduce((sum, p) => sum + p.weight, 0);

  const handleSave = async () => {
    if (!selected) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const res = await saveEnsembleConfig(selected.sport, selected.model_type, editing);
      setMessage(`Saved ${selected.sport}/${selected.model_type} ensemble config`);
      // Update local state
      setSelected({ ...selected, providers: res.providers });
      setEditing(res.providers.map((p) => ({ ...p })));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleNormalize = () => {
    if (totalWeight === 0) return;
    setEditing((prev) =>
      prev.map((p) => ({
        ...p,
        weight: Math.round((p.weight / totalWeight) * 1000) / 1000,
      })),
    );
  };

  if (loading && !configs.length) {
    return <div className={styles.loading}>Loading ensemble configs...</div>;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "1.5rem" }}>
      {/* Left: config list */}
      <div>
        <AdminCard title="Ensemble Configs" subtitle={`${configs.length} configured`}>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {configs.map((cfg) => {
              const key = `${cfg.sport}/${cfg.model_type}`;
              const isSelected = selected?.sport === cfg.sport && selected?.model_type === cfg.model_type;
              return (
                <div
                  key={key}
                  style={{
                    padding: "0.5rem",
                    cursor: "pointer",
                    borderRadius: "4px",
                    background: isSelected ? "var(--color-primary-bg, #e8f0fe)" : "transparent",
                    border: isSelected ? "1px solid var(--color-primary, #4285f4)" : "1px solid transparent",
                  }}
                  onClick={() => handleSelect(cfg)}
                >
                  <div style={{ fontWeight: 500, fontSize: "0.875rem" }}>
                    {cfg.sport.toUpperCase()} / {cfg.model_type}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "#666" }}>
                    {cfg.providers.length} provider{cfg.providers.length !== 1 ? "s" : ""}
                    {" — "}
                    {cfg.providers.map((p) => `${p.name}:${p.weight}`).join(", ")}
                  </div>
                </div>
              );
            })}

            {configs.length === 0 && (
              <p style={{ color: "#666", fontSize: "0.85rem" }}>
                No ensemble configs found. The API returns defaults on first load.
              </p>
            )}
          </div>
        </AdminCard>
      </div>

      {/* Right: editor */}
      <div>
        {error && <div className={styles.error}>{error}</div>}
        {message && <div className={styles.success}>{message}</div>}

        {selected ? (
          <AdminCard
            title={`${selected.sport.toUpperCase()} / ${selected.model_type}`}
            subtitle="Configure probability provider weights for ensemble mode"
          >
            <p style={{ fontSize: "0.85rem", color: "#666", marginBottom: "1rem" }}>
              When <strong>ensemble</strong> probability mode is used, predictions from
              each provider are combined using these weights. Weights are automatically
              normalized to sum to 1.0 at save time.
            </p>

            <AdminTable headers={["Provider", "Weight", "Proportion", ""]}>
              {editing.map((provider, i) => (
                <tr key={i}>
                  <td>
                    <select
                      value={provider.name}
                      onChange={(e) =>
                        setEditing((prev) =>
                          prev.map((p, idx) => (idx === i ? { ...p, name: e.target.value } : p)),
                        )
                      }
                      style={{ padding: "0.25rem", fontSize: "0.85rem" }}
                    >
                      {KNOWN_PROVIDERS.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={provider.weight}
                        onChange={(e) => handleWeightChange(i, parseFloat(e.target.value))}
                        style={{ width: "120px" }}
                      />
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={provider.weight}
                        onChange={(e) => handleWeightChange(i, parseFloat(e.target.value) || 0)}
                        style={{ width: "60px", padding: "0.25rem", fontSize: "0.85rem" }}
                      />
                    </div>
                  </td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <div
                        style={{
                          width: "80px",
                          height: "16px",
                          background: "#f3f4f6",
                          borderRadius: "3px",
                          overflow: "hidden",
                        }}
                      >
                        <div
                          style={{
                            width: `${totalWeight > 0 ? (provider.weight / totalWeight) * 100 : 0}%`,
                            height: "100%",
                            background: "var(--accent, #3b82f6)",
                            borderRadius: "3px",
                            transition: "width 0.2s",
                          }}
                        />
                      </div>
                      <span style={{ fontSize: "0.8rem", color: "#666" }}>
                        {totalWeight > 0
                          ? `${((provider.weight / totalWeight) * 100).toFixed(0)}%`
                          : "0%"}
                      </span>
                    </div>
                  </td>
                  <td>
                    <button
                      className={styles.btn}
                      style={{ fontSize: "0.7rem", padding: "2px 6px", color: "#c00" }}
                      onClick={() => handleRemoveProvider(i)}
                      disabled={editing.length <= 1}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </AdminTable>

            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", alignItems: "center" }}>
              <button
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={handleSave}
                disabled={saving || editing.length === 0}
              >
                {saving ? "Saving..." : "Save Config"}
              </button>
              <button
                className={styles.btn}
                onClick={handleNormalize}
                disabled={totalWeight === 0}
              >
                Normalize to 1.0
              </button>
              <button
                className={styles.btn}
                onClick={handleAddProvider}
                disabled={editing.length >= KNOWN_PROVIDERS.length}
              >
                + Add Provider
              </button>
              <span style={{ fontSize: "0.8rem", color: totalWeight > 0.99 && totalWeight < 1.01 ? "#22c55e" : "#f59e0b" }}>
                Total weight: {totalWeight.toFixed(3)}
              </span>
            </div>
          </AdminCard>
        ) : (
          <AdminCard title="Ensemble Configuration">
            <p style={{ color: "#666" }}>
              Select an ensemble config from the left panel to edit provider weights.
            </p>
            <p style={{ color: "#999", fontSize: "0.85rem", marginTop: "0.5rem" }}>
              Ensemble mode combines predictions from multiple probability providers
              (rule-based, ML model) using configurable weights. This controls how much
              each source contributes to the final win probability used in simulations.
            </p>
          </AdminCard>
        )}
      </div>
    </div>
  );
}
