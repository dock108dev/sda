"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  listFeatureLoadouts,
  getFeatureLoadout,
  createFeatureLoadout,
  updateFeatureLoadout,
  deleteFeatureLoadout,
  bulkDeleteFeatureLoadouts,
  cloneFeatureLoadout,
  getAvailableFeatures,
  type FeatureLoadout,
  type AvailableFeature,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export function LoadoutsPanel({ sportCode = "mlb" }: { sportCode?: string }) {
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
  const newModelType = "plate_appearance";
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [loadoutRes, featRes] = await Promise.all([
        listFeatureLoadouts(sportCode),
        getAvailableFeatures(sportCode),
      ]);
      setLoadouts(loadoutRes.loadouts);
      setAvailableFeatures(featRes.all_features);
      setTotalGames(featRes.total_games_with_data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sportCode]);

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
        sport: sportCode,
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

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    setError(null);
    try {
      const ids = Array.from(selectedIds);
      await bulkDeleteFeatureLoadouts(ids);
      if (selected && selectedIds.has(selected.id)) setSelected(null);
      setSelectedIds(new Set());
      await refresh();
      setMessage(`Deleted ${ids.length} loadout${ids.length !== 1 ? "s" : ""}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const toggleSelectId = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === loadouts.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(loadouts.map((l) => l.id)));
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
          {loadouts.length > 1 && (
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.5rem", paddingBottom: "0.5rem", borderBottom: "1px solid #e0e0e0" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "0.35rem", cursor: "pointer", fontSize: "0.75rem", color: "#666" }}>
                <input
                  type="checkbox"
                  checked={selectedIds.size === loadouts.length && loadouts.length > 0}
                  onChange={toggleSelectAll}
                />
                Select all
              </label>
              {selectedIds.size > 0 && (
                <button
                  className={styles.btn}
                  style={{ fontSize: "0.7rem", padding: "2px 6px", color: "#c00", marginLeft: "auto" }}
                  onClick={handleBulkDelete}
                >
                  Delete {selectedIds.size}
                </button>
              )}
            </div>
          )}
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
                  display: "flex",
                  gap: "0.5rem",
                  alignItems: "flex-start",
                }}
                onClick={() => handleSelect(l.id)}
              >
                <input
                  type="checkbox"
                  checked={selectedIds.has(l.id)}
                  onChange={(e) => { e.stopPropagation(); toggleSelectId(l.id); }}
                  onClick={(e) => e.stopPropagation()}
                  style={{ marginTop: "0.2rem" }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: "0.875rem" }}>{l.name}</div>
                  <div style={{ fontSize: "0.75rem", color: "#666" }}>
                    {l.enabled_count}/{l.total_count} features
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
            subtitle={`${selected.features.filter((f) => f.enabled).length}/${selected.features.length} features enabled`}
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
