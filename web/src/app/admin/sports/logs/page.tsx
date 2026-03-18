"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchDockerLogs } from "@/lib/api/sportsAdmin";
import styles from "./page.module.css";

const CONTAINERS = [
  { label: "API", container: "sports-api" },
  { label: "Scraper", container: "sports-scraper" },
  { label: "Social Scraper", container: "sports-social-scraper" },
  { label: "API Worker", container: "sports-api-worker" },
  { label: "Training Worker", container: "sports-api-training-worker" },
];

const LINE_COUNTS = [500, 1000, 5000];
const AUTO_REFRESH_INTERVAL = 10_000;

function classifyLine(line: string): "error" | "warning" | null {
  const upper = line.toUpperCase();
  if (upper.includes("ERROR") || upper.includes("CRITICAL") || upper.includes("FATAL")) {
    return "error";
  }
  if (upper.includes("WARNING") || upper.includes("WARN")) {
    return "warning";
  }
  return null;
}

export default function LogsPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [lineCount, setLineCount] = useState(1000);
  const [logs, setLogs] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const logAreaRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const loadLogs = useCallback(async (tabIndex: number, lines: number) => {
    const tab = CONTAINERS[tabIndex];
    setLoading(true);
    setError(null);
    try {
      const result = await fetchDockerLogs(tab.container, lines);
      setLogs(result.logs);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setLogs("");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load logs on mount and when tab/lineCount changes
  useEffect(() => {
    loadLogs(activeTab, lineCount);
  }, [activeTab, lineCount, loadLogs]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (logAreaRef.current) {
      logAreaRef.current.scrollTop = logAreaRef.current.scrollHeight;
    }
  }, [logs]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        loadLogs(activeTab, lineCount);
      }, AUTO_REFRESH_INTERVAL);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [autoRefresh, activeTab, lineCount, loadLogs]);

  // Filter lines by search query
  const filteredLines = useMemo(() => {
    if (!logs) return [];
    const allLines = logs.split("\n");
    if (!searchQuery.trim()) return allLines;
    const q = searchQuery.toLowerCase();
    return allLines.filter((line) => line.toLowerCase().includes(q));
  }, [logs, searchQuery]);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>Logs</h1>
      </div>

      <div className={styles.tabs}>
        {CONTAINERS.map((c, i) => (
          <button
            key={c.container}
            className={`${styles.tab} ${i === activeTab ? styles.tabActive : ""}`}
            onClick={() => setActiveTab(i)}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div className={styles.searchRow}>
        <input
          type="text"
          className={styles.searchInput}
          placeholder="Filter logs..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <select
          className={styles.select}
          value={lineCount}
          onChange={(e) => setLineCount(Number(e.target.value))}
        >
          {LINE_COUNTS.map((n) => (
            <option key={n} value={n}>
              {n} lines
            </option>
          ))}
        </select>
        <label className={styles.autoRefreshLabel}>
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          Auto-refresh
        </label>
        <button
          className={styles.refreshButton}
          onClick={() => loadLogs(activeTab, lineCount)}
          disabled={loading}
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {loading && !logs ? (
        <div className={styles.loading}>Loading logs...</div>
      ) : error ? (
        <div className={styles.errorMessage}>{error}</div>
      ) : (
        <div className={styles.logArea} ref={logAreaRef}>
          <pre className={styles.logContent}>
            {filteredLines.map((line, i) => {
              const cls = classifyLine(line);
              const lineClass = cls === "error"
                ? styles.lineError
                : cls === "warning"
                  ? styles.lineWarning
                  : undefined;
              return (
                <span key={i} className={lineClass}>
                  {line}
                  {"\n"}
                </span>
              );
            })}
            {filteredLines.length === 0 && "No logs available."}
          </pre>
        </div>
      )}

      <div className={styles.footer}>
        <span>
          Showing {filteredLines.length} lines from <strong>{CONTAINERS[activeTab].container}</strong>
          {searchQuery && ` (filtered from ${logs.split("\n").length})`}
        </span>
        {autoRefresh && <span>Auto-refreshing every 10s</span>}
      </div>
    </div>
  );
}
