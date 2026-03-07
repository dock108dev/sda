"use client";

import { useState, useCallback } from "react";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  getFeatureConfig,
  listFeatureConfigs,
  saveFeatureConfig,
  type FeatureConfigResponse,
} from "@/lib/api/analytics";
import styles from "../analytics.module.css";

export default function FeatureConfigPage() {
  const [configName, setConfigName] = useState("mlb_pa_model");
  const [available, setAvailable] = useState<string[]>([]);
  const [data, setData] = useState<FeatureConfigResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const handleListConfigs = useCallback(() => {
    listFeatureConfigs()
      .then((res) => setAvailable(res.available))
      .catch((err) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  }, []);

  const handleLoad = useCallback(() => {
    setLoading(true);
    setError(null);
    setMessage(null);
    handleListConfigs();
    getFeatureConfig(configName)
      .then(setData)
      .catch((err) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setLoading(false));
  }, [configName, handleListConfigs]);

  const handleToggle = (featureName: string) => {
    if (!data) return;
    const updated = { ...data.features };
    updated[featureName] = {
      ...updated[featureName],
      enabled: !updated[featureName].enabled,
    };
    setData({ ...data, features: updated });
  };

  const handleWeightChange = (featureName: string, weight: number) => {
    if (!data) return;
    const updated = { ...data.features };
    updated[featureName] = { ...updated[featureName], weight };
    setData({ ...data, features: updated });
  };

  const handleSave = useCallback(() => {
    if (!data) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    saveFeatureConfig({
      model: data.model,
      sport: data.sport,
      features: data.features,
    })
      .then((res) =>
        setMessage(
          `Saved: ${res.enabled_features.length} features enabled`,
        ),
      )
      .catch((err) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setSaving(false));
  }, [data]);

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Feature Configuration</h1>
        <p className={styles.pageSubtitle}>
          Manage ML feature selection, weighting, and experimentation
        </p>
      </header>

      <div className={styles.formRow} style={{ marginBottom: "1rem" }}>
        <div className={styles.formGroup}>
          <label>Config Name</label>
          {available.length > 0 ? (
            <select
              value={configName}
              onChange={(e) => setConfigName(e.target.value)}
            >
              {available.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={configName}
              onChange={(e) => setConfigName(e.target.value)}
              placeholder="e.g. mlb_pa_model"
            />
          )}
        </div>
        <button
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={handleLoad}
          disabled={loading}
        >
          {loading ? "Loading..." : "Load Config"}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {message && (
        <div className={styles.success}>
          {message}
        </div>
      )}

      {data && !loading && (
        <div className={styles.resultsSection}>
          <AdminCard
            title={data.model}
            subtitle={`Sport: ${data.sport} | ${data.enabled_features.length} enabled features`}
          >
            <AdminTable
              headers={["Feature", "Enabled", "Weight"]}
            >
              {Object.entries(data.features).map(([name, cfg]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={cfg.enabled}
                      onChange={() => handleToggle(name)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.1}
                      value={cfg.weight}
                      onChange={(e) =>
                        handleWeightChange(name, parseFloat(e.target.value) || 0)
                      }
                      style={{ width: "5rem" }}
                      disabled={!cfg.enabled}
                    />
                  </td>
                </tr>
              ))}
            </AdminTable>

            <div style={{ marginTop: "1rem" }}>
              <button
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save Configuration"}
              </button>
            </div>
          </AdminCard>
        </div>
      )}
    </div>
  );
}
