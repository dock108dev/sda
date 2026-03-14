"use client";

import { useMemo } from "react";
import type { AdminGameDetail } from "@/lib/api/sportsAdmin";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

type PlayerStatsSectionProps = {
  playerStats: AdminGameDetail["playerStats"];
  nhlSkaters: AdminGameDetail["nhlSkaters"];
  nhlGoalies: AdminGameDetail["nhlGoalies"];
  mlbBatters: AdminGameDetail["mlbBatters"];
  mlbPitchers: AdminGameDetail["mlbPitchers"];
  mlbPitcherGameStats?: AdminGameDetail["mlbPitcherGameStats"];
  isNHL: boolean;
  isMLB: boolean;
};

const fmtPct = (v: number | null | undefined): string => (v != null ? `${(v * 100).toFixed(1)}%` : "—");
const fmtNum = (v: number | null | undefined, decimals = 1): string => (v != null ? v.toFixed(decimals) : "—");

export function PlayerStatsSection({ playerStats, nhlSkaters, nhlGoalies, mlbBatters, mlbPitchers, mlbPitcherGameStats, isNHL, isMLB }: PlayerStatsSectionProps) {
  const playerStatsByTeam = useMemo(() => {
    return playerStats.reduce<Record<string, typeof playerStats>>((acc, p) => {
      acc[p.team] = acc[p.team] || [];
      acc[p.team].push(p);
      return acc;
    }, {});
  }, [playerStats]);

  const nhlSkatersByTeam = useMemo(() => {
    if (!nhlSkaters) return {};
    return nhlSkaters.reduce<Record<string, NonNullable<typeof nhlSkaters>>>((acc, p) => {
      acc[p.team] = acc[p.team] || [];
      acc[p.team].push(p);
      return acc;
    }, {});
  }, [nhlSkaters]);

  const nhlGoaliesByTeam = useMemo(() => {
    if (!nhlGoalies) return {};
    return nhlGoalies.reduce<Record<string, NonNullable<typeof nhlGoalies>>>((acc, p) => {
      acc[p.team] = acc[p.team] || [];
      acc[p.team].push(p);
      return acc;
    }, {});
  }, [nhlGoalies]);

  const mlbBattersByTeam = useMemo(() => {
    if (!mlbBatters) return {};
    return mlbBatters.reduce<Record<string, NonNullable<typeof mlbBatters>>>((acc, p) => {
      acc[p.team] = acc[p.team] || [];
      acc[p.team].push(p);
      return acc;
    }, {});
  }, [mlbBatters]);

  const mlbPitchersByTeam = useMemo(() => {
    if (!mlbPitchers) return {};
    return mlbPitchers.reduce<Record<string, NonNullable<typeof mlbPitchers>>>((acc, p) => {
      acc[p.team] = acc[p.team] || [];
      acc[p.team].push(p);
      return acc;
    }, {});
  }, [mlbPitchers]);

  const mlbPitcherGameStatsByTeam = useMemo(() => {
    if (!mlbPitcherGameStats) return {};
    return mlbPitcherGameStats.reduce<Record<string, NonNullable<typeof mlbPitcherGameStats>>>((acc, p) => {
      acc[p.team] = acc[p.team] || [];
      acc[p.team].push(p);
      return acc;
    }, {});
  }, [mlbPitcherGameStats]);

  return (
    <CollapsibleSection title="Player Stats" defaultOpen={false}>
      {isNHL ? (
        // NHL-specific player stats display - one card per team with skaters + goalies
        Object.keys(nhlSkatersByTeam).length === 0 && Object.keys(nhlGoaliesByTeam).length === 0 ? (
          <div style={{ color: "#475569" }}>No player stats found.</div>
        ) : (
          <div className={styles.playerStatsGrid}>
            {/* Get unique teams from both skaters and goalies */}
            {Array.from(new Set([...Object.keys(nhlSkatersByTeam), ...Object.keys(nhlGoaliesByTeam)])).map((team) => (
              <div key={team} className={styles.teamStatsCard}>
                <div className={styles.teamStatsHeader}>
                  <h3>{team}</h3>
                </div>

                {/* Skaters section */}
                {nhlSkatersByTeam[team] && nhlSkatersByTeam[team].length > 0 && (
                  <>
                    <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.9rem", color: "#475569" }}>Skaters</h4>
                    <div style={{ overflowX: "auto" }}>
                      <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                        <thead>
                          <tr>
                            <th>Player</th>
                            <th>TOI</th>
                            <th>G</th>
                            <th>A</th>
                            <th>Pts</th>
                            <th>+/-</th>
                            <th>SOG</th>
                            <th>Hits</th>
                            <th>BLK</th>
                            <th>PIM</th>
                          </tr>
                        </thead>
                        <tbody>
                          {nhlSkatersByTeam[team].map((p, idx) => (
                            <tr key={`${team}-skater-${idx}-${p.playerName}`}>
                              <td>{p.playerName}</td>
                              <td>{p.toi ?? "—"}</td>
                              <td>{p.goals ?? "—"}</td>
                              <td>{p.assists ?? "—"}</td>
                              <td>{p.points ?? "—"}</td>
                              <td>{p.plusMinus ?? "—"}</td>
                              <td>{p.shotsOnGoal ?? "—"}</td>
                              <td>{p.hits ?? "—"}</td>
                              <td>{p.blockedShots ?? "—"}</td>
                              <td>{p.penaltyMinutes ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}

                {/* Goalies section */}
                {nhlGoaliesByTeam[team] && nhlGoaliesByTeam[team].length > 0 && (
                  <>
                    <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.9rem", color: "#475569" }}>Goalies</h4>
                    <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                      <thead>
                        <tr>
                          <th>Player</th>
                          <th>TOI</th>
                          <th>SA</th>
                          <th>SV</th>
                          <th>GA</th>
                          <th>SV%</th>
                        </tr>
                      </thead>
                      <tbody>
                        {nhlGoaliesByTeam[team].map((p, idx) => (
                          <tr key={`${team}-goalie-${idx}-${p.playerName}`}>
                            <td>{p.playerName}</td>
                            <td>{p.toi ?? "—"}</td>
                            <td>{p.shotsAgainst ?? "—"}</td>
                            <td>{p.saves ?? "—"}</td>
                            <td>{p.goalsAgainst ?? "—"}</td>
                            <td>{p.savePercentage != null ? `${(p.savePercentage * 100).toFixed(1)}%` : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </div>
            ))}
          </div>
        )
      ) : isMLB ? (
        // MLB-specific player stats display - one card per team with batters + pitchers
        Object.keys(mlbBattersByTeam).length === 0 && Object.keys(mlbPitchersByTeam).length === 0 ? (
          <div style={{ color: "#475569" }}>No player stats found.</div>
        ) : (
          <div className={styles.playerStatsGrid}>
            {Array.from(new Set([...Object.keys(mlbBattersByTeam), ...Object.keys(mlbPitchersByTeam)])).map((team) => (
              <div key={team} className={styles.teamStatsCard}>
                <div className={styles.teamStatsHeader}>
                  <h3>{team}</h3>
                </div>

                {/* Batters section */}
                {mlbBattersByTeam[team] && mlbBattersByTeam[team].length > 0 && (
                  <>
                    <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.9rem", color: "#475569" }}>Batters</h4>
                    <div style={{ overflowX: "auto" }}>
                      <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                        <thead>
                          <tr>
                            <th>Player</th>
                            <th>Pos</th>
                            <th>AB</th>
                            <th>H</th>
                            <th>R</th>
                            <th>RBI</th>
                            <th>HR</th>
                            <th>BB</th>
                            <th>SO</th>
                            <th>SB</th>
                            <th>AVG</th>
                            <th>OBP</th>
                            <th>SLG</th>
                            <th>OPS</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mlbBattersByTeam[team].map((p, idx) => (
                            <tr key={`${team}-batter-${idx}-${p.playerName}`}>
                              <td>{p.playerName}</td>
                              <td>{p.position ?? "—"}</td>
                              <td>{p.atBats ?? "—"}</td>
                              <td>{p.hits ?? "—"}</td>
                              <td>{p.runs ?? "—"}</td>
                              <td>{p.rbi ?? "—"}</td>
                              <td>{p.homeRuns ?? "—"}</td>
                              <td>{p.baseOnBalls ?? "—"}</td>
                              <td>{p.strikeOuts ?? "—"}</td>
                              <td>{p.stolenBases ?? "—"}</td>
                              <td>{p.avg ?? "—"}</td>
                              <td>{p.obp ?? "—"}</td>
                              <td>{p.slg ?? "—"}</td>
                              <td>{p.ops ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}

                {/* Pitchers section */}
                {mlbPitchersByTeam[team] && mlbPitchersByTeam[team].length > 0 && (
                  <>
                    <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.9rem", color: "#475569" }}>Pitchers</h4>
                    <div style={{ overflowX: "auto" }}>
                      <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                        <thead>
                          <tr>
                            <th>Player</th>
                            <th>IP</th>
                            <th>H</th>
                            <th>R</th>
                            <th>ER</th>
                            <th>BB</th>
                            <th>SO</th>
                            <th>HR</th>
                            <th>ERA</th>
                            <th>PC</th>
                            <th>STR</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mlbPitchersByTeam[team].map((p, idx) => (
                            <tr key={`${team}-pitcher-${idx}-${p.playerName}`}>
                              <td>{p.playerName}</td>
                              <td>{p.inningsPitched ?? "—"}</td>
                              <td>{p.hits ?? "—"}</td>
                              <td>{p.runs ?? "—"}</td>
                              <td>{p.earnedRuns ?? "—"}</td>
                              <td>{p.baseOnBalls ?? "—"}</td>
                              <td>{p.strikeOuts ?? "—"}</td>
                              <td>{p.homeRuns ?? "—"}</td>
                              <td>{p.era ?? "—"}</td>
                              <td>{p.pitchCount ?? "—"}</td>
                              <td>{p.strikes ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}

                {/* Pitcher Advanced (Statcast) */}
                {mlbPitcherGameStatsByTeam[team] && mlbPitcherGameStatsByTeam[team].length > 0 && (
                  <>
                    <h4 style={{ margin: "0.75rem 0 0.25rem", fontSize: "0.9rem", color: "#475569" }}>Pitcher Advanced (Statcast)</h4>
                    <div style={{ overflowX: "auto" }}>
                      <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                        <thead>
                          <tr>
                            <th>Player</th>
                            <th>K%</th>
                            <th>BB%</th>
                            <th>Whiff%</th>
                            <th>Zone Contact%</th>
                            <th>Chase%</th>
                            <th>Exit Velo Against</th>
                            <th>Hard Hit% Against</th>
                            <th>Barrel% Against</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mlbPitcherGameStatsByTeam[team].map((p, idx) => (
                            <tr key={`${team}-adv-pitcher-${idx}-${p.playerName}`}>
                              <td>{p.playerName}{p.isStarter ? " (S)" : ""}</td>
                              <td>{fmtPct(p.kRate)}</td>
                              <td>{fmtPct(p.bbRate)}</td>
                              <td>{fmtPct(p.whiffRate)}</td>
                              <td>{fmtPct(p.zContactPct)}</td>
                              <td>{fmtPct(p.chaseRate)}</td>
                              <td>{fmtNum(p.avgExitVeloAgainst)}</td>
                              <td>{fmtPct(p.hardHitPctAgainst)}</td>
                              <td>{fmtPct(p.barrelPctAgainst)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        )
      ) : (
        // Generic player stats (NBA, NCAAB, etc.)
        Object.keys(playerStatsByTeam).length === 0 ? (
          <div style={{ color: "#475569" }}>No player stats found.</div>
        ) : (
          <div className={styles.playerStatsGrid}>
            {Object.entries(playerStatsByTeam).map(([team, rows]) => {
              // Helper to coerce value to number (handles numeric strings)
              const toNumber = (v: unknown): number | null => {
                if (typeof v === "number") return v;
                if (typeof v === "string") {
                  const parsed = Number(v);
                  return isNaN(parsed) ? null : parsed;
                }
                return null;
              };

              // Helper to get stat from raw_stats - handles both flat and nested formats
              const getStat = (p: typeof rows[0], ...keys: string[]): number | null => {
                for (const key of keys) {
                  const val = p.rawStats?.[key];
                  if (val !== null && val !== undefined) {
                    // Direct number or numeric string
                    const num = toNumber(val);
                    if (num !== null) return num;
                    // Nested object formats (CBB API)
                    if (typeof val === "object" && !Array.isArray(val)) {
                      const obj = val as Record<string, unknown>;
                      // Try "total" key first (points, rebounds, etc.)
                      const total = toNumber(obj.total);
                      if (total !== null) return total;
                      // Try "personal" key for fouls
                      const personal = toNumber(obj.personal);
                      if (personal !== null) return personal;
                    }
                  }
                }
                return null;
              };
              // Format shooting stat as "made/att" - handles multiple formats
              const formatShootingStat = (
                p: typeof rows[0],
                flatMadeKey: string,
                flatAttKey: string,
                nestedKey: string,
              ): string => {
                // First try flat keys (from updated scraper)
                let made = getStat(p, flatMadeKey);
                let att = getStat(p, flatAttKey);

                // Fallback: try nested CBB API format (e.g., fieldGoals: {made: X, attempted: Y})
                if (made === null && att === null) {
                  const nested = p.rawStats?.[nestedKey];
                  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
                    const obj = nested as Record<string, unknown>;
                    made = toNumber(obj.made);
                    att = toNumber(obj.attempted);
                  }
                }

                // Return "—" if we don't have complete data (both made and att)
                // Partial data like "5/null" would be misleading
                if (made === null || att === null) return "—";
                return `${made}/${att}`;
              };
              return (
                <div key={team} className={styles.teamStatsCard}>
                  <div className={styles.teamStatsHeader}>
                    <h3>{team}</h3>
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                      <thead>
                        <tr>
                          <th>Player</th>
                          <th>Min</th>
                          <th>Pts</th>
                          <th>Reb</th>
                          <th>Ast</th>
                          <th>Stl</th>
                          <th>Blk</th>
                          <th>TO</th>
                          <th>FG</th>
                          <th>3PT</th>
                          <th>FT</th>
                          <th>PF</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((p, idx) => (
                          <tr key={`${team}-${idx}-${p.playerName}`}>
                            <td>{p.playerName}</td>
                            <td>{p.minutes != null ? Math.round(p.minutes) : "—"}</td>
                            <td>{p.points ?? "—"}</td>
                            <td>{p.rebounds ?? getStat(p, "rebounds", "totalRebounds") ?? "—"}</td>
                            <td>{p.assists ?? "—"}</td>
                            <td>{getStat(p, "steals") ?? "—"}</td>
                            <td>{getStat(p, "blocks", "blocked_shots") ?? "—"}</td>
                            <td>{getStat(p, "turnovers") ?? "—"}</td>
                            <td>{formatShootingStat(p, "fgMade", "fgAttempted", "fieldGoals")}</td>
                            <td>{formatShootingStat(p, "fg3Made", "fg3Attempted", "threePointFieldGoals")}</td>
                            <td>{formatShootingStat(p, "ftMade", "ftAttempted", "freeThrows")}</td>
                            <td>{getStat(p, "fouls", "personalFouls") ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}
    </CollapsibleSection>
  );
}
