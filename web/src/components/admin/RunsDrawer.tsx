"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./RunsDrawer.module.css";
import { cancelJobRun, listJobRuns, type JobRunResponse } from "@/lib/api/sportsAdmin";

type DrawerSize = "collapsed" | "half" | "full";

import {
  ALL_STATUSES,
  AUTO_REFRESH_MS,
  PHASE_OPTIONS,
  STATUS_LABELS,
  formatDate,
  formatDuration,
  formatTime,
  groupConsecutiveRuns,
  phaseLabel,
} from "./RunsDrawerUtils";

const SIZE_CLASS: Record<DrawerSize, string> = {
  collapsed: styles.drawerCollapsed,
  half: styles.drawerHalf,
  full: styles.drawerFull,
};

export function RunsDrawer() {
  const [size, setSize] = useState<DrawerSize>("collapsed");
  const [runs, setRuns] = useState<JobRunResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState("");
  const [selectedStatuses, setSelectedStatuses] = useState<Set<string>>(new Set());
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(new Set());
  const [cancelingIds, setCancelingIds] = useState<Set<number>>(new Set());

  const fetchRuns = useCallback(async () => {
    try {
      setError(null);
      const data = await listJobRuns({
        phase: phase || undefined,
        limit: 100,
      });
      setRuns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [phase]);

  const filteredRuns = selectedStatuses.size === 0
    ? runs
    : runs.filter((r) => selectedStatuses.has(r.status));

  const toggleStatus = (s: string) =>
    setSelectedStatuses((prev) => {
      const next = new Set(prev);
      next.has(s) ? next.delete(s) : next.add(s);
      return next;
    });

  // Fetch when opened or filters change
  useEffect(() => {
    if (size !== "collapsed") {
      setLoading(true);
      fetchRuns();
    }
  }, [fetchRuns, size]);

  // Auto-refresh when open
  useEffect(() => {
    if (size === "collapsed") return;
    const interval = setInterval(fetchRuns, AUTO_REFRESH_MS);
    return () => clearInterval(interval);
  }, [fetchRuns, size]);

  // Keep main content padding in sync with drawer height so content
  // behind the drawer remains scrollable.
  useEffect(() => {
    const heights: Record<DrawerSize, string> = {
      collapsed: "36px",
      half: "50vh",
      full: "calc(100vh - var(--admin-header-height))",
    };
    document.documentElement.style.setProperty(
      "--runs-drawer-height",
      heights[size],
    );
    return () => {
      document.documentElement.style.removeProperty("--runs-drawer-height");
    };
  }, [size]);

  const toggleSize = () => {
    setSize((prev) => (prev === "collapsed" ? "half" : "collapsed"));
  };

  const getStatusClass = (s: string) => {
    switch (s) {
      case "success":
        return styles.statusSuccess;
      case "running":
        return styles.statusRunning;
      case "error":
        return styles.statusError;
      case "canceled":
        return styles.statusCanceled;
      case "queued":
        return styles.statusQueued;
      default:
        return "";
    }
  };

  const handleCancel = async (runId: number) => {
    setCancelingIds((prev) => new Set(prev).add(runId));
    try {
      await cancelJobRun(runId);
      await fetchRuns();
    } catch {
      // errors surface via fetchRuns or are transient
    } finally {
      setCancelingIds((prev) => {
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
    }
  };

  return (
    <div className={`${styles.drawer} ${SIZE_CLASS[size]}`}>
      {/* Tab bar — always visible */}
      <div className={styles.tabBar} onClick={toggleSize}>
        <span className={styles.tabLabel}>
          Runs {size === "collapsed" ? "\u25B2" : "\u25BC"}
        </span>
        <div
          className={styles.tabControls}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className={`${styles.tabBtn} ${size === "half" ? styles.tabBtnActive : ""}`}
            onClick={() => setSize("half")}
            title="Half height"
          >
            &#x2B12;
          </button>
          <button
            className={`${styles.tabBtn} ${size === "full" ? styles.tabBtnActive : ""}`}
            onClick={() => setSize("full")}
            title="Full height"
          >
            &#x2610;
          </button>
          <button
            className={styles.tabBtn}
            onClick={() => setSize("collapsed")}
            title="Collapse"
          >
            &#x2715;
          </button>
        </div>
      </div>

      {/* Body — only rendered when open */}
      {size !== "collapsed" && (
        <>
          <div className={styles.toolbar}>
            <select value={phase} onChange={(e) => setPhase(e.target.value)}>
              {PHASE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <div className={styles.statusChips}>
              {ALL_STATUSES.map((s) => (
                <button
                  key={s}
                  className={`${styles.statusChip} ${selectedStatuses.has(s) ? styles.statusChipActive : ""}`}
                  onClick={() => toggleStatus(s)}
                  type="button"
                >
                  {STATUS_LABELS[s]}
                </button>
              ))}
              {selectedStatuses.size > 0 && (
                <button
                  className={styles.statusChipClear}
                  onClick={() => setSelectedStatuses(new Set())}
                  type="button"
                >
                  Clear
                </button>
              )}
            </div>
            <button
              className={styles.refreshBtn}
              onClick={fetchRuns}
              disabled={loading}
            >
              {loading ? "Loading..." : "Refresh"}
            </button>
            <span className={styles.autoRefreshLabel}>Auto-refresh: 30s</span>
          </div>

          <div className={styles.body}>
            {error && <div className={styles.error}>{error}</div>}

            {!loading && filteredRuns.length === 0 && !error && (
              <div className={styles.empty}>No task runs found.</div>
            )}

            {filteredRuns.length > 0 && (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Phase</th>
                    <th>Leagues</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th>Summary</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {groupConsecutiveRuns(filteredRuns).map((item, idx) => {
                    if (item.kind === "group") {
                      const isExpanded = expandedGroups.has(idx);
                      const first = item.runs[0];
                      const last = item.runs[item.runs.length - 1];
                      return (
                        <>
                          <tr
                            key={`group-${idx}`}
                            className={styles.expandable}
                            onClick={() => {
                              setExpandedGroups((prev) => {
                                const next = new Set(prev);
                                if (next.has(idx)) next.delete(idx);
                                else next.add(idx);
                                return next;
                              });
                            }}
                          >
                            <td>
                              <span className={styles.phaseBadge}>
                                {phaseLabel(item.phase)}
                              </span>
                              <span className={styles.groupCount}>
                                {"\u00D7"}{item.count}
                              </span>
                            </td>
                            <td>-</td>
                            <td>
                              <span
                                className={`${styles.statusPill} ${getStatusClass(item.status)}`}
                              >
                                {item.status}
                              </span>
                            </td>
                            <td>
                              {formatDate(last.startedAt)} {formatTime(last.startedAt)}
                              {" \u2013 "}
                              {formatTime(first.startedAt)}
                            </td>
                            <td className={styles.durationCell}>-</td>
                            <td>{isExpanded ? "Click to collapse" : `${item.count} runs (click to expand)`}</td>
                            <td>-</td>
                          </tr>
                          {isExpanded &&
                            item.runs.map((run) => (
                              <>
                                <tr
                                  key={run.id}
                                  className={`${run.summaryData ? styles.expandable : ""} ${styles.groupedRow}`}
                                  onClick={() => {
                                    if (run.summaryData) {
                                      setExpandedId(
                                        expandedId === run.id ? null : run.id
                                      );
                                    }
                                  }}
                                >
                                  <td>
                                    <span className={styles.phaseBadge}>
                                      {phaseLabel(run.phase)}
                                    </span>
                                  </td>
                                  <td>
                                    {run.leagues.map((lg) => (
                                      <span key={lg} className={styles.leagueBadge}>
                                        {lg}
                                      </span>
                                    ))}
                                  </td>
                                  <td>
                                    <span
                                      className={`${styles.statusPill} ${getStatusClass(run.status)}`}
                                    >
                                      {run.status}
                                    </span>
                                  </td>
                                  <td>
                                    {formatDate(run.startedAt)} {formatTime(run.startedAt)}
                                  </td>
                                  <td className={styles.durationCell}>
                                    {formatDuration(run.durationSeconds)}
                                  </td>
                                  <td>
                                    {run.errorSummary
                                      ? run.errorSummary.slice(0, 60)
                                      : run.summaryData
                                        ? "Click to expand"
                                        : "-"}
                                  </td>
                                  <td>-</td>
                                </tr>
                                {expandedId === run.id && run.summaryData && (
                                  <tr
                                    key={`${run.id}-detail`}
                                    className={styles.summaryRow}
                                  >
                                    <td colSpan={7}>
                                      <pre className={styles.summaryPre}>
                                        {JSON.stringify(run.summaryData, null, 2)}
                                      </pre>
                                    </td>
                                  </tr>
                                )}
                              </>
                            ))}
                        </>
                      );
                    }

                    const run = item.run;
                    return (
                      <>
                        <tr
                          key={run.id}
                          className={
                            run.summaryData ? styles.expandable : undefined
                          }
                          onClick={() => {
                            if (run.summaryData) {
                              setExpandedId(
                                expandedId === run.id ? null : run.id
                              );
                            }
                          }}
                        >
                          <td>
                            <span className={styles.phaseBadge}>
                              {phaseLabel(run.phase)}
                            </span>
                          </td>
                          <td>
                            {run.leagues.map((lg) => (
                              <span key={lg} className={styles.leagueBadge}>
                                {lg}
                              </span>
                            ))}
                          </td>
                          <td>
                            <span
                              className={`${styles.statusPill} ${getStatusClass(run.status)}`}
                            >
                              {run.status}
                            </span>
                          </td>
                          <td>
                            {run.status === "queued"
                              ? `${formatDate(run.createdAt)} ${formatTime(run.createdAt)}`
                              : `${formatDate(run.startedAt)} ${formatTime(run.startedAt)}`}
                          </td>
                          <td className={styles.durationCell}>
                            {formatDuration(run.durationSeconds)}
                          </td>
                          <td>
                            {run.errorSummary
                              ? run.errorSummary.slice(0, 60)
                              : run.summaryData
                                ? "Click to expand"
                                : "-"}
                          </td>
                          <td>
                            {run.status === "running" || run.status === "queued" ? (
                              <button
                                className={styles.cancelBtn}
                                disabled={cancelingIds.has(run.id)}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleCancel(run.id);
                                }}
                              >
                                {cancelingIds.has(run.id) ? "Canceling..." : "Cancel"}
                              </button>
                            ) : (
                              "-"
                            )}
                          </td>
                        </tr>
                        {expandedId === run.id && run.summaryData && (
                          <tr
                            key={`${run.id}-detail`}
                            className={styles.summaryRow}
                          >
                            <td colSpan={7}>
                              <pre className={styles.summaryPre}>
                                {JSON.stringify(run.summaryData, null, 2)}
                              </pre>
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
