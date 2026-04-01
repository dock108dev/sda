"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { AdminCard, AdminTable } from "@/components/admin";
import {
  fetchTournament,
  fetchTournamentLeaderboard,
  fetchTournamentField,
  fetchTournamentRounds,
  fetchOutrightOdds,
  addFieldPlayer,
  removeFieldPlayer,
} from "@/lib/api/golf";
import type {
  GolfTournament,
  GolfLeaderboardEntry,
  GolfFieldEntry,
  GolfRound,
  GolfOddsEntry,
} from "@/lib/api/golfTypes";
import styles from "../../golf.module.css";

type Tab = "leaderboard" | "field" | "rounds" | "odds";

const MARKET_OPTIONS = ["win", "top_5", "top_10", "make_cut"];

export default function TournamentDetailPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;

  const [tab, setTab] = useState<Tab>("leaderboard");
  const [tournament, setTournament] = useState<GolfTournament | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Tab data
  const [leaderboard, setLeaderboard] = useState<GolfLeaderboardEntry[]>([]);
  const [field, setField] = useState<GolfFieldEntry[]>([]);
  const [rounds, setRounds] = useState<GolfRound[]>([]);
  const [odds, setOdds] = useState<GolfOddsEntry[]>([]);

  // Field management
  const [addPlayerName, setAddPlayerName] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);

  // Filters
  const [selectedRound, setSelectedRound] = useState(1);
  const [market, setMarket] = useState("win");

  // Load tournament info
  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await fetchTournament(eventId);
        setTournament(res);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [eventId]);

  // Load tab data when tab/filters change
  useEffect(() => {
    const loadTab = async () => {
      try {
        if (tab === "leaderboard") {
          setLeaderboard(await fetchTournamentLeaderboard(eventId));
        } else if (tab === "field") {
          const fieldRes = await fetchTournamentField(eventId);
          setField(fieldRes.field ?? []);
        } else if (tab === "rounds") {
          setRounds(await fetchTournamentRounds(eventId, selectedRound));
        } else if (tab === "odds" && tournament?.id) {
          setOdds(await fetchOutrightOdds({ tournament_id: tournament.id, market }));
        }
      } catch {
        // Tab data load failure is non-fatal — empty state is shown
      }
    };
    loadTab();
  }, [eventId, tab, selectedRound, market, tournament?.id]);

  if (loading) return <div className={styles.loading}>Loading tournament...</div>;
  if (error) return <div className={styles.error}>{error}</div>;

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>{tournament?.event_name ?? "Tournament"}</h1>
        <p className={styles.pageSubtitle}>
          {tournament?.course ?? ""} &middot; {tournament?.tour} &middot; {tournament?.status}
        </p>
      </header>

      {/* Tabs */}
      <div className={styles.tabs}>
        {(["leaderboard", "field", "rounds", "odds"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`${styles.tab} ${tab === t ? styles.tabActive : ""}`}
            onClick={() => setTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Leaderboard */}
      {tab === "leaderboard" && (
        <AdminCard>
          {leaderboard.length === 0 ? (
            <div className={styles.empty}>No leaderboard data available.</div>
          ) : (
            <AdminTable
              headers={["Pos", "Player", "Total", "Today", "Thru", "R1", "R2", "R3", "R4", "SG Total", "Win Prob"]}
            >
              {leaderboard.map((e) => (
                <tr key={e.dg_id}>
                  <td>{e.position ?? "-"}</td>
                  <td>{e.player_name ?? "-"}</td>
                  <td>{e.total_score ?? "-"}</td>
                  <td>{e.today_score ?? "-"}</td>
                  <td>{e.thru ?? "-"}</td>
                  <td>{e.r1 ?? "-"}</td>
                  <td>{e.r2 ?? "-"}</td>
                  <td>{e.r3 ?? "-"}</td>
                  <td>{e.r4 ?? "-"}</td>
                  <td>{e.sg_total != null ? e.sg_total.toFixed(2) : "-"}</td>
                  <td>{e.win_prob != null ? `${(e.win_prob * 100).toFixed(1)}%` : "-"}</td>
                </tr>
              ))}
            </AdminTable>
          )}
        </AdminCard>
      )}

      {/* Field */}
      {tab === "field" && (
        <AdminCard>
          <div style={{ padding: "0.75rem 1rem", display: "flex", gap: "0.5rem", alignItems: "flex-end", borderBottom: "1px solid #e5e7eb" }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: "0.85rem", fontWeight: 500, display: "block", marginBottom: "0.25rem" }}>Add Player</label>
              <input
                type="text"
                placeholder="Last, First (e.g. Aberg, Ludvig)"
                value={addPlayerName}
                onChange={(e) => { setAddPlayerName(e.target.value); setFieldError(null); }}
                onKeyDown={async (e) => {
                  if (e.key === "Enter" && addPlayerName.trim()) {
                    try {
                      setFieldError(null);
                      await addFieldPlayer(eventId, addPlayerName.trim());
                      setAddPlayerName("");
                      const fieldRes = await fetchTournamentField(eventId);
                      setField(fieldRes.field ?? []);
                    } catch (err) {
                      setFieldError(err instanceof Error ? err.message : String(err));
                    }
                  }
                }}
                style={{ padding: "0.5rem", borderRadius: "4px", border: "1px solid #ccc", width: "100%" }}
              />
            </div>
            <button
              className={styles.primaryButton}
              disabled={!addPlayerName.trim()}
              onClick={async () => {
                try {
                  setFieldError(null);
                  await addFieldPlayer(eventId, addPlayerName.trim());
                  setAddPlayerName("");
                  const fieldRes = await fetchTournamentField(eventId);
                  setField(fieldRes.field ?? []);
                } catch (err) {
                  setFieldError(err instanceof Error ? err.message : String(err));
                }
              }}
            >
              Add
            </button>
          </div>
          {fieldError && (
            <div style={{ padding: "0.5rem 1rem", color: "#dc2626", fontSize: "0.85rem" }}>
              {fieldError}
            </div>
          )}
          {field.length === 0 ? (
            <div className={styles.empty}>No field data available.</div>
          ) : (
            <>
              <div style={{ padding: "0.5rem 1rem", fontSize: "0.85rem", color: "#666" }}>
                {field.length} players in field
              </div>
              <AdminTable headers={["Player", "Status", "Tee Time R1", "Tee Time R2", "DK Salary", "FD Salary", ""]}>
                {field.map((e) => (
                  <tr key={e.dg_id}>
                    <td>{e.player_name ?? "-"}</td>
                    <td>{e.status}</td>
                    <td>{e.tee_time_r1 ?? "-"}</td>
                    <td>{e.tee_time_r2 ?? "-"}</td>
                    <td>{e.dk_salary != null ? `$${e.dk_salary.toLocaleString()}` : "-"}</td>
                    <td>{e.fd_salary != null ? `$${e.fd_salary.toLocaleString()}` : "-"}</td>
                    <td>
                      <button
                        onClick={async () => {
                          if (!confirm(`Remove ${e.player_name} from the field?`)) return;
                          try {
                            await removeFieldPlayer(eventId, e.dg_id);
                            setField((prev) => prev.filter((f) => f.dg_id !== e.dg_id));
                          } catch (err) {
                            alert(`Failed: ${err instanceof Error ? err.message : String(err)}`);
                          }
                        }}
                        style={{
                          background: "none",
                          border: "1px solid #dc2626",
                          color: "#dc2626",
                          padding: "0.2rem 0.5rem",
                          borderRadius: "4px",
                          fontSize: "0.8rem",
                          cursor: "pointer",
                        }}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </AdminTable>
            </>
          )}
        </AdminCard>
      )}

      {/* Rounds */}
      {tab === "rounds" && (
        <AdminCard>
          <div className={styles.filterBar}>
            <div className={styles.formGroup}>
              <label>Round</label>
              <select
                value={selectedRound}
                onChange={(e) => setSelectedRound(Number(e.target.value))}
              >
                {[1, 2, 3, 4].map((r) => (
                  <option key={r} value={r}>Round {r}</option>
                ))}
              </select>
            </div>
          </div>
          {rounds.length === 0 ? (
            <div className={styles.empty}>No round data available.</div>
          ) : (
            <AdminTable
              headers={["DG ID", "Score", "Strokes", "SG OTT", "SG APP", "SG ARG", "SG Putt", "SG Total"]}
            >
              {rounds.map((e) => (
                <tr key={e.dg_id}>
                  <td>{e.dg_id}</td>
                  <td>{e.score ?? "-"}</td>
                  <td>{e.strokes ?? "-"}</td>
                  <td>{e.sg_ott != null ? e.sg_ott.toFixed(2) : "-"}</td>
                  <td>{e.sg_app != null ? e.sg_app.toFixed(2) : "-"}</td>
                  <td>{e.sg_arg != null ? e.sg_arg.toFixed(2) : "-"}</td>
                  <td>{e.sg_putt != null ? e.sg_putt.toFixed(2) : "-"}</td>
                  <td>{e.sg_total != null ? e.sg_total.toFixed(2) : "-"}</td>
                </tr>
              ))}
            </AdminTable>
          )}
        </AdminCard>
      )}

      {/* Odds */}
      {tab === "odds" && (
        <AdminCard>
          <div className={styles.filterBar}>
            <div className={styles.formGroup}>
              <label>Market</label>
              <select value={market} onChange={(e) => setMarket(e.target.value)}>
                {MARKET_OPTIONS.map((m) => (
                  <option key={m} value={m}>{m.replace("_", " ")}</option>
                ))}
              </select>
            </div>
          </div>
          {odds.length === 0 ? (
            <div className={styles.empty}>No odds data available.</div>
          ) : (
            <AdminTable headers={["Player", "Book", "Market", "Odds", "DG Prob"]}>
              {odds.map((e, i) => (
                <tr key={`${e.dg_id}-${e.book}-${i}`}>
                  <td>{e.player_name ?? "-"}</td>
                  <td>{e.book}</td>
                  <td>{e.market}</td>
                  <td>{e.odds}</td>
                  <td>{e.dg_prob != null ? `${(e.dg_prob * 100).toFixed(1)}%` : "-"}</td>
                </tr>
              ))}
            </AdminTable>
          )}
        </AdminCard>
      )}
    </div>
  );
}
