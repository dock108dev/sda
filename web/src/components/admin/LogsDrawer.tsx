"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./LogsDrawer.module.css";
import { fetchDockerLogs } from "@/lib/api/sportsAdmin";

export type LogsTab = {
  label: string;
  container: string;
};

const DEFAULT_TABS: LogsTab[] = [
  { label: "API", container: "sports-api" },
  { label: "Scraper", container: "sports-scraper" },
  { label: "Social Scraper", container: "sports-social-scraper" },
  { label: "API Worker", container: "sports-api-worker" },
  { label: "Training Worker", container: "sports-api-training-worker" },
];

const DEFAULT_WIDTH = 50; // percent of viewport
const MIN_WIDTH = 25;
const MAX_WIDTH = 85;

type LogsDrawerProps = {
  open: boolean;
  onClose: () => void;
  tabs?: LogsTab[];
};

export function LogsDrawer({ open, onClose, tabs = DEFAULT_TABS }: LogsDrawerProps) {
  const [activeTab, setActiveTab] = useState(0);
  const [logs, setLogs] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logAreaRef = useRef<HTMLDivElement>(null);

  // Resizable width (persisted in state, percentage of viewport)
  const [widthPct, setWidthPct] = useState(DEFAULT_WIDTH);
  const [dragging, setDragging] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const loadLogs = useCallback(async (tabIndex: number) => {
    const tab = tabs[tabIndex];
    setLoading(true);
    setError(null);
    try {
      const result = await fetchDockerLogs(tab.container);
      setLogs(result.logs);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setLogs("");
    } finally {
      setLoading(false);
    }
  }, [tabs]);

  useEffect(() => {
    if (open) {
      loadLogs(activeTab);
    }
  }, [open, activeTab, loadLogs]);

  // Auto-scroll to bottom when logs change
  useEffect(() => {
    if (logAreaRef.current) {
      logAreaRef.current.scrollTop = logAreaRef.current.scrollHeight;
    }
  }, [logs]);

  // Drag-to-resize handling
  useEffect(() => {
    if (!dragging) return;

    const onMouseMove = (e: MouseEvent) => {
      const pct = ((window.innerWidth - e.clientX) / window.innerWidth) * 100;
      setWidthPct(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, pct)));
    };

    const onMouseUp = () => setDragging(false);

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [dragging]);

  const handleTabClick = (index: number) => {
    setActiveTab(index);
  };

  const handleRefresh = () => {
    loadLogs(activeTab);
  };

  return (
    <>
      <div
        className={`${styles.backdrop} ${open ? styles.backdropOpen : ""}`}
        onClick={onClose}
      />
      <div
        ref={panelRef}
        className={`${styles.panel} ${open ? styles.panelOpen : ""}`}
        style={{ width: `${widthPct}vw` }}
      >
        {/* Drag handle on left edge */}
        <div
          className={`${styles.resizeHandle} ${dragging ? styles.resizeHandleActive : ""}`}
          onMouseDown={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
        />

        <div className={styles.header}>
          <h2>Container Logs</h2>
          <div className={styles.headerActions}>
            <button
              className={styles.refreshButton}
              onClick={handleRefresh}
              disabled={loading}
            >
              {loading ? "Loading..." : "Refresh"}
            </button>
            <button className={styles.closeButton} onClick={onClose}>
              ✕
            </button>
          </div>
        </div>

        <div className={styles.tabs}>
          {tabs.map((tab, i) => (
            <button
              key={tab.container}
              className={`${styles.tab} ${i === activeTab ? styles.tabActive : ""}`}
              onClick={() => handleTabClick(i)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className={styles.loading}>Loading logs...</div>
        ) : error ? (
          <div className={styles.errorMessage}>{error}</div>
        ) : (
          <div className={styles.logArea} ref={logAreaRef}>
            <pre className={styles.logContent}>{logs || "No logs available."}</pre>
          </div>
        )}

        <div className={styles.footer}>
          Showing last 1000 lines from <strong>{tabs[activeTab].container}</strong>
        </div>
      </div>
    </>
  );
}
