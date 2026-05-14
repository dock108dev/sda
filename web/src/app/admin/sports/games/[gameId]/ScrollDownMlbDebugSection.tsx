"use client";

import { useMemo, useState } from "react";
import {
  fetchScrollDownMlbDebug,
  type ScrollDownMlbDebugFinding,
  type ScrollDownMlbDebugResponse,
} from "@/lib/api/sportsAdmin";
import styles from "./styles.module.css";

function statusColor(status: "ok" | "warning" | "error" | "available" | "not_available" | "blocked") {
  if (status === "ok" || status === "available") return "#166534";
  if (status === "warning" || status === "not_available") return "#92400e";
  return "#991b1b";
}

function FindingTable({ findings }: { findings: ScrollDownMlbDebugFinding[] }) {
  if (findings.length === 0) {
    return <div className={styles.subtle}>No findings.</div>;
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className={styles.table} style={{ fontSize: "0.85rem" }}>
        <thead>
          <tr>
            <th>Severity</th>
            <th>Code</th>
            <th>Scope</th>
            <th>Play</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding, idx) => (
            <tr key={`${finding.code}-${finding.scope ?? "deck"}-${finding.playId ?? idx}`}>
              <td style={{ color: statusColor(finding.severity === "info" ? "ok" : finding.severity), fontWeight: 700 }}>
                {finding.severity}
              </td>
              <td>{finding.code}</td>
              <td>{finding.scope ?? "—"}</td>
              <td>{finding.playId ?? "—"}</td>
              <td>{finding.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ScrollDownMlbDebugSection({ gameId }: { gameId: number }) {
  const [debug, setDebug] = useState<ScrollDownMlbDebugResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const allFindings = useMemo(
    () => [...(debug?.errors ?? []), ...(debug?.warnings ?? [])],
    [debug],
  );
  const deckJson = useMemo(
    () => (debug?.deck ? JSON.stringify(debug.deck, null, 2) : ""),
    [debug],
  );

  const load = async () => {
    setLoading(true);
    setError(null);
    setCopyStatus(null);
    try {
      setDebug(await fetchScrollDownMlbDebug(gameId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Scroll Down debug data");
    } finally {
      setLoading(false);
    }
  };

  const copyDeckJson = async () => {
    if (!deckJson) return;
    try {
      await navigator.clipboard.writeText(deckJson);
      setCopyStatus("Copied deck JSON");
    } catch {
      setCopyStatus("Copy failed");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          style={{ padding: "0.55rem 0.9rem", borderRadius: 8, border: "1px solid #2563eb", background: "#2563eb", color: "#fff", fontWeight: 600 }}
        >
          {loading ? "Loading..." : debug ? "Reload Scroll Down debug" : "Load Scroll Down debug"}
        </button>
        {debug?.deck && (
          <button
            type="button"
            onClick={copyDeckJson}
            style={{ padding: "0.55rem 0.9rem", borderRadius: 8, border: "1px solid #cbd5e1", background: "#fff" }}
          >
            Copy deck JSON
          </button>
        )}
        {copyStatus && <span className={styles.subtle}>{copyStatus}</span>}
      </div>

      {error && <div style={{ color: "#991b1b" }}>Error: {error}</div>}

      {debug && (
        <>
          <div className={styles.teamStatsGrid}>
            <div className={styles.teamStatsCard}>
              <div className={styles.teamStatsHeader}>
                <h3>Status</h3>
                <span className={styles.badge} style={{ color: statusColor(debug.status) }}>
                  {debug.status}
                </span>
              </div>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Available</td><td>{debug.available ? "yes" : "no"}</td></tr>
                  <tr><td>Reason</td><td>{debug.reason ?? "—"}</td></tr>
                  <tr><td>Policy</td><td>{debug.policy ?? "—"}</td></tr>
                  <tr><td>Deck version</td><td>{debug.deckVersion ?? "—"}</td></tr>
                  <tr><td>Final</td><td>{debug.isFinal == null ? "—" : debug.isFinal ? "yes" : "no"}</td></tr>
                </tbody>
              </table>
            </div>
            <div className={styles.teamStatsCard}>
              <div className={styles.teamStatsHeader}><h3>Counts</h3></div>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Cards</td><td>{debug.cardCount}</td></tr>
                  <tr><td>Last play index</td><td>{debug.lastPlayIndex ?? "—"}</td></tr>
                  <tr><td>Half-innings</td><td>{debug.halfInningCount}</td></tr>
                  <tr><td>Events</td><td>{debug.eventCount}</td></tr>
                  <tr><td>Selected events</td><td>{debug.selectedEventCount}</td></tr>
                  <tr><td>Findings</td><td>{debug.errors.length} errors, {debug.warnings.length} warnings</td></tr>
                </tbody>
              </table>
            </div>
          </div>

          {debug.halfInnings.length > 0 ? (
            <div style={{ overflowX: "auto" }}>
              <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                <thead>
                  <tr>
                    <th>Half</th>
                    <th>Batting</th>
                    <th>Fielding</th>
                    <th>Events</th>
                    <th>Selected</th>
                    <th>Runs</th>
                    <th>Play range</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {debug.halfInnings.map((half) => (
                    <tr key={`${half.inning}-${half.half}`}>
                      <td>{half.half} {half.inning}</td>
                      <td>{half.battingTeam}</td>
                      <td>{half.fieldingTeam}</td>
                      <td>{half.eventCount}</td>
                      <td>{half.selectedCount}</td>
                      <td>{half.scoredRuns}</td>
                      <td>{half.minPlayIndex ?? "—"}–{half.maxPlayIndex ?? "—"}</td>
                      <td style={{ color: statusColor(half.status), fontWeight: 700 }}>{half.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={styles.subtle}>No half-inning containers in the current deck.</div>
          )}

          <div>
            <h3>Validation findings</h3>
            <FindingTable findings={allFindings} />
          </div>

          {debug.deck && (
            <details>
              <summary style={{ cursor: "pointer", fontWeight: 700 }}>Raw outbound deck JSON</summary>
              <pre style={{ maxHeight: 520, overflow: "auto", background: "#0f172a", color: "#e2e8f0", padding: "1rem", borderRadius: 8, fontSize: "0.75rem" }}>
                {deckJson}
              </pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
