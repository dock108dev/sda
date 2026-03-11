"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  listRegisteredModels,
  activateModel,
  compareModels,
  getCalibrationReport,
  type RegisteredModel,
  type ModelComparison,
  type CalibrationReport,
} from "@/lib/api/analytics";
import { LoadoutsPanel } from "../workbench/LoadoutsPanel";
import { TrainingPanel } from "../workbench/TrainingPanel";
import { EnsemblePanel } from "../workbench/EnsemblePanel";
import { CalibrationPanel } from "./CalibrationPanel";
import { DegradationAlertsPanel } from "./DegradationAlertsPanel";
import styles from "../analytics.module.css";

type Tab = "registry" | "loadouts" | "training" | "performance";

export default function ModelsPage() {
  const [tab, setTab] = useState<Tab>("registry");

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Models</h1>
        <p className={styles.pageSubtitle}>
          Full model lifecycle — loadouts, training, registry, and performance
        </p>
      </header>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        {([
          { key: "registry", label: "Registry" },
          { key: "loadouts", label: "Loadouts" },
          { key: "training", label: "Training" },
          { key: "performance", label: "Performance" },
        ] as const).map((t) => (
          <button
            key={t.key}
            className={`${styles.btn} ${tab === t.key ? styles.btnPrimary : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "registry" && <RegistryPanel />}
      {tab === "loadouts" && <LoadoutsPanel />}
      {tab === "training" && <TrainingSection />}
      {tab === "performance" && <PerformanceSection />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Training Section — TrainingPanel + EnsemblePanel                  */
/* ------------------------------------------------------------------ */

function TrainingSection() {
  return (
    <>
      <TrainingPanel />
      <div style={{ marginTop: "1.5rem" }}>
        <EnsemblePanel />
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Registry Panel                                                    */
/* ------------------------------------------------------------------ */

type SortKey = "version" | "accuracy" | "log_loss" | "brier_score" | "created_at";

function RegistryPanel() {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);

  // Filters
  const [sportFilter, setSportFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);

  // Sorting
  const [sortBy, setSortBy] = useState<SortKey>("version");
  const [sortDesc, setSortDesc] = useState(true);

  // Comparison
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comparison, setComparison] = useState<ModelComparison | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listRegisteredModels(
        sportFilter || undefined,
        typeFilter || undefined,
      );
      setModels(res.models);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sportFilter, typeFilter]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleActivate(m: RegisteredModel) {
    setActivating(m.model_id);
    try {
      const res = await activateModel(m.sport, m.model_type, m.model_id);
      if (res.status === "error") {
        setError(res.message || "Activation failed");
      } else {
        await load();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActivating(null);
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setComparison(null);
  }

  async function handleCompare() {
    const ids = Array.from(selected);
    if (ids.length < 2) return;
    const first = models.find((m) => m.model_id === ids[0]);
    if (!first) return;
    try {
      const res = await compareModels(first.sport, first.model_type, ids);
      setComparison(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  // Apply client-side filtering and sorting
  let filtered = activeOnly ? models.filter((m) => m.active) : models;
  filtered = [...filtered].sort((a, b) => {
    let va: number | string;
    let vb: number | string;
    if (sortBy === "version" || sortBy === "created_at") {
      va = a[sortBy] ?? "";
      vb = b[sortBy] ?? "";
    } else {
      va = a.metrics?.[sortBy] ?? (sortDesc ? -Infinity : Infinity);
      vb = b.metrics?.[sortBy] ?? (sortDesc ? -Infinity : Infinity);
    }
    if (va < vb) return sortDesc ? 1 : -1;
    if (va > vb) return sortDesc ? -1 : 1;
    return 0;
  });

  // Group by sport / model_type
  const grouped = filtered.reduce<Record<string, RegisteredModel[]>>((acc, m) => {
    const key = `${m.sport} / ${m.model_type}`;
    if (!acc[key]) acc[key] = [];
    acc[key].push(m);
    return acc;
  }, {});

  const sports = [...new Set(models.map((m) => m.sport))];
  const types = [...new Set(models.map((m) => m.model_type))];

  function sortHeader(label: string, key: SortKey) {
    const active = sortBy === key;
    return (
      <span
        style={{ cursor: "pointer", textDecoration: active ? "underline" : "none" }}
        onClick={() => {
          if (active) setSortDesc(!sortDesc);
          else { setSortBy(key); setSortDesc(true); }
        }}
      >
        {label}{active ? (sortDesc ? " \u25BC" : " \u25B2") : ""}
      </span>
    );
  }

  return (
    <>
      {/* Filters */}
      <div className={styles.formRow} style={{ marginBottom: "1rem" }}>
        <div className={styles.formGroup}>
          <label>Sport</label>
          <select value={sportFilter} onChange={(e) => setSportFilter(e.target.value)}>
            <option value="">All</option>
            {sports.map((s) => <option key={s} value={s}>{s.toUpperCase()}</option>)}
          </select>
        </div>
        <div className={styles.formGroup}>
          <label>Model Type</label>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">All</option>
            {types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
          Active only
        </label>
        {selected.size >= 2 && (
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleCompare}>
            Compare ({selected.size})
          </button>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {loading && <p>Loading models...</p>}

      {!loading && filtered.length === 0 && (
        <AdminCard title="No Models Found">
          <p>Train a model using the training pipeline to see it here.</p>
        </AdminCard>
      )}

      {Object.entries(grouped).map(([group, groupModels]) => {
        const activeModel = groupModels.find((m) => m.active);
        return (
          <AdminCard
            key={group}
            title={group.toUpperCase()}
            subtitle={`${groupModels.length} version(s)${activeModel ? ` — Active: ${activeModel.model_id}` : ""}`}
          >
            <AdminTable
              headers={[
                "",
                "Model ID",
                sortHeader("Version", "version"),
                sortHeader("Accuracy", "accuracy"),
                sortHeader("Log Loss", "log_loss"),
                sortHeader("Brier Score", "brier_score"),
                sortHeader("Created", "created_at"),
                "Status",
                "",
              ]}
            >
              {groupModels.map((m) => (
                <tr key={m.model_id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(m.model_id)}
                      onChange={() => toggleSelect(m.model_id)}
                    />
                  </td>
                  <td>
                    <Link
                      href={`/admin/analytics/models/${encodeURIComponent(m.model_id)}`}
                      style={{ textDecoration: "underline" }}
                    >
                      {m.model_id}
                    </Link>
                  </td>
                  <td>v{m.version}</td>
                  <td>{m.metrics?.accuracy != null ? m.metrics.accuracy.toFixed(3) : "-"}</td>
                  <td>{m.metrics?.log_loss != null ? m.metrics.log_loss.toFixed(3) : "-"}</td>
                  <td>{m.metrics?.brier_score != null ? m.metrics.brier_score.toFixed(3) : "-"}</td>
                  <td>{m.created_at ? new Date(m.created_at).toLocaleDateString() : "-"}</td>
                  <td>
                    {m.active ? (
                      <span style={{ background: "#22c55e", color: "#fff", padding: "2px 8px", borderRadius: "4px", fontSize: "0.8rem" }}>
                        Active
                      </span>
                    ) : ""}
                  </td>
                  <td>
                    {!m.active && (
                      <button
                        className={`${styles.btn} ${styles.btnPrimary}`}
                        onClick={() => handleActivate(m)}
                        disabled={activating === m.model_id}
                        style={{ fontSize: "0.8rem", padding: "4px 8px" }}
                      >
                        {activating === m.model_id ? "..." : "Activate"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </AdminTable>
          </AdminCard>
        );
      })}

      {/* Comparison Section */}
      {comparison && comparison.models.length >= 2 && (
        <AdminCard title="Model Comparison" subtitle={`${comparison.sport.toUpperCase()} / ${comparison.model_type}`}>
          <AdminTable
            headers={["Metric", ...comparison.models.map((m) => m.model_id)]}
          >
            {(() => {
              const metricKeys = new Set<string>();
              comparison.models.forEach((m) => {
                Object.keys(m.metrics).forEach((k) => {
                  if (typeof m.metrics[k] === "number") metricKeys.add(k);
                });
              });
              const better = comparison.comparison?.better_model;
              return Array.from(metricKeys).map((key) => (
                <tr key={key}>
                  <td>{key}</td>
                  {comparison.models.map((m) => {
                    const val = m.metrics[key];
                    const isBetter = better === m.model_id;
                    return (
                      <td key={m.model_id} style={isBetter ? { fontWeight: "bold" } : {}}>
                        {val != null ? (typeof val === "number" ? val.toFixed(4) : String(val)) : "-"}
                      </td>
                    );
                  })}
                </tr>
              ));
            })()}
          </AdminTable>
          {comparison.comparison && (
            <p style={{ marginTop: "0.5rem", fontSize: "0.9rem" }}>
              Better model: <strong>{comparison.comparison.better_model}</strong>
            </p>
          )}
        </AdminCard>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Performance Section — calibration + degradation alerts            */
/* ------------------------------------------------------------------ */

function PerformanceSection() {
  const [sport, setSport] = useState<string>("");
  const [data, setData] = useState<CalibrationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLoad = useCallback(() => {
    setLoading(true);
    setError(null);
    getCalibrationReport(sport || undefined)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [sport]);

  return (
    <>
      <div className={styles.formRow} style={{ marginBottom: "1rem" }}>
        <div className={styles.formGroup}>
          <label>Sport</label>
          <select value={sport} onChange={(e) => setSport(e.target.value)}>
            <option value="">All Sports</option>
            <option value="mlb">MLB</option>
          </select>
        </div>
        <button
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={handleLoad}
          disabled={loading}
        >
          {loading ? "Loading..." : "Load Metrics"}
        </button>
      </div>

      {loading && <div className={styles.loading}>Loading metrics...</div>}
      {error && <div className={styles.error}>{error}</div>}

      {data && !loading && (
        <div className={styles.resultsSection}>
          <AdminCard
            title="Overview"
            subtitle={`Based on ${data.total_predictions} resolved predictions`}
          >
            {data.total_predictions === 0 ? (
              <p style={{ color: "var(--text-muted)" }}>
                No resolved predictions yet. Run a batch simulation, then record outcomes after games finish.
              </p>
            ) : (
              <>
                <div className={styles.statsRow}>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.total_predictions}</div>
                    <div className={styles.statLabel}>Resolved</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{(data.accuracy * 100).toFixed(1)}%</div>
                    <div className={styles.statLabel}>Winner Accuracy</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.brier_score.toFixed(4)}</div>
                    <div className={styles.statLabel}>Brier Score</div>
                  </div>
                </div>
                <div className={styles.statsRow}>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.avg_home_score_error.toFixed(1)}</div>
                    <div className={styles.statLabel}>Avg Home Score Error</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>{data.avg_away_score_error.toFixed(1)}</div>
                    <div className={styles.statLabel}>Avg Away Score Error</div>
                  </div>
                  <div className={styles.statBox}>
                    <div className={styles.statValue}>
                      {data.home_bias > 0 ? "+" : ""}{(data.home_bias * 100).toFixed(1)}%
                    </div>
                    <div className={styles.statLabel}>Home Win Bias</div>
                  </div>
                </div>
              </>
            )}
          </AdminCard>
        </div>
      )}

      <DegradationAlertsPanel sport={sport || undefined} />
      <CalibrationPanel sport={sport || undefined} />
    </>
  );
}
