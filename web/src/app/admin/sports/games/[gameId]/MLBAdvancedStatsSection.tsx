"use client";

import { useMemo } from "react";
import type { MLBAdvancedTeamStats, MLBAdvancedPlayerStats, MLBPitcherGameStat } from "@/lib/api/sportsAdmin/types";
import { fmtPct, fmtNum } from "@/lib/utils/formatting";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

function fmtVelo(v: number | null | undefined): string {
  return v != null ? `${v.toFixed(1)} mph` : "—";
}

export function MLBAdvancedStatsSection({
  stats,
  playerStats,
  pitcherGameStats,
}: {
  stats?: MLBAdvancedTeamStats[] | null;
  playerStats?: MLBAdvancedPlayerStats[] | null;
  pitcherGameStats?: MLBPitcherGameStat[] | null;
}) {
  const homePlayers = (playerStats ?? [])
    .filter((p) => p.isHome)
    .sort((a, b) => b.totalPitches - a.totalPitches);

  const awayPlayers = (playerStats ?? [])
    .filter((p) => !p.isHome)
    .sort((a, b) => b.totalPitches - a.totalPitches);

  const pitcherStatsByTeam = useMemo((): Record<string, MLBPitcherGameStat[]> => {
    if (!pitcherGameStats) return {};
    return pitcherGameStats.reduce<Record<string, MLBPitcherGameStat[]>>((acc, p) => {
      acc[p.team] = acc[p.team] || [];
      acc[p.team].push(p);
      return acc;
    }, {});
  }, [pitcherGameStats]);

  return (
    <CollapsibleSection title="Advanced Stats (Statcast)" defaultOpen={false}>
      {/* Team-level batting stats */}
      {stats && stats.length > 0 && (
        <div className={styles.teamStatsGrid}>
          {stats.map((t) => (
            <div key={t.team} className={styles.teamStatsCard}>
              <div className={styles.teamStatsHeader}>
                <h3>{t.team}</h3>
                <span className={styles.badge}>{t.isHome ? "Home" : "Away"}</span>
              </div>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Plate Discipline
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Z-Swing%</td><td>{fmtPct(t.zSwingPct)}</td></tr>
                  <tr><td>O-Swing%</td><td>{fmtPct(t.oSwingPct)}</td></tr>
                  <tr><td>Z-Contact%</td><td>{fmtPct(t.zContactPct)}</td></tr>
                  <tr><td>O-Contact%</td><td>{fmtPct(t.oContactPct)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Quality of Contact
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Total Pitches</td><td>{t.totalPitches}</td></tr>
                  <tr><td>Balls in Play</td><td>{t.ballsInPlay}</td></tr>
                  <tr><td>Avg Exit Velo</td><td>{fmtVelo(t.avgExitVelo)}</td></tr>
                  <tr><td>Hard Hit%</td><td>{fmtPct(t.hardHitPct)}</td></tr>
                  <tr><td>Barrel%</td><td>{fmtPct(t.barrelPct)}</td></tr>
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Pitcher Advanced (Statcast) */}
      {pitcherGameStats && pitcherGameStats.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Pitcher Breakdown
          </h3>
          <div className={styles.teamStatsGrid}>
            {Object.entries(pitcherStatsByTeam).map(([team, pitchers]) => (
              <div key={team} className={styles.teamStatsCard}>
                <div className={styles.teamStatsHeader}><h3>{team}</h3></div>
                <div style={{ overflowX: "auto" }}>
                  <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                    <thead>
                      <tr>
                        <th>Player</th>
                        <th>BF</th>
                        <th>PC</th>
                        <th>K</th>
                        <th>BB</th>
                        <th>ZoneP</th>
                        <th>ZoneSw</th>
                        <th>ZoneCon</th>
                        <th>OtsP</th>
                        <th>OtsSw</th>
                        <th>OtsCon</th>
                        <th>BIP</th>
                        <th>Avg EV</th>
                        <th>HH</th>
                        <th>Brl</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pitchers.map((p, idx) => (
                        <tr key={`${team}-pitcher-${idx}-${p.playerName}`}>
                          <td>{p.playerName}{p.isStarter ? " (S)" : ""}</td>
                          <td>{p.battersFaced ?? "—"}</td>
                          <td>{p.pitchesThrown ?? "—"}</td>
                          <td>{p.strikeouts ?? "—"}</td>
                          <td>{p.walks ?? "—"}</td>
                          <td>{p.zonePitches ?? "—"}</td>
                          <td>{p.zoneSwings ?? "—"}</td>
                          <td>{p.zoneContact ?? "—"}</td>
                          <td>{p.outsidePitches ?? "—"}</td>
                          <td>{p.outsideSwings ?? "—"}</td>
                          <td>{p.outsideContact ?? "—"}</td>
                          <td>{p.ballsInPlay ?? "—"}</td>
                          <td>{fmtNum(p.avgExitVeloAgainst)}</td>
                          <td>{p.hardHitAgainst ?? "—"}</td>
                          <td>{p.barrelAgainst ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Batter breakdown */}
      {playerStats && playerStats.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Batter Breakdown
          </h3>
          {[
            { label: "Away", players: awayPlayers },
            { label: "Home", players: homePlayers },
          ]
            .filter((g) => g.players.length > 0)
            .map((group) => (
              <div key={group.label} style={{ marginBottom: "1.25rem" }}>
                <h4 style={{ margin: "0 0 0.5rem", fontSize: "0.9rem", color: "#475569" }}>
                  {group.players[0]?.team ?? group.label}{" "}
                  <span className={styles.badge}>{group.label}</span>
                </h4>
                <div style={{ overflowX: "auto" }}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Batter</th>
                        <th>Pitches</th>
                        <th>ZoneP</th>
                        <th>ZoneSw</th>
                        <th>ZoneCon</th>
                        <th>OtsP</th>
                        <th>OtsSw</th>
                        <th>OtsCon</th>
                        <th>BIP</th>
                        <th>Avg EV</th>
                        <th>HH</th>
                        <th>Brl</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.players.map((p) => (
                        <tr key={p.playerName}>
                          <td>{p.playerName}</td>
                          <td>{p.totalPitches}</td>
                          <td>{p.zonePitches}</td>
                          <td>{p.zoneSwings}</td>
                          <td>{p.zoneContact}</td>
                          <td>{p.outsidePitches}</td>
                          <td>{p.outsideSwings}</td>
                          <td>{p.outsideContact}</td>
                          <td>{p.ballsInPlay}</td>
                          <td>{fmtVelo(p.avgExitVelo)}</td>
                          <td>{p.hardHitCount}</td>
                          <td>{p.barrelCount}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
        </>
      )}
    </CollapsibleSection>
  );
}
