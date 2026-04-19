"use client";

import type { NBAAdvancedTeamStats, NBAAdvancedPlayerStats } from "@/lib/api/sportsAdmin/types";
import { fmtPct } from "@/lib/utils/formatting";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

function fmtRating(v: number | null | undefined): string {
  return v != null ? v.toFixed(1) : "—";
}

function fmtInt(v: number | null | undefined): string {
  return v != null ? String(v) : "—";
}

export function NBAAdvancedStatsSection({
  teamStats,
  playerStats,
}: {
  teamStats?: NBAAdvancedTeamStats[] | null;
  playerStats?: NBAAdvancedPlayerStats[] | null;
}) {
  const homeTeam = teamStats?.find((t) => t.isHome);
  const awayTeam = teamStats?.find((t) => !t.isHome);

  const awayPlayers = (playerStats ?? [])
    .filter((p) => !p.isHome)
    .sort((a, b) => (b.minutes ?? 0) - (a.minutes ?? 0));

  const homePlayers = (playerStats ?? [])
    .filter((p) => p.isHome)
    .sort((a, b) => (b.minutes ?? 0) - (a.minutes ?? 0));

  return (
    <CollapsibleSection title="Advanced Stats (NBA)" defaultOpen={false}>
      {/* Team Comparison */}
      {teamStats && teamStats.length > 0 && (
        <div className={styles.teamStatsGrid}>
          {[awayTeam, homeTeam].filter(Boolean).map((t) => (
            <div key={t!.team} className={styles.teamStatsCard}>
              <div className={styles.teamStatsHeader}>
                <h3>{t!.team}</h3>
                <span className={styles.badge}>{t!.isHome ? "Home" : "Away"}</span>
              </div>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Efficiency
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>OFF RTG</td><td>{fmtRating(t!.offRating)}</td></tr>
                  <tr><td>DEF RTG</td><td>{fmtRating(t!.defRating)}</td></tr>
                  <tr><td>NET RTG</td><td>{fmtRating(t!.netRating)}</td></tr>
                  <tr><td>PACE</td><td>{fmtRating(t!.pace)}</td></tr>
                  <tr><td>PIE</td><td>{fmtPct(t!.pie)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Shooting
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>eFG%</td><td>{fmtPct(t!.efgPct)}</td></tr>
                  <tr><td>TS%</td><td>{fmtPct(t!.tsPct)}</td></tr>
                  <tr><td>FG%</td><td>{fmtPct(t!.fgPct)}</td></tr>
                  <tr><td>3PT%</td><td>{fmtPct(t!.fg3Pct)}</td></tr>
                  <tr><td>FT%</td><td>{fmtPct(t!.ftPct)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Rebounding
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>ORB%</td><td>{fmtPct(t!.orbPct)}</td></tr>
                  <tr><td>DRB%</td><td>{fmtPct(t!.drbPct)}</td></tr>
                  <tr><td>REB%</td><td>{fmtPct(t!.rebPct)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Ball Movement
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>AST%</td><td>{fmtPct(t!.astPct)}</td></tr>
                  <tr><td>AST/TO</td><td>{fmtRating(t!.astTovRatio)}</td></tr>
                  <tr><td>TOV%</td><td>{fmtPct(t!.tovPct)}</td></tr>
                  <tr><td>Free Throw Rate</td><td>{fmtRating(t!.ftRate)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Hustle
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Contested Shots</td><td>{fmtInt(t!.contestedShots)}</td></tr>
                  <tr><td>Deflections</td><td>{fmtInt(t!.deflections)}</td></tr>
                  <tr><td>Charges Drawn</td><td>{fmtInt(t!.chargesDrawn)}</td></tr>
                  <tr><td>Loose Balls</td><td>{fmtInt(t!.looseBallsRecovered)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Paint / Transition
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Paint Pts</td><td>{fmtInt(t!.paintPoints)}</td></tr>
                  <tr><td>Fastbreak Pts</td><td>{fmtInt(t!.fastbreakPoints)}</td></tr>
                  <tr><td>2nd Chance Pts</td><td>{fmtInt(t!.secondChancePoints)}</td></tr>
                  <tr><td>Pts Off TO</td><td>{fmtInt(t!.pointsOffTurnovers)}</td></tr>
                  <tr><td>Bench Pts</td><td>{fmtInt(t!.benchPoints)}</td></tr>
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Player Advanced Stats */}
      {playerStats && playerStats.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Player Advanced Stats
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
                        <th>TS%</th>
                        <th>eFG%</th>
                        <th>USG%</th>
                        <th>OFF RTG</th>
                        <th>DEF RTG</th>
                        <th>PIE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.players.map((p) => (
                        <tr key={p.playerName}>
                          <td>{p.playerName}</td>
                          <td>{fmtRating(p.minutes)}</td>
                          <td>{fmtPct(p.tsPct)}</td>
                          <td>{fmtPct(p.efgPct)}</td>
                          <td>{fmtPct(p.usgPct)}</td>
                          <td>{fmtRating(p.offRating)}</td>
                          <td>{fmtRating(p.defRating)}</td>
                          <td>{fmtPct(p.pie)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ overflowX: "auto", marginTop: "0.5rem" }}>
                  <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                    <thead>
                      <tr>
                        <th>Player</th>
                        <th>Touches</th>
                        <th>Speed</th>
                        <th>Distance</th>
                        <th>C.Shots</th>
                        <th>Deflections</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.players.map((p) => (
                        <tr key={`${p.playerName}-hustle`}>
                          <td>{p.playerName}</td>
                          <td>{fmtInt(p.touches)}</td>
                          <td>{fmtRating(p.speed)}</td>
                          <td>{fmtRating(p.distance)}</td>
                          <td>{fmtInt(p.contestedShots)}</td>
                          <td>{fmtInt(p.deflections)}</td>
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
