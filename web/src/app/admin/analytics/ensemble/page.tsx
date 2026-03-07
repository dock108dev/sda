"use client";

import { useEffect, useState } from "react";
import { AdminCard } from "@/components/admin";
import {
  listEnsembleConfigs,
  saveEnsembleConfig,
  type EnsembleConfigResponse,
  type EnsembleProviderWeight,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function EnsemblePage() {
  const [configs, setConfigs] = useState<EnsembleConfigResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Editable state keyed by "sport:model_type"
  const [drafts, setDrafts] = useState<
    Record<string, EnsembleProviderWeight[]>
  >({});

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await listEnsembleConfigs();
      setConfigs(res.configs);
      const d: Record<string, EnsembleProviderWeight[]> = {};
      for (const c of res.configs) {
        d[`${c.sport}:${c.model_type}`] = c.providers.map((p) => ({ ...p }));
      }
      setDrafts(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function updateWeight(key: string, idx: number, weight: number) {
    setDrafts((prev) => {
      const copy = { ...prev };
      copy[key] = copy[key].map((p, i) =>
        i === idx ? { ...p, weight } : p,
      );
      return copy;
    });
  }

  async function handleSave(cfg: EnsembleConfigResponse) {
    const key = `${cfg.sport}:${cfg.model_type}`;
    const providers = drafts[key];
    if (!providers) return;
    setSaving(true);
    setError(null);
    try {
      await saveEnsembleConfig(cfg.sport, cfg.model_type, providers);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Ensemble Configuration</h1>
        <p className={styles.pageSubtitle}>
          Configure how multiple probability sources are combined for predictions and simulations
        </p>
      </header>

      {error && <div className={styles.error}>{error}</div>}
      {loading && <p>Loading configurations...</p>}

      {!loading && configs.length === 0 && (
        <AdminCard title="No Configurations">
          <p>No ensemble configurations found.</p>
        </AdminCard>
      )}

      {configs.map((cfg) => {
        const key = `${cfg.sport}:${cfg.model_type}`;
        const providers = drafts[key] || cfg.providers;
        const total = providers.reduce((s, p) => s + p.weight, 0);

        return (
          <AdminCard
            key={key}
            title={`${cfg.sport.toUpperCase()} ${cfg.model_type}`}
            subtitle={`${providers.length} provider(s) — total weight: ${total.toFixed(2)}`}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {providers.map((p, i) => (
                <div key={p.name} className={styles.formRow}>
                  <div className={styles.formGroup}>
                    <label>{p.name}</label>
                    <input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      value={p.weight}
                      onChange={(e) =>
                        updateWeight(key, i, parseFloat(e.target.value) || 0)
                      }
                      style={{ width: "100px" }}
                    />
                  </div>
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    <div className={styles.probTrack}>
                      <div
                        className={styles.probFill}
                        style={{
                          width: `${Math.min(p.weight * 100, 100)}%`,
                        }}
                      />
                    </div>
                    <span
                      className={styles.probValue}
                      style={{ marginLeft: "0.5rem" }}
                    >
                      {(p.weight * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: "1rem" }}>
              <button
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={() => handleSave(cfg)}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save Weights"}
              </button>
            </div>
          </AdminCard>
        );
      })}
    </div>
  );
}
