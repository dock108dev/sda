"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { AdminCard } from "@/components/admin";
import { createPool } from "@/lib/api/golfPools";
import { listTournaments } from "@/lib/api/golf";
import type { GolfTournament } from "@/lib/api/golfTypes";
import styles from "../../golf.module.css";

const CLUB_OPTIONS = [
  { code: "rvcc", label: "RVCC", variant: "rvcc", pickCount: 7, countBest: 5, minCuts: 5 },
  { code: "crestmont", label: "Crestmont", variant: "crestmont", pickCount: 6, countBest: 4, minCuts: 4 },
];

export default function CreatePoolPage() {
  const router = useRouter();
  const [tournaments, setTournaments] = useState<GolfTournament[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [clubCode, setClubCode] = useState("rvcc");
  const [tournamentId, setTournamentId] = useState<number | "">("");
  const [entryDeadline, setEntryDeadline] = useState("");
  const [maxEntriesPerEmail, setMaxEntriesPerEmail] = useState<number | "">(1);

  // Auto-filled rules based on club
  const selectedClub = CLUB_OPTIONS.find((c) => c.code === clubCode) ?? CLUB_OPTIONS[0];

  const [tournError, setTournError] = useState<string | null>(null);

  useEffect(() => {
    listTournaments({ limit: 50 })
      .then(setTournaments)
      .catch((err) => setTournError(err instanceof Error ? err.message : "Failed to load tournaments"));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Pool name is required.");
      return;
    }
    if (!tournamentId) {
      setError("Tournament is required.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const pool = await createPool({
        code: `${clubCode}-${tournamentId}-${Date.now()}`,
        name: name.trim(),
        club_code: clubCode,
        tournament_id: Number(tournamentId),
        entry_deadline: entryDeadline || undefined,
        max_entries_per_email: maxEntriesPerEmail ? Number(maxEntriesPerEmail) : undefined,
        scoring_enabled: true,
        allow_self_service_entry: true,
        rules_json: {
          variant: selectedClub.variant,
          pick_count: selectedClub.pickCount,
          count_best: selectedClub.countBest,
          min_cuts_to_qualify: selectedClub.minCuts,
          uses_buckets: selectedClub.variant === "crestmont",
        },
      });
      router.push(`/admin/golf/pools/${pool.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Create Pool</h1>
        <p className={styles.pageSubtitle}>
          Set up a new country club golf pool
        </p>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      <AdminCard>
        <form onSubmit={handleSubmit} style={{ padding: "1rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div className={styles.formGroup}>
            <label>Pool Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Masters 2026 - RVCC"
              required
            />
          </div>

          <div className={styles.formGroup}>
            <label>Club</label>
            <select value={clubCode} onChange={(e) => setClubCode(e.target.value)}>
              {CLUB_OPTIONS.map((c) => (
                <option key={c.code} value={c.code}>{c.label}</option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label>Tournament</label>
            {tournError ? (
              <div style={{ color: "#ef4444", fontSize: "0.85rem" }}>Failed to load tournaments: {tournError}</div>
            ) : (
              <select
                value={tournamentId}
                onChange={(e) => setTournamentId(e.target.value ? Number(e.target.value) : "")}
                required
              >
                <option value="">Select a tournament...</option>
                {tournaments.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.event_name} ({t.start_date})
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className={styles.formGroup}>
            <label>Entry Deadline</label>
            <input
              type="datetime-local"
              value={entryDeadline}
              onChange={(e) => setEntryDeadline(e.target.value)}
            />
          </div>

          <div className={styles.formGroup}>
            <label>Max Entries per Email</label>
            <input
              type="number"
              min="1"
              value={maxEntriesPerEmail}
              onChange={(e) => setMaxEntriesPerEmail(e.target.value ? Number(e.target.value) : "")}
            />
          </div>

          {/* Auto-filled rules preview */}
          <div style={{ background: "#f8fafc", borderRadius: "6px", padding: "1rem" }}>
            <h4 style={{ margin: "0 0 0.5rem 0", fontSize: "0.9rem", color: "#334155" }}>
              Rules (auto-filled for {selectedClub.label})
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem", fontSize: "0.85rem", color: "#64748b" }}>
              <div>Variant: <strong>{selectedClub.variant}</strong></div>
              <div>Picks: <strong>{selectedClub.pickCount}</strong></div>
              <div>Count Best: <strong>{selectedClub.countBest}</strong></div>
              <div>Min Cuts to Qualify: <strong>{selectedClub.minCuts}</strong></div>
              <div>Uses Buckets: <strong>{selectedClub.variant === "crestmont" ? "Yes" : "No"}</strong></div>
            </div>
          </div>

          <div style={{ display: "flex", gap: "1rem", marginTop: "0.5rem" }}>
            <button
              type="submit"
              className={styles.primaryButton}
              disabled={loading}
            >
              {loading ? "Creating..." : "Create Pool"}
            </button>
            <button
              type="button"
              className={styles.btn}
              onClick={() => router.push("/admin/golf/pools")}
              style={{ background: "#e2e8f0", color: "#334155" }}
            >
              Cancel
            </button>
          </div>
        </form>
      </AdminCard>
    </div>
  );
}
