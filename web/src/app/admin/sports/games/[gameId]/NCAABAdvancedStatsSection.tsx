"use client";

import type { NCAABAdvancedTeamStats, NCAABAdvancedPlayerStats } from "@/lib/api/sportsAdmin/types";
import { fmtPct } from "@/lib/utils/formatting";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

function fmtRating(v: number | null | undefined): string {
  return v != null ? v.toFixed(1) : "—";
}

function fmtNum(v: number | null | undefined, decimals = 0): string {
  return v != null ? v.toFixed(decimals) : "—";
}

export function NCAABAdvancedStatsSection({
  teamStats,
  playerStats,
}: {
  teamStats?: NCAABAdvancedTeamStats[] | null;
  playerStats?: NCAABAdvancedPlayerStats[] | null;
}) {
  const sortedTeams = [...(teamStats ?? [])].sort((a, b) => {
    if (a.isHome === b.isHome) return 0;
    return a.isHome ? 1 : -1; // away first, then home
  });

  const awayPlayers = (playerStats ?? [])
    .filter((p) => !p.isHome)
    .sort((a, b) => (b.gameScore ?? 0) - (a.gameScore ?? 0));

  const homePlayers = (playerStats ?? [])
    .filter((p) => p.isHome)
    .sort((a, b) => (b.gameScore ?? 0) - (a.gameScore ?? 0));

  return (
    <CollapsibleSection title="Advanced Stats (NCAAB)" defaultOpen={false}>
      {/* Team Comparison */}
      {sortedTeams.length > 0 && (
        <>
          <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Team Comparison
          </h3>
          <div className={styles.teamStatsGrid}>
            {sortedTeams.map((t) => (
              <div key={t.team} className={styles.teamStatsCard}>
                <div className={styles.teamStatsHeader}>
                  <h3>{t.team}</h3>
                  <span className={styles.badge}>{t.isHome ? "Home" : "Away"}</span>
                </div>

                <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                  Efficiency
                </h4>
                <table className={styles.table}>
                  <tbody>
                    <tr><td>OFF RTG</td><td>{fmtRating(t.offRating)}</td></tr>
                    <tr><td>DEF RTG</td><td>{fmtRating(t.defRating)}</td></tr>
                    <tr><td>NET RTG</td><td>{fmtRating(t.netRating)}</td></tr>
                    <tr><td>PACE</td><td>{fmtRating(t.pace)}</td></tr>
                    <tr><td>Possessions</td><td>{fmtNum(t.possessions)}</td></tr>
                  </tbody>
                </table>

                <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                  Four Factors (Offense)
                </h4>
                <table className={styles.table}>
                  <tbody>
                    <tr><td>eFG%</td><td>{fmtPct(t.offEfgPct)}</td></tr>
                    <tr><td>TOV%</td><td>{fmtPct(t.offTovPct)}</td></tr>
                    <tr><td>ORB%</td><td>{fmtPct(t.offOrbPct)}</td></tr>
                    <tr><td>FT Rate</td><td>{fmtPct(t.offFtRate)}</td></tr>
                  </tbody>
                </table>

                <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                  Four Factors (Defense)
                </h4>
                <table className={styles.table}>
                  <tbody>
                    <tr><td>Opp eFG%</td><td>{fmtPct(t.defEfgPct)}</td></tr>
                    <tr><td>Opp TOV%</td><td>{fmtPct(t.defTovPct)}</td></tr>
                    <tr><td>Opp ORB%</td><td>{fmtPct(t.defOrbPct)}</td></tr>
                    <tr><td>Opp FT Rate</td><td>{fmtPct(t.defFtRate)}</td></tr>
                  </tbody>
                </table>

                <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                  Shooting
                </h4>
                <table className={styles.table}>
                  <tbody>
                    <tr><td>FG%</td><td>{fmtPct(t.fgPct)}</td></tr>
                    <tr><td>3PT%</td><td>{fmtPct(t.threePtPct)}</td></tr>
                    <tr><td>FT%</td><td>{fmtPct(t.ftPct)}</td></tr>
                    <tr><td>3PT Rate</td><td>{fmtPct(t.threePtRate)}</td></tr>
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Player Stats */}
      {playerStats && playerStats.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Player Stats
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
                  <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                    <thead>
                      <tr>
                        <th>Player</th>
                        <th>MIN</th>
                        <th>PTS</th>
                        <th>REB</th>
                        <th>AST</th>
                        <th>STL</th>
                        <th>BLK</th>
                        <th>TO</th>
                        <th>TS%</th>
                        <th>eFG%</th>
                        <th>USG%</th>
                        <th>Game Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.players.map((p) => (
                        <tr key={p.playerName}>
                          <td>{p.playerName}</td>
                          <td>{fmtNum(p.minutes)}</td>
                          <td>{fmtNum(p.points)}</td>
                          <td>{fmtNum(p.rebounds)}</td>
                          <td>{fmtNum(p.assists)}</td>
                          <td>{fmtNum(p.steals)}</td>
                          <td>{fmtNum(p.blocks)}</td>
                          <td>{fmtNum(p.turnovers)}</td>
                          <td>{fmtPct(p.tsPct)}</td>
                          <td>{fmtPct(p.efgPct)}</td>
                          <td>{fmtPct(p.usgPct)}</td>
                          <td>{fmtRating(p.gameScore)}</td>
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
