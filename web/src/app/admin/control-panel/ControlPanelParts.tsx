"use client";

import { useState } from "react";

import { triggerBulkFlowGeneration, triggerTask } from "@/lib/api/sportsAdmin/taskControl";

import styles from "./styles.module.css";
import { LEAGUE_OPTIONS, type TaskDef } from "./taskRegistry";

// ── TaskCard component ──

export function TaskCard({ task }: { task: TaskDef }) {
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
      setResult({ taskId: res.taskId });
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

export function ChipToggle({
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

// ── Gameflow Generation card ──

export function GameflowCard() {
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
