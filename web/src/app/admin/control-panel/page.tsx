"use client";

import { useState, useEffect, useCallback } from "react";
import styles from "./styles.module.css";
import {
  createScrapeRun,
  createBulkBackfill,
  previewBulkBackfill,
  getHoldStatus,
  setHoldStatus,
} from "@/lib/api/sportsAdmin/taskControl";
import type { BulkBackfillChunk } from "@/lib/api/sportsAdmin/taskControl";
import {
  LEAGUE_OPTIONS,
  TASK_REGISTRY,
  CATEGORIES,
} from "./taskRegistry";
import { CircuitBreakerPanel } from "@/components/admin/CircuitBreakerPanel";
import { CoverageReportPanel } from "@/components/admin/CoverageReportPanel";

import { ChipToggle, GameflowCard, TaskCard } from "./ControlPanelParts";

// ── Data Backfill card ──

const DATA_TYPES = ["Boxscores", "Odds", "PBP", "Social", "Advanced Stats"] as const;

function DataBackfillCard() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [leagues, setLeagues] = useState<Set<string>>(() => new Set());
  const [dataTypes, setDataTypes] = useState<Set<string>>(() => new Set());
  const [forceAll, setForceAll] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [preview, setPreview] = useState<{ totalChunks: number; chunks: BulkBackfillChunk[] } | null>(null);
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
      setResult({ dispatched: res.chunksDispatched, total: res.totalChunks });
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
          acc[c.leagueCode] = (acc[c.leagueCode] || 0) + 1;
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
            {preview.totalChunks} monthly chunks:{" "}
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

// ── Main page ──

export default function ControlPanelPage() {
  const [held, setHeld] = useState(false);
  const [holdError, setHoldError] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    getHoldStatus()
      .then((s) => { setHeld(s.held); setHoldError(false); })
      .catch((err) => {
        // The UI only renders a generic "unknown" banner, but we want the
        // underlying status / network error in browser logs for triage.
        // See docs/audits/error-handling-report.md AH-15/AH-21.
        console.error("[control-panel] getHoldStatus failed", err);
        setHoldError(true);
      });
  }, []);

  const toggleHold = useCallback(async () => {
    setToggling(true);
    try {
      const res = await setHoldStatus(!held);
      setHeld(res.held);
      setHoldError(false);
    } catch (err) {
      console.error("[control-panel] setHoldStatus failed", err);
      setHoldError(true);
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

      <CircuitBreakerPanel />
      <CoverageReportPanel />

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
