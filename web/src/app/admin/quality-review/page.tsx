"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./styles.module.css";

interface TierBreakdown {
  tier1?: { score?: number; failures?: string[]; checks?: Record<string, boolean> };
  tier2?: { score?: number | null; rubric?: Record<string, number>; cache_hit?: boolean };
}

interface QueueItem {
  id: number;
  flowId: number;
  gameId: number;
  sport: string;
  gameDate: string | null;
  flowSource: string | null;
  combinedScore: number;
  tier1Score: number;
  tier2Score: number | null;
  tierBreakdown: TierBreakdown;
  forbiddenPhrases: string[];
  narrativePreview: string;
  status: string;
  createdAt: string;
}

interface QueueResponse {
  total: number;
  page: number;
  pageSize: number;
  items: QueueItem[];
}

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 30_000;

function scoreClass(score: number): string {
  if (score >= 75) return styles.scoreHigh;
  if (score >= 50) return styles.scoreMid;
  return styles.scoreLow;
}

export default function QualityReviewPage() {
  const [data, setData] = useState<QueueResponse | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchQueue = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const res = await fetch(
          `/proxy/api/admin/quality-review?status_filter=pending&page=${page}&page_size=${PAGE_SIZE}`
        );
        if (!res.ok) throw new Error(`Failed to load queue (${res.status})`);
        setData(await res.json());
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load queue");
      } finally {
        setLoading(false);
      }
    },
    [page]
  );

  // Initial load + page change
  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  // 30-second polling
  useEffect(() => {
    intervalRef.current = setInterval(() => fetchQueue(true), POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchQueue]);

  async function handleAction(queueId: number, action: "approve" | "reject" | "regenerate") {
    const labels: Record<typeof action, string> = {
      approve: "Approve",
      reject: "Reject (deletes flow and re-queues generation)",
      regenerate: "Regenerate (deletes flow and forces fresh LLM run)",
    };
    if (!confirm(`${labels[action]} — are you sure?`)) return;

    setActionInFlight(queueId);
    try {
      const res = await fetch(`/proxy/api/admin/quality-review/${queueId}/${action}`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Action failed (${res.status})`);
      }
      await fetchQueue(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setActionInFlight(null);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Quality Review Queue</h1>
          <p className={styles.subtitle}>
            Flows escalated by the 3-tier grader — combined score below threshold. Polls every 30s.
          </p>
        </div>
        <button className={styles.refreshBtn} onClick={() => fetchQueue()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className={styles.error}>
          {error}
          <button onClick={() => setError(null)} className={styles.dismissBtn}>
            Dismiss
          </button>
        </div>
      )}

      {!loading && data?.total === 0 && (
        <div className={styles.empty}>
          No flows pending review.
        </div>
      )}

      {data && data.items.length > 0 && (
        <>
          <p className={styles.meta}>
            Showing {(page - 1) * PAGE_SIZE + 1}–
            {Math.min(page * PAGE_SIZE, data.total)} of {data.total} items
          </p>

          <table className={styles.table}>
            <thead>
              <tr>
                <th>Game</th>
                <th>Source</th>
                <th>Score</th>
                <th>Tier Breakdown</th>
                <th>Forbidden Phrases</th>
                <th>Preview</th>
                <th>Escalated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <div className={styles.gameCell}>
                      <span className={styles.sport}>{item.sport}</span>
                      <span className={styles.gameId}>#{item.gameId}</span>
                      {item.gameDate && (
                        <span className={styles.date}>
                          {new Date(item.gameDate).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </td>
                  <td>
                    <span
                      className={`${styles.badge} ${
                        item.flowSource === "TEMPLATE" ? styles.badgeTemplate : styles.badgeLlm
                      }`}
                    >
                      {item.flowSource ?? "LLM"}
                    </span>
                  </td>
                  <td>
                    <span className={`${styles.score} ${scoreClass(item.combinedScore)}`}>
                      {item.combinedScore.toFixed(1)}
                    </span>
                  </td>
                  <td>
                    <div className={styles.tiers}>
                      <span title="Tier 1 (rule-based)">
                        T1: {item.tier1Score.toFixed(1)}
                      </span>
                      {item.tier2Score != null && (
                        <span title="Tier 2 (LLM)">
                          T2: {item.tier2Score.toFixed(1)}
                        </span>
                      )}
                    </div>
                    {item.tierBreakdown.tier1?.failures &&
                      item.tierBreakdown.tier1.failures.length > 0 && (
                        <details className={styles.failuresDetails}>
                          <summary className={styles.failuresSummary}>
                            {item.tierBreakdown.tier1.failures.length} failure
                            {item.tierBreakdown.tier1.failures.length !== 1 ? "s" : ""}
                          </summary>
                          <ul className={styles.failuresList}>
                            {item.tierBreakdown.tier1.failures.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                  </td>
                  <td>
                    {item.forbiddenPhrases.length === 0 ? (
                      <span className={styles.none}>—</span>
                    ) : (
                      <div className={styles.phrases}>
                        {item.forbiddenPhrases.map((p) => (
                          <span key={p} className={styles.phrase}>
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    <p className={styles.preview}>
                      {item.narrativePreview || <em className={styles.none}>No preview</em>}
                    </p>
                  </td>
                  <td className={styles.dateCell}>
                    {new Date(item.createdAt).toLocaleString()}
                  </td>
                  <td>
                    <div className={styles.actions}>
                      <button
                        className={`${styles.actionBtn} ${styles.approveBtn}`}
                        onClick={() => handleAction(item.id, "approve")}
                        disabled={actionInFlight === item.id}
                      >
                        Approve
                      </button>
                      <button
                        className={`${styles.actionBtn} ${styles.rejectBtn}`}
                        onClick={() => handleAction(item.id, "reject")}
                        disabled={actionInFlight === item.id}
                      >
                        Reject
                      </button>
                      <button
                        className={`${styles.actionBtn} ${styles.regenBtn}`}
                        onClick={() => handleAction(item.id, "regenerate")}
                        disabled={actionInFlight === item.id}
                      >
                        Regenerate
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <div className={styles.pagination}>
              <button
                className={styles.pageBtn}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                ← Prev
              </button>
              <span className={styles.pageInfo}>
                Page {page} / {totalPages}
              </span>
              <button
                className={styles.pageBtn}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
