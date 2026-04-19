"use client";

import { useMemo } from "react";
import type { NFLAdvancedTeamStats, NFLAdvancedPlayerStats } from "@/lib/api/sportsAdmin/types";
import { fmtPct } from "@/lib/utils/formatting";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

function fmtEpa(v: number | null | undefined): string {
  return v != null ? v.toFixed(1) : "—";
}

function fmtCpoe(v: number | null | undefined): string {
  return v != null ? v.toFixed(1) : "—";
}

function fmtNum(v: number | null | undefined): string {
  return v != null ? String(v) : "—";
}

type Props = {
  teamStats?: NFLAdvancedTeamStats[] | null;
  playerStats?: NFLAdvancedPlayerStats[] | null;
};

export function NFLAdvancedStatsSection({ teamStats, playerStats }: Props) {
  const sortedTeams = useMemo(() => {
    if (!teamStats) return [];
    return [...teamStats].sort((a, b) => {
      if (a.isHome === b.isHome) return 0;
      return a.isHome ? 1 : -1; // away first, then home
    });
  }, [teamStats]);

  const { passers, rushers, receivers } = useMemo(() => {
    const p: NFLAdvancedPlayerStats[] = [];
    const ru: NFLAdvancedPlayerStats[] = [];
    const re: NFLAdvancedPlayerStats[] = [];
    for (const s of playerStats ?? []) {
      const role = (s.playerRole ?? "").toLowerCase();
      if (role === "passer") p.push(s);
      else if (role === "rusher") ru.push(s);
      else if (role === "receiver") re.push(s);
    }
    // Sort each group by total EPA descending (nulls last)
    const sortByEpa = (a: NFLAdvancedPlayerStats, b: NFLAdvancedPlayerStats) =>
      (b.totalEpa ?? -Infinity) - (a.totalEpa ?? -Infinity);
    p.sort(sortByEpa);
    ru.sort(sortByEpa);
    re.sort(sortByEpa);
    return { passers: p, rushers: ru, receivers: re };
  }, [playerStats]);

  return (
    <CollapsibleSection title="Advanced Stats (NFL)" defaultOpen={false}>
      {/* Team Comparison */}
      {sortedTeams.length > 0 && (
        <div className={styles.teamStatsGrid}>
          {sortedTeams.map((t) => (
            <div key={t.team} className={styles.teamStatsCard}>
              <div className={styles.teamStatsHeader}>
                <h3>{t.team}</h3>
                <span className={styles.badge}>{t.isHome ? "Home" : "Away"}</span>
              </div>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                EPA
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Total EPA</td><td>{fmtEpa(t.totalEpa)}</td></tr>
                  <tr><td>Pass EPA</td><td>{fmtEpa(t.passEpa)}</td></tr>
                  <tr><td>Rush EPA</td><td>{fmtEpa(t.rushEpa)}</td></tr>
                  <tr><td>EPA/Play</td><td>{fmtEpa(t.epaPerPlay)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                WPA
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Total WPA</td><td>{fmtEpa(t.totalWpa)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Success
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Success Rate</td><td>{fmtPct(t.successRate)}</td></tr>
                  <tr><td>Pass Success Rate</td><td>{fmtPct(t.passSuccessRate)}</td></tr>
                  <tr><td>Rush Success Rate</td><td>{fmtPct(t.rushSuccessRate)}</td></tr>
                  <tr><td>Explosive Play Rate</td><td>{fmtPct(t.explosivePlayRate)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Passing Context
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Avg CPOE</td><td>{fmtCpoe(t.avgCpoe)}</td></tr>
                  <tr><td>Avg Air Yards</td><td>{fmtEpa(t.avgAirYards)}</td></tr>
                  <tr><td>Avg YAC</td><td>{fmtEpa(t.avgYac)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Volume
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Total Plays</td><td>{fmtNum(t.totalPlays)}</td></tr>
                  <tr><td>Pass Plays</td><td>{fmtNum(t.passPlays)}</td></tr>
                  <tr><td>Rush Plays</td><td>{fmtNum(t.rushPlays)}</td></tr>
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Player Stats — Passers */}
      {passers.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Passers
          </h3>
          <div style={{ overflowX: "auto" }}>
            <table className={styles.table} style={{ fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>EPA</th>
                  <th>EPA/Play</th>
                  <th>CPOE</th>
                  <th>Air EPA</th>
                  <th>YAC EPA</th>
                  <th>WPA</th>
                  <th>Success Rate</th>
                  <th>Plays</th>
                </tr>
              </thead>
              <tbody>
                {passers.map((p, idx) => (
                  <tr key={`passer-${idx}-${p.playerName}`}>
                    <td>{p.playerName}</td>
                    <td>{fmtEpa(p.totalEpa)}</td>
                    <td>{fmtEpa(p.epaPerPlay)}</td>
                    <td>{fmtCpoe(p.cpoe)}</td>
                    <td>{fmtEpa(p.airEpa)}</td>
                    <td>{fmtEpa(p.yacEpa)}</td>
                    <td>{fmtEpa(p.totalWpa)}</td>
                    <td>{fmtPct(p.successRate)}</td>
                    <td>{fmtNum(p.plays)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Player Stats — Rushers */}
      {rushers.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Rushers
          </h3>
          <div style={{ overflowX: "auto" }}>
            <table className={styles.table} style={{ fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>EPA</th>
                  <th>EPA/Play</th>
                  <th>WPA</th>
                  <th>Success Rate</th>
                  <th>Plays</th>
                </tr>
              </thead>
              <tbody>
                {rushers.map((p, idx) => (
                  <tr key={`rusher-${idx}-${p.playerName}`}>
                    <td>{p.playerName}</td>
                    <td>{fmtEpa(p.totalEpa)}</td>
                    <td>{fmtEpa(p.epaPerPlay)}</td>
                    <td>{fmtEpa(p.totalWpa)}</td>
                    <td>{fmtPct(p.successRate)}</td>
                    <td>{fmtNum(p.plays)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Player Stats — Receivers */}
      {receivers.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Receivers
          </h3>
          <div style={{ overflowX: "auto" }}>
            <table className={styles.table} style={{ fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>EPA</th>
                  <th>EPA/Play</th>
                  <th>Air Yards</th>
                  <th>WPA</th>
                  <th>Success Rate</th>
                  <th>Plays</th>
                </tr>
              </thead>
              <tbody>
                {receivers.map((p, idx) => (
                  <tr key={`receiver-${idx}-${p.playerName}`}>
                    <td>{p.playerName}</td>
                    <td>{fmtEpa(p.totalEpa)}</td>
                    <td>{fmtEpa(p.epaPerPlay)}</td>
                    <td>{fmtEpa(p.airYards)}</td>
                    <td>{fmtEpa(p.totalWpa)}</td>
                    <td>{fmtPct(p.successRate)}</td>
                    <td>{fmtNum(p.plays)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </CollapsibleSection>
  );
}
