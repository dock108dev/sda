"use client";

import type { NHLAdvancedTeamStats, NHLSkaterAdvancedStats, NHLGoalieAdvancedStats } from "@/lib/api/sportsAdmin/types";
import { fmtPct, fmtNum } from "@/lib/utils/formatting";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

function fmtRating(v: number | null | undefined, decimals = 2): string {
  return v != null ? v.toFixed(decimals) : "—";
}

export function NHLAdvancedStatsSection({
  teamStats,
  skaterStats,
  goalieStats,
}: {
  teamStats?: NHLAdvancedTeamStats[] | null;
  skaterStats?: NHLSkaterAdvancedStats[] | null;
  goalieStats?: NHLGoalieAdvancedStats[] | null;
}) {
  const awayTeam = (teamStats ?? []).find((t) => !t.isHome);
  const homeTeam = (teamStats ?? []).find((t) => t.isHome);
  const teamOrder = [awayTeam, homeTeam].filter(Boolean) as NHLAdvancedTeamStats[];

  const awaySkaters = (skaterStats ?? [])
    .filter((p) => !p.isHome)
    .sort((a, b) => (b.gameScore ?? 0) - (a.gameScore ?? 0));

  const homeSkaters = (skaterStats ?? [])
    .filter((p) => p.isHome)
    .sort((a, b) => (b.gameScore ?? 0) - (a.gameScore ?? 0));

  return (
    <CollapsibleSection title="Advanced Stats (NHL)" defaultOpen={false}>
      {/* Team Comparison */}
      {teamOrder.length > 0 && (
        <div className={styles.teamStatsGrid}>
          {teamOrder.map((t) => (
            <div key={t.team} className={styles.teamStatsCard}>
              <div className={styles.teamStatsHeader}>
                <h3>{t.team}</h3>
                <span className={styles.badge}>{t.isHome ? "Home" : "Away"}</span>
              </div>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Shot Quality
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>xGF</td><td>{fmtRating(t.xgoalsFor)}</td></tr>
                  <tr><td>xGA</td><td>{fmtRating(t.xgoalsAgainst)}</td></tr>
                  <tr><td>xG%</td><td>{fmtPct(t.xgoalsPct)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Possession
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>CF</td><td>{fmtNum(t.corsiFor, 0)}</td></tr>
                  <tr><td>CA</td><td>{fmtNum(t.corsiAgainst, 0)}</td></tr>
                  <tr><td>CF%</td><td>{fmtPct(t.corsiPct)}</td></tr>
                  <tr><td>FF</td><td>{fmtNum(t.fenwickFor, 0)}</td></tr>
                  <tr><td>FA</td><td>{fmtNum(t.fenwickAgainst, 0)}</td></tr>
                  <tr><td>FF%</td><td>{fmtPct(t.fenwickPct)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                Shooting
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>Shots For</td><td>{fmtNum(t.shotsFor, 0)}</td></tr>
                  <tr><td>Shots Against</td><td>{fmtNum(t.shotsAgainst, 0)}</td></tr>
                  <tr><td>Shooting %</td><td>{fmtPct(t.shootingPct)}</td></tr>
                  <tr><td>Save %</td><td>{fmtPct(t.savePct)}</td></tr>
                  <tr><td>PDO</td><td>{fmtRating(t.pdo)}</td></tr>
                </tbody>
              </table>

              <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.85rem", color: "#64748b" }}>
                High Danger
              </h4>
              <table className={styles.table}>
                <tbody>
                  <tr><td>HD Shots For</td><td>{fmtNum(t.highDangerShotsFor, 0)}</td></tr>
                  <tr><td>HD Goals For</td><td>{fmtNum(t.highDangerGoalsFor, 0)}</td></tr>
                  <tr><td>HD Shots Against</td><td>{fmtNum(t.highDangerShotsAgainst, 0)}</td></tr>
                  <tr><td>HD Goals Against</td><td>{fmtNum(t.highDangerGoalsAgainst, 0)}</td></tr>
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Skater Stats */}
      {skaterStats && skaterStats.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Skater Stats
          </h3>
          {[
            { label: "Away", players: awaySkaters },
            { label: "Home", players: homeSkaters },
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
                        <th>xGF</th>
                        <th>xGA</th>
                        <th>xG%</th>
                        <th>SOG</th>
                        <th>G</th>
                        <th>SH%</th>
                        <th>G/60</th>
                        <th>A/60</th>
                        <th>P/60</th>
                        <th>GS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.players.map((p) => (
                        <tr key={p.playerName}>
                          <td>{p.playerName}</td>
                          <td>{fmtRating(p.xgoalsFor)}</td>
                          <td>{fmtRating(p.xgoalsAgainst)}</td>
                          <td>{fmtPct(p.onIceXgoalsPct)}</td>
                          <td>{p.shots ?? "—"}</td>
                          <td>{p.goals ?? "—"}</td>
                          <td>{fmtPct(p.shootingPct)}</td>
                          <td>{fmtRating(p.goalsPer60)}</td>
                          <td>{fmtRating(p.assistsPer60)}</td>
                          <td>{fmtRating(p.pointsPer60)}</td>
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

      {/* Goalie Stats */}
      {goalieStats && goalieStats.length > 0 && (
        <>
          <h3 style={{ margin: "1.5rem 0 0.75rem", fontSize: "1rem", color: "#1e293b" }}>
            Goalie Stats
          </h3>
          <div style={{ overflowX: "auto" }}>
            <table className={styles.table} style={{ fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th>Goalie</th>
                  <th>SA</th>
                  <th>GA</th>
                  <th>xGA</th>
                  <th>GSAx</th>
                  <th>SV%</th>
                  <th>HD SV%</th>
                </tr>
              </thead>
              <tbody>
                {goalieStats.map((g) => (
                  <tr key={`${g.team}-${g.playerName}`}>
                    <td>{g.playerName} <span className={styles.badge}>{g.isHome ? "Home" : "Away"}</span></td>
                    <td>{g.shotsAgainst ?? "—"}</td>
                    <td>{g.goalsAgainst ?? "—"}</td>
                    <td>{fmtRating(g.xgoalsAgainst)}</td>
                    <td>{fmtRating(g.goalsSavedAboveExpected)}</td>
                    <td>{fmtPct(g.savePct)}</td>
                    <td>{fmtPct(g.highDangerSavePct)}</td>
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
