"use client";

import { useState, useEffect, useCallback } from "react";
import styles from "./styles.module.css";
import {
  triggerTask,
  createScrapeRun,
  createBulkBackfill,
  previewBulkBackfill,
  triggerBulkFlowGeneration,
  getHoldStatus,
  setHoldStatus,
} from "@/lib/api/sportsAdmin/taskControl";
import type { BulkBackfillChunk } from "@/lib/api/sportsAdmin/taskControl";
import {
  type TaskDef,
  LEAGUE_OPTIONS,
  TASK_REGISTRY,
  CATEGORIES,
} from "./taskRegistry";

// ── TaskCard component ──

function TaskCard({ task }: { task: TaskDef }) {
  const [paramValues, setParamValues] = useState<Record<string, string>>(() => {
    const defaults: Record<string, string> = {};
    for (const p of task.params) {
      if (p.default !== undefined) {
        defaults[p.name] = String(p.default);
      } else if (p.required && p.type === "select" && p.options?.length) {
        defaults[p.name] = p.options[0];
      } else {
        defaults[p.name] = "";
      }
    }
    return defaults;
  });
  const [dispatching, setDispatching] = useState(false);
  const [result, setResult] = useState<
    { taskId: string } | { error: string } | null
  >(null);

  const canRun = task.params
    .filter((p) => p.required)
    .every((p) => paramValues[p.name]?.trim());

  const handleRun = async () => {
    setDispatching(true);
    setResult(null);
    try {
      const args: unknown[] = [];
      for (const p of task.params) {
        const val = paramValues[p.name]?.trim();
        if (val) {
          args.push(p.type === "number" ? Number(val) : val);  // "text" and "select" pass as strings
        } else if (p.required) {
          return;
        } else {
          args.push(null);
        }
      }
      const res = await triggerTask(task.name, args);
      setResult({ taskId: res.task_id });
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Dispatch failed";
      setResult({ error: msg });
    } finally {
      setDispatching(false);
    }
  };

  return (
    <div className={styles.taskCard}>
      <div className={styles.taskHeader}>
        <span className={styles.taskName}>{task.label}</span>
        <span
          className={`${styles.queueBadge} ${
            task.queue === "sports-scraper"
              ? styles.queueSports
              : styles.queueSocial
          }`}
        >
          {task.queue === "sports-scraper" ? "sports" : "social"}
        </span>
      </div>
      <div className={styles.taskDescription}>{task.description}</div>

      {task.params.length > 0 && (
        <div className={styles.paramsRow}>
          {task.params.map((p) => (
            <div key={p.name} className={styles.paramGroup}>
              <label className={styles.paramLabel}>
                {p.name}
                {p.required ? "" : " (opt)"}
              </label>
              {p.type === "select" && p.options ? (
                <select
                  className={styles.paramInput}
                  value={paramValues[p.name] ?? ""}
                  onChange={(e) =>
                    setParamValues((prev) => ({
                      ...prev,
                      [p.name]: e.target.value,
                    }))
                  }
                >
                  {!p.required && <option value="">All</option>}
                  {p.options.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={p.type === "text" ? "text" : "number"}
                  className={styles.paramInput}
                  placeholder={p.default !== undefined ? String(p.default) : ""}
                  value={paramValues[p.name] ?? ""}
                  onChange={(e) =>
                    setParamValues((prev) => ({
                      ...prev,
                      [p.name]: e.target.value,
                    }))
                  }
                />
              )}
            </div>
          ))}
        </div>
      )}

      <div className={styles.taskFooter}>
        <button
          className={styles.runButton}
          disabled={!canRun || dispatching}
          onClick={handleRun}
        >
          {dispatching ? "Dispatching..." : "Run"}
        </button>
        {result && "taskId" in result && (
          <span className={styles.dispatchedMsg}>
            Dispatched{" "}
            <span className={styles.dispatchedTaskId}>{result.taskId}</span>
          </span>
        )}
        {result && "error" in result && (
          <span className={styles.errorMsg}>{result.error}</span>
        )}
      </div>
    </div>
  );
}

// ── Chip toggle helper ──

function ChipToggle({
  items,
  selected,
  onToggle,
}: {
  items: string[];
  selected: Set<string>;
  onToggle: (item: string) => void;
}) {
  return (
    <div className={styles.chipGroup}>
      {items.map((item) => (
        <button
          key={item}
          type="button"
          className={selected.has(item) ? styles.chipActive : styles.chip}
          onClick={() => onToggle(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}

// ── Data Backfill card ──

const DATA_TYPES = ["Boxscores", "Odds", "PBP", "Social", "Advanced Stats"] as const;

function DataBackfillCard() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [leagues, setLeagues] = useState<Set<string>>(() => new Set());
  const [dataTypes, setDataTypes] = useState<Set<string>>(() => new Set());
  const [forceAll, setForceAll] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [preview, setPreview] = useState<{ total_chunks: number; chunks: BulkBackfillChunk[] } | null>(null);
  const [result, setResult] = useState<{ dispatched: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggleLeague = (l: string) =>
    setLeagues((prev) => {
      const next = new Set(prev);
      next.has(l) ? next.delete(l) : next.add(l);
      return next;
    });

  const toggleDataType = (dt: string) =>
    setDataTypes((prev) => {
      const next = new Set(prev);
      next.has(dt) ? next.delete(dt) : next.add(dt);
      return next;
    });

  const canRun =
    startDate && endDate && leagues.size > 0 && dataTypes.size > 0;

  const buildParams = () => ({
    leagues: Array.from(leagues),
    startDate,
    endDate,
    boxscores: dataTypes.has("Boxscores"),
    odds: dataTypes.has("Odds"),
    pbp: dataTypes.has("PBP"),
    social: dataTypes.has("Social"),
    advancedStats: dataTypes.has("Advanced Stats"),
    onlyMissing: !forceAll,
  });

  const handlePreview = async () => {
    setError(null);
    setResult(null);
    try {
      const p = await previewBulkBackfill(buildParams());
      setPreview(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    }
  };

  const handleRun = async () => {
    setDispatching(true);
    setError(null);
    setPreview(null);
    setResult(null);
    try {
      const res = await createBulkBackfill(buildParams());
      setResult({ dispatched: res.chunks_dispatched, total: res.total_chunks });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setDispatching(false);
    }
  };

  // Summarize preview chunks by league
  const previewSummary = preview
    ? Object.entries(
        preview.chunks.reduce<Record<string, number>>((acc, c) => {
          acc[c.league_code] = (acc[c.league_code] || 0) + 1;
          return acc;
        }, {})
      )
    : null;

  return (
    <div className={styles.backfillCard}>
      <div className={styles.taskHeader}>
        <span className={styles.taskName}>Data Backfill</span>
      </div>
      <div className={styles.taskDescription}>
        Season-aware backfill — automatically chunks by month, skips off-season.
      </div>

      <div className={styles.dateRow}>
        <div className={styles.paramGroup}>
          <label className={styles.paramLabel}>Start Date</label>
          <input
            type="date"
            className={styles.paramInput}
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setPreview(null); }}
          />
        </div>
        <div className={styles.paramGroup}>
          <label className={styles.paramLabel}>End Date</label>
          <input
            type="date"
            className={styles.paramInput}
            value={endDate}
            onChange={(e) => { setEndDate(e.target.value); setPreview(null); }}
          />
        </div>
      </div>

      <div className={styles.paramGroup}>
        <label className={styles.paramLabel}>Leagues</label>
        <ChipToggle
          items={LEAGUE_OPTIONS}
          selected={leagues}
          onToggle={(l) => { toggleLeague(l); setPreview(null); }}
        />
      </div>

      <div className={styles.paramGroup}>
        <label className={styles.paramLabel}>Data Types</label>
        <ChipToggle
          items={[...DATA_TYPES]}
          selected={dataTypes}
          onToggle={toggleDataType}
        />
      </div>

      <div className={styles.taskFooter}>
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.8rem", color: "#64748b", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={forceAll}
            onChange={(e) => setForceAll(e.target.checked)}
          />
          Force re-upsert all games (skip nothing)
        </label>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            className={styles.runButton}
            style={{ background: "#64748b" }}
            disabled={!canRun}
            onClick={handlePreview}
          >
            Preview
          </button>
          <button
            className={styles.runButton}
            disabled={!canRun || dispatching}
            onClick={handleRun}
          >
            {dispatching ? "Dispatching..." : "Run Backfill"}
          </button>
        </div>
      </div>

      {preview && previewSummary && (
        <div className={styles.resultList}>
          <span className={styles.dispatchedMsg}>
            {preview.total_chunks} monthly chunks:{" "}
            {previewSummary.map(([lc, n]) => `${lc} (${n})`).join(", ")}
          </span>
        </div>
      )}

      {result && (
        <div className={styles.resultList}>
          <span className={styles.dispatchedMsg}>
            Dispatched {result.dispatched}/{result.total} chunks — check Runs Drawer for progress
          </span>
        </div>
      )}

      {error && (
        <div className={styles.resultList}>
          <span className={styles.errorMsg}>{error}</span>
        </div>
      )}
    </div>
  );
}

// ── Gameflow Generation card ──

function GameflowCard() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [leagues, setLeagues] = useState<Set<string>>(
    () => new Set(LEAGUE_OPTIONS)
  );
  const [force, setForce] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [result, setResult] = useState<
    { jobId: string } | { error: string } | null
  >(null);

  const toggleLeague = (l: string) =>
    setLeagues((prev) => {
      const next = new Set(prev);
      next.has(l) ? next.delete(l) : next.add(l);
      return next;
    });

  const canRun = startDate && endDate && leagues.size > 0;

  const handleRun = async () => {
    setDispatching(true);
    setResult(null);
    try {
      const res = await triggerBulkFlowGeneration({
        start_date: startDate,
        end_date: endDate,
        leagues: Array.from(leagues),
        force,
      });
      setResult({ jobId: res.job_id });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed";
      setResult({ error: msg });
    } finally {
      setDispatching(false);
    }
  };

  return (
    <div className={styles.backfillCard}>
      <div className={styles.taskHeader}>
        <span className={styles.taskName}>Gameflow Generation</span>
      </div>
      <div className={styles.taskDescription}>
        Trigger bulk gameflow generation for selected leagues over a date range.
      </div>

      <div className={styles.dateRow}>
        <div className={styles.paramGroup}>
          <label className={styles.paramLabel}>Start Date</label>
          <input
            type="date"
            className={styles.paramInput}
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <div className={styles.paramGroup}>
          <label className={styles.paramLabel}>End Date</label>
          <input
            type="date"
            className={styles.paramInput}
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
      </div>

      <div className={styles.paramGroup}>
        <label className={styles.paramLabel}>Leagues</label>
        <ChipToggle
          items={LEAGUE_OPTIONS}
          selected={leagues}
          onToggle={toggleLeague}
        />
      </div>

      <div className={styles.checkboxRow}>
        <input
          type="checkbox"
          id="forceRegenerate"
          checked={force}
          onChange={(e) => setForce(e.target.checked)}
        />
        <label htmlFor="forceRegenerate">Force Regenerate</label>
      </div>

      <div className={styles.taskFooter}>
        <button
          className={styles.runButton}
          disabled={!canRun || dispatching}
          onClick={handleRun}
        >
          {dispatching ? "Dispatching..." : "Run Flows"}
        </button>
        {result && "jobId" in result && (
          <span className={styles.dispatchedMsg}>
            Dispatched{" "}
            <span className={styles.dispatchedTaskId}>{result.jobId}</span>
          </span>
        )}
        {result && "error" in result && (
          <span className={styles.errorMsg}>{result.error}</span>
        )}
      </div>
    </div>
  );
}

// ── Main page ──

export default function ControlPanelPage() {
  const [held, setHeld] = useState(false);
  const [holdError, setHoldError] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    getHoldStatus()
      .then((s) => { setHeld(s.held); setHoldError(false); })
      .catch(() => setHoldError(true));
  }, []);

  const toggleHold = useCallback(async () => {
    setToggling(true);
    try {
      const res = await setHoldStatus(!held);
      setHeld(res.held);
    } catch {
      // ignore
    } finally {
      setToggling(false);
    }
  }, [held]);

  return (
    <div className={styles.container}>
      <h1>Control Panel</h1>
      <p className={styles.subtitle}>
        Trigger Celery tasks on-demand. Open the Runs drawer at the bottom to
        monitor job history.
      </p>

      <div className={held ? styles.holdBannerActive : styles.holdBanner}>
        <div className={styles.holdBannerContent}>
          <span className={styles.holdBannerText}>
            {holdError
              ? "Scheduler hold status unknown — could not reach server."
              : held
              ? "Schedulers are HELD — beat tasks will be skipped. Manual triggers still work."
              : "Schedulers are active."}
          </span>
          <button
            className={held ? styles.holdButtonRelease : styles.holdButtonHold}
            disabled={toggling}
            onClick={toggleHold}
          >
            {toggling
              ? "..."
              : held
                ? "Release Hold"
                : "Hold All Tasks"}
          </button>
        </div>
      </div>

      <div className={styles.categoryGroup}>
        <h2 className={styles.categoryTitle}>Backfill</h2>
        <div className={styles.backfillGrid}>
          <DataBackfillCard />
          <GameflowCard />
        </div>
      </div>

      {CATEGORIES.map((cat) => (
        <div key={cat} className={styles.categoryGroup}>
          <h2 className={styles.categoryTitle}>{cat}</h2>
          <div className={styles.taskGrid}>
            {TASK_REGISTRY.filter((t) => t.category === cat).map((task) => (
              <TaskCard key={task.name} task={task} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
