"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  fetchPool,
  fetchPoolLeaderboard,
  fetchPoolEntries,
  rescorePool,
  lockPool,
  deletePoolEntry,
  entriesExportUrl,
} from "@/lib/api/golfPools";
import type {
  GolfPool,
  GolfPoolEntry,
  GolfPoolLeaderboardEntry,
} from "@/lib/api/golfPoolTypes";
import styles from "../../golf.module.css";

type Tab = "overview" | "leaderboard" | "entries" | "operations";

export default function PoolDetailPage() {
  const params = useParams<{ poolId: string }>();
  const poolId = params.poolId;

  const [tab, setTab] = useState<Tab>("overview");
  const [pool, setPool] = useState<GolfPool | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Tab data
  const [leaderboard, setLeaderboard] = useState<GolfPoolLeaderboardEntry[]>([]);
  const [entries, setEntries] = useState<GolfPoolEntry[]>([]);
  const [entrySearch, setEntrySearch] = useState("");

  // Operation status
  const [opMessage, setOpMessage] = useState<string | null>(null);
  const [opLoading, setOpLoading] = useState(false);

  // Load pool info
  useEffect(() => {
    setLoading(true);
    fetchPool(poolId)
      .then((res) => setPool(res))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [poolId]);

  const [tabError, setTabError] = useState<string | null>(null);

  // Load tab data
  const loadTabData = useCallback(async () => {
    setTabError(null);
    try {
      if (tab === "leaderboard") {
        const res = await fetchPoolLeaderboard(poolId);
        setLeaderboard(res);
      } else if (tab === "entries") {
        const res = await fetchPoolEntries(poolId);
        setEntries(res);
      }
    } catch (err) {
      setTabError(err instanceof Error ? err.message : "Failed to load tab data");
    }
  }, [poolId, tab]);

  useEffect(() => {
    loadTabData();
  }, [loadTabData]);

  const handleRescore = async () => {
    setOpLoading(true);
    setOpMessage(null);
    try {
      const res = await rescorePool(poolId);
      setOpMessage(`Rescore triggered. Task ID: ${res.task_id ?? "submitted"}`);
    } catch (err) {
      setOpMessage(`Rescore failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setOpLoading(false);
    }
  };

  const handleLock = async () => {
    setOpLoading(true);
    setOpMessage(null);
    try {
      const updated = await lockPool(poolId);
      setPool(updated);
      setOpMessage("Pool locked successfully.");
    } catch (err) {
      setOpMessage(`Lock failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setOpLoading(false);
    }
  };

  const handleDeleteEntry = async (entryId: number, email: string) => {
    if (!confirm(`Delete entry #${entryId} (${email})? This cannot be undone.`)) return;
    try {
      await deletePoolEntry(poolId, entryId);
      setEntries((prev) => prev.filter((e) => e.id !== entryId));
    } catch (err) {
      alert(`Failed to delete entry: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleExportCsv = () => {
    window.open(entriesExportUrl(poolId), "_blank");
  };

  const filteredEntries = entries.filter((e) => {
    if (!entrySearch) return true;
    const q = entrySearch.toLowerCase();
    return (
      e.email.toLowerCase().includes(q) ||
      (e.entry_name ?? "").toLowerCase().includes(q)
    );
  });

  if (loading) return <div className={styles.loading}>Loading pool...</div>;
  if (error) return <div className={styles.error}>{error}</div>;

  const rules = pool?.rules as Record<string, unknown> | null;

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>{pool?.name ?? "Pool"}</h1>
        <p className={styles.pageSubtitle}>
          {pool?.club_code} &middot; {pool?.status} &middot; {pool?.entries_count} entries
        </p>
      </header>

      {/* Tabs */}
      <div className={styles.tabs}>
        {(["overview", "leaderboard", "entries", "operations"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`${styles.tab} ${tab === t ? styles.tabActive : ""}`}
            onClick={() => setTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Overview */}
      {tab === "overview" && pool && (
        <AdminCard>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", padding: "1rem" }}>
            <div>
              <strong>Club Code:</strong> {pool.club_code}
            </div>
            <div>
              <strong>Status:</strong> {pool.status}
            </div>
            <div>
              <strong>Tournament:</strong> {pool.tournament_name ?? pool.tournament_id}
            </div>
            <div>
              <strong>Scoring Enabled:</strong> {pool.scoring_enabled ? "Yes" : "No"}
            </div>
            <div>
              <strong>Entry Deadline:</strong>{" "}
              {pool.entry_deadline
                ? new Date(pool.entry_deadline).toLocaleString()
                : "Not set"}
            </div>
            <div>
              <strong>Max Entries per Email:</strong>{" "}
              {pool.max_entries_per_email ?? "Unlimited"}
            </div>
            <div>
              <strong>Total Entries:</strong> {pool.entries_count}
            </div>
            <div>
              <strong>Last Scored:</strong>{" "}
              {pool.last_scored_at
                ? new Date(pool.last_scored_at).toLocaleString()
                : "Never"}
            </div>
            {rules && (
              <>
                <div>
                  <strong>Variant:</strong> {String(rules.variant ?? "-")}
                </div>
                <div>
                  <strong>Pick Count:</strong> {String(rules.pick_count ?? "-")}
                </div>
                <div>
                  <strong>Count Best:</strong> {String(rules.count_best ?? "-")}
                </div>
                <div>
                  <strong>Min Cuts to Qualify:</strong>{" "}
                  {String(rules.min_cuts_to_qualify ?? "-")}
                </div>
              </>
            )}
          </div>
        </AdminCard>
      )}

      {tabError && <div className={styles.error}>{tabError}</div>}

      {/* Leaderboard */}
      {!tabError && tab === "leaderboard" && (
        <AdminCard>
          {leaderboard.length === 0 ? (
            <div className={styles.empty}>No leaderboard data available. Pool may not have been scored yet.</div>
          ) : (
            <AdminTable
              headers={[
                "Rank",
                "Entry",
                "Email",
                "Score",
                "Qualified",
                "Counted",
                "Status",
                ...leaderboard[0]?.picks?.map((_, i) => `Pick ${i + 1}`) ?? [],
              ]}
            >
              {leaderboard.map((e) => (
                <tr key={e.entry_id}>
                  <td>
                    {e.rank != null ? (e.is_tied ? `T${e.rank}` : String(e.rank)) : "-"}
                  </td>
                  <td>{e.entry_name ?? "-"}</td>
                  <td style={{ fontSize: "0.85rem" }}>{e.email}</td>
                  <td>
                    {e.aggregate_score != null
                      ? (e.aggregate_score > 0 ? `+${e.aggregate_score}` : String(e.aggregate_score))
                      : "-"}
                  </td>
                  <td>{e.qualified_golfers_count}</td>
                  <td>{e.counted_golfers_count}</td>
                  <td>{e.qualification_status}</td>
                  {e.picks.map((pick) => (
                    <td
                      key={pick.dg_id}
                      style={{
                        fontSize: "0.8rem",
                        opacity: pick.is_dropped ? 0.5 : 1,
                        textDecoration: pick.is_dropped ? "line-through" : "none",
                      }}
                      title={`${pick.player_name} (${pick.status}) — ${pick.total_score != null ? pick.total_score : "N/A"}`}
                    >
                      {pick.player_name?.split(" ").pop() ?? "-"}
                      {pick.total_score != null ? ` (${pick.total_score > 0 ? "+" : ""}${pick.total_score})` : ""}
                    </td>
                  ))}
                </tr>
              ))}
            </AdminTable>
          )}
        </AdminCard>
      )}

      {/* Entries */}
      {!tabError && tab === "entries" && (
        <AdminCard>
          <div className={styles.filterBar} style={{ display: "flex", alignItems: "flex-end", gap: "1rem" }}>
            <div className={styles.formGroup} style={{ flex: 1 }}>
              <label>Search</label>
              <input
                type="text"
                placeholder="Filter by email or name..."
                value={entrySearch}
                onChange={(e) => setEntrySearch(e.target.value)}
                style={{ padding: "0.5rem", borderRadius: "4px", border: "1px solid #ccc", width: "100%" }}
              />
            </div>
            <button
              className={styles.primaryButton}
              onClick={handleExportCsv}
              disabled={entries.length === 0}
              title="Download all entries as CSV"
            >
              Export CSV
            </button>
          </div>
          {filteredEntries.length === 0 ? (
            <div className={styles.empty}>No entries found.</div>
          ) : (
            <AdminTable headers={["ID", "Email", "Entry Name", "Picks", "Created", ""]}>
              {filteredEntries.map((e) => {
                const pickCount = e.picks?.length ?? e.picks_count ?? 0;
                const incomplete = pickCount < 7;
                const lastNames = (e.picks ?? [])
                  .sort((a, b) => a.pick_slot - b.pick_slot)
                  .map((pk) => {
                    const name = pk.player_name || "";
                    // "Last, First" → "Last"; "First Last" → "Last"
                    return name.includes(",") ? name.split(",")[0].trim() : name.split(" ").pop() ?? name;
                  })
                  .join(", ");

                return (
                  <tr
                    key={e.id}
                    style={incomplete ? { background: "#fef2f2", borderLeft: "3px solid #dc2626" } : undefined}
                  >
                    <td>{e.id}</td>
                    <td>{e.email}</td>
                    <td>{e.entry_name ?? "-"}</td>
                    <td
                      style={{ fontSize: "0.85rem", maxWidth: "400px" }}
                      title={lastNames}
                    >
                      {incomplete && (
                        <span style={{ color: "#dc2626", fontWeight: 600, marginRight: "0.25rem" }}>
                          ({pickCount}/7)
                        </span>
                      )}
                      {lastNames || "-"}
                    </td>
                    <td style={{ fontSize: "0.85rem" }}>
                      {new Date(e.created_at).toLocaleString()}
                    </td>
                    <td>
                      <button
                        onClick={() => handleDeleteEntry(e.id, e.email)}
                        style={{
                          background: "none",
                          border: "1px solid #dc2626",
                          color: "#dc2626",
                          padding: "0.25rem 0.5rem",
                          borderRadius: "4px",
                          fontSize: "0.8rem",
                          cursor: "pointer",
                        }}
                        title={`Delete entry for ${e.email}`}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </AdminTable>
          )}
          <div style={{ padding: "0.5rem 1rem", fontSize: "0.85rem", color: "#666" }}>
            {filteredEntries.length} of {entries.length} entries shown
          </div>
        </AdminCard>
      )}

      {/* Operations */}
      {tab === "operations" && (
        <AdminCard>
          <div style={{ padding: "1rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
            <h3 style={{ margin: 0 }}>Pool Operations</h3>

            {opMessage && (
              <div
                style={{
                  padding: "0.75rem",
                  background: opMessage.includes("failed") ? "#fee" : "#efe",
                  borderRadius: "4px",
                  fontSize: "0.9rem",
                }}
              >
                {opMessage}
              </div>
            )}

            <div style={{ display: "flex", gap: "1rem" }}>
              <button
                className={styles.primaryButton}
                onClick={handleRescore}
                disabled={opLoading}
              >
                {opLoading ? "Processing..." : "Rescore Pool"}
              </button>

              <button
                className={styles.primaryButton}
                onClick={handleLock}
                disabled={opLoading || pool?.status === "closed"}
                style={{
                  background: pool?.status === "closed" ? "#999" : undefined,
                }}
              >
                {pool?.status === "closed" ? "Already Locked" : "Lock Pool"}
              </button>
            </div>

            <p style={{ fontSize: "0.85rem", color: "#666", margin: 0 }}>
              <strong>Rescore:</strong> Triggers the scoring engine to recalculate all entry scores from current leaderboard data.
            </p>
            <p style={{ fontSize: "0.85rem", color: "#666", margin: 0 }}>
              <strong>Lock:</strong> Prevents new entries and locks the pool for scoring only.
            </p>
          </div>
        </AdminCard>
      )}
    </div>
  );
}
