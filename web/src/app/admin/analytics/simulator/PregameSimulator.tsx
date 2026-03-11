"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard } from "@/components/admin";
import {
  runSimulation,
  listMLBTeams,
  getMLBRoster,
  type SimulationResult,
  type MLBTeam,
  type RosterBatter,
  type RosterPitcher,
} from "@/lib/api/analytics";
import { ScoreDistributionChart, PAProbabilitiesChart } from "../charts";
import styles from "../analytics.module.css";

interface LineupSlot {
  external_ref: string;
  name: string;
}

export function PregameSimulator() {
  const [sport] = useState("mlb");
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [iterations, setIterations] = useState(5000);
  const [rollingWindow, setRollingWindow] = useState(30);
  const [probabilityMode, setProbabilityMode] = useState<"ml" | "ensemble">("ml");
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // MLB teams for dropdowns
  const [teams, setTeams] = useState<MLBTeam[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(true);

  // Lineup mode
  const [useLineup, setUseLineup] = useState(false);
  const [homeLineup, setHomeLineup] = useState<LineupSlot[]>([]);
  const [awayLineup, setAwayLineup] = useState<LineupSlot[]>([]);
  const [homeStarter, setHomeStarter] = useState<LineupSlot | null>(null);
  const [awayStarter, setAwayStarter] = useState<LineupSlot | null>(null);
  const [starterInnings, setStarterInnings] = useState(6);

  // Roster data for selectors
  const [homeBatters, setHomeBatters] = useState<RosterBatter[]>([]);
  const [awayBatters, setAwayBatters] = useState<RosterBatter[]>([]);
  const [homePitchers, setHomePitchers] = useState<RosterPitcher[]>([]);
  const [awayPitchers, setAwayPitchers] = useState<RosterPitcher[]>([]);
  const [rosterLoading, setRosterLoading] = useState(false);

  // Load teams on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await listMLBTeams();
        setTeams(res.teams);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load teams");
      } finally {
        setTeamsLoading(false);
      }
    })();
  }, []);

  // Load roster when teams change and lineup mode is on
  const loadRoster = useCallback(async (team: string, side: "home" | "away") => {
    if (!team) return;
    setRosterLoading(true);
    try {
      const roster = await getMLBRoster(team);
      if (side === "home") {
        setHomeBatters(roster.batters || []);
        setHomePitchers(roster.pitchers || []);
        // Auto-fill lineup with top 9 batters by games played
        if (roster.batters && roster.batters.length >= 9) {
          setHomeLineup(
            roster.batters.slice(0, 9).map((b) => ({
              external_ref: b.external_ref,
              name: b.name,
            })),
          );
        }
        // Auto-fill starter with top pitcher
        if (roster.pitchers && roster.pitchers.length > 0) {
          const top = roster.pitchers[0];
          setHomeStarter({ external_ref: top.external_ref, name: top.name });
        }
      } else {
        setAwayBatters(roster.batters || []);
        setAwayPitchers(roster.pitchers || []);
        if (roster.batters && roster.batters.length >= 9) {
          setAwayLineup(
            roster.batters.slice(0, 9).map((b) => ({
              external_ref: b.external_ref,
              name: b.name,
            })),
          );
        }
        if (roster.pitchers && roster.pitchers.length > 0) {
          const top = roster.pitchers[0];
          setAwayStarter({ external_ref: top.external_ref, name: top.name });
        }
      }
    } catch {
      setError(`Failed to load roster for ${team}`);
    } finally {
      setRosterLoading(false);
    }
  }, []);

  useEffect(() => {
    if (useLineup && homeTeam) loadRoster(homeTeam, "home");
  }, [homeTeam, useLineup, loadRoster]);

  useEffect(() => {
    if (useLineup && awayTeam) loadRoster(awayTeam, "away");
  }, [awayTeam, useLineup, loadRoster]);

  const teamsWithStats = teams.filter((t) => t.games_with_stats > 0);

  const lineupFilled = (lineup: LineupSlot[]) =>
    lineup.length === 9 && lineup.every((s) => s?.external_ref);

  const lineupValid = !useLineup || (lineupFilled(homeLineup) && lineupFilled(awayLineup));

  async function handleSimulate() {
    if (!homeTeam || !awayTeam) return;
    setLoading(true);
    setError(null);
    try {
      const req: Parameters<typeof runSimulation>[0] = {
        sport,
        home_team: homeTeam,
        away_team: awayTeam,
        iterations,
        probability_mode: probabilityMode,
        rolling_window: rollingWindow,
      };
      if (useLineup && lineupFilled(homeLineup) && lineupFilled(awayLineup)) {
        req.home_lineup = homeLineup;
        req.away_lineup = awayLineup;
        if (homeStarter) req.home_starter = homeStarter;
        if (awayStarter) req.away_starter = awayStarter;
        req.starter_innings = starterInnings;
      }
      const res = await runSimulation(req);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function updateLineupSlot(
    side: "home" | "away",
    index: number,
    ref: string,
  ) {
    const batters = side === "home" ? homeBatters : awayBatters;
    const batter = batters.find((b) => b.external_ref === ref);
    if (!batter) return;
    const slot: LineupSlot = { external_ref: batter.external_ref, name: batter.name };

    const update = (prev: LineupSlot[]) => {
      // Ensure dense 9-slot array — never sparse
      const next = Array.from({ length: 9 }, (_, i) => prev[i] ?? { external_ref: "", name: "" });
      next[index] = slot;
      return next;
    };

    if (side === "home") {
      setHomeLineup(update);
    } else {
      setAwayLineup(update);
    }
  }

  return (
    <>
      <AdminCard title="Pregame Setup">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} disabled>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Home Team</label>
            {teamsLoading ? (
              <select disabled><option>Loading...</option></select>
            ) : (
              <select value={homeTeam} onChange={(e) => setHomeTeam(e.target.value)}>
                <option value="">Select home team</option>
                {teamsWithStats.map((t) => (
                  <option key={t.id} value={t.abbreviation} disabled={t.abbreviation === awayTeam}>
                    {t.abbreviation} — {t.name} ({t.games_with_stats} games)
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className={styles.formGroup}>
            <label>Away Team</label>
            {teamsLoading ? (
              <select disabled><option>Loading...</option></select>
            ) : (
              <select value={awayTeam} onChange={(e) => setAwayTeam(e.target.value)}>
                <option value="">Select away team</option>
                {teamsWithStats.map((t) => (
                  <option key={t.id} value={t.abbreviation} disabled={t.abbreviation === homeTeam}>
                    {t.abbreviation} — {t.name} ({t.games_with_stats} games)
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Iterations</label>
            <input type="number" value={iterations} onChange={(e) => setIterations(Math.max(100, parseInt(e.target.value) || 100))} min={100} max={50000} />
          </div>
          <div className={styles.formGroup}>
            <label>Rolling Window: {rollingWindow}</label>
            <input type="range" min={5} max={80} step={5} value={rollingWindow} onChange={(e) => setRollingWindow(parseInt(e.target.value))} />
          </div>
          <div className={styles.formGroup}>
            <label>Probability Mode</label>
            <select value={probabilityMode} onChange={(e) => setProbabilityMode(e.target.value as "ml" | "ensemble")}>
              <option value="ml">ML Model</option>
              <option value="ensemble">Ensemble</option>
            </select>
          </div>
        </div>

        {/* Lineup Mode Toggle */}
        <div className={styles.formRow} style={{ marginTop: "0.75rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={useLineup}
              onChange={(e) => setUseLineup(e.target.checked)}
            />
            <span style={{ fontWeight: 500 }}>Lineup Mode</span>
            <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              — per-batter probabilities using Statcast profiles
            </span>
          </label>
        </div>

        <div className={styles.formRow} style={{ marginTop: "0.75rem" }}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleSimulate}
            disabled={loading || !homeTeam || !awayTeam || homeTeam === awayTeam || !lineupValid}
          >
            {loading ? "Simulating..." : "Run Simulation"}
          </button>
          {homeTeam && awayTeam && homeTeam === awayTeam && (
            <span style={{ color: "#ef4444", fontSize: "0.85rem" }}>Home and away must be different teams</span>
          )}
          {rosterLoading && (
            <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Loading rosters...</span>
          )}
        </div>
      </AdminCard>

      {/* Lineup Configuration */}
      {useLineup && homeTeam && awayTeam && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <AdminCard title={`${homeTeam} Lineup`} subtitle="Home batting order">
            <LineupEditor
              lineup={homeLineup}
              batters={homeBatters}
              onChange={(idx, ref) => updateLineupSlot("home", idx, ref)}
            />
            <div style={{ marginTop: "0.75rem" }}>
              <label style={{ fontSize: "0.85rem", fontWeight: 500 }}>Starting Pitcher</label>
              <select
                value={homeStarter?.external_ref || ""}
                onChange={(e) => {
                  const p = homePitchers.find((p) => p.external_ref === e.target.value);
                  setHomeStarter(p ? { external_ref: p.external_ref, name: p.name } : null);
                }}
                style={{ width: "100%", marginTop: "0.25rem" }}
              >
                <option value="">Select SP</option>
                {homePitchers.map((p) => (
                  <option key={p.external_ref} value={p.external_ref}>
                    {p.name} ({p.games}G, {p.avg_ip.toFixed(1)} avg IP)
                  </option>
                ))}
              </select>
            </div>
          </AdminCard>
          <AdminCard title={`${awayTeam} Lineup`} subtitle="Away batting order">
            <LineupEditor
              lineup={awayLineup}
              batters={awayBatters}
              onChange={(idx, ref) => updateLineupSlot("away", idx, ref)}
            />
            <div style={{ marginTop: "0.75rem" }}>
              <label style={{ fontSize: "0.85rem", fontWeight: 500 }}>Starting Pitcher</label>
              <select
                value={awayStarter?.external_ref || ""}
                onChange={(e) => {
                  const p = awayPitchers.find((p) => p.external_ref === e.target.value);
                  setAwayStarter(p ? { external_ref: p.external_ref, name: p.name } : null);
                }}
                style={{ width: "100%", marginTop: "0.25rem" }}
              >
                <option value="">Select SP</option>
                {awayPitchers.map((p) => (
                  <option key={p.external_ref} value={p.external_ref}>
                    {p.name} ({p.games}G, {p.avg_ip.toFixed(1)} avg IP)
                  </option>
                ))}
              </select>
            </div>
          </AdminCard>
        </div>
      )}

      {useLineup && homeTeam && awayTeam && (
        <AdminCard title="Bullpen Transition">
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label>Starter pitches through inning: {starterInnings}</label>
              <input
                type="range"
                min={4}
                max={9}
                step={1}
                value={starterInnings}
                onChange={(e) => setStarterInnings(parseInt(e.target.value))}
              />
              <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                Bullpen takes over after inning {starterInnings}
              </span>
            </div>
          </div>
        </AdminCard>
      )}

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <div className={styles.resultsSection}>
          <AdminCard title="Win Probability">
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.home_win_probability * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>{result.home_team} (Home)</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{(result.away_win_probability * 100).toFixed(1)}%</div>
                <div className={styles.statLabel}>{result.away_team} (Away)</div>
              </div>
            </div>
            <div className={styles.probBar}>
              <span className={styles.probLabel}>{result.home_team}</span>
              <div className={styles.probTrack}>
                <div className={styles.probFill} style={{ width: `${result.home_win_probability * 100}%` }} />
              </div>
              <span className={styles.probLabel} style={{ textAlign: "right" }}>{result.away_team}</span>
            </div>
            {!!result.profile_meta?.lineup_mode && (
              <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
                Lineup-aware simulation with per-batter matchup probabilities
              </p>
            )}
          </AdminCard>

          {result.model_home_win_probability != null && (
            <AdminCard title="Game Model Prediction" subtitle="Trained model win probability">
              <div className={styles.statsRow}>
                <div className={styles.statBox}>
                  <div className={styles.statValue}>{(result.model_home_win_probability * 100).toFixed(1)}%</div>
                  <div className={styles.statLabel}>{result.home_team} (Model)</div>
                </div>
                <div className={styles.statBox}>
                  <div className={styles.statValue}>{((1 - result.model_home_win_probability) * 100).toFixed(1)}%</div>
                  <div className={styles.statLabel}>{result.away_team} (Model)</div>
                </div>
              </div>
            </AdminCard>
          )}

          {result.home_pa_probabilities && result.away_pa_probabilities && (
            <AdminCard title="PA Probabilities" subtitle={`From rolling ${result.profile_meta?.rolling_window ?? 30}-game profiles`}>
              <PAProbabilitiesChart
                homeProbs={result.home_pa_probabilities}
                awayProbs={result.away_pa_probabilities}
                homeLabel={result.home_team}
                awayLabel={result.away_team}
              />
            </AdminCard>
          )}

          {result.profile_meta && !result.profile_meta.has_profiles && (
            <AdminCard title="Profile Status">
              <p style={{ color: "#ef4444", fontSize: "0.9rem" }}>
                Could not load team profiles. Using league-average defaults.
              </p>
            </AdminCard>
          )}

          <AdminCard title="Average Score" subtitle={`Based on ${result.iterations.toLocaleString()} simulations`}>
            <div className={styles.statsRow}>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.average_home_score}</div>
                <div className={styles.statLabel}>{result.home_team} Avg</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.average_away_score}</div>
                <div className={styles.statLabel}>{result.away_team} Avg</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.average_total}</div>
                <div className={styles.statLabel}>Avg Total</div>
              </div>
              <div className={styles.statBox}>
                <div className={styles.statValue}>{result.median_total}</div>
                <div className={styles.statLabel}>Median Total</div>
              </div>
            </div>
          </AdminCard>

          {result.most_common_scores && result.most_common_scores.length > 0 && (
            <AdminCard title="Most Common Scores">
              <ScoreDistributionChart data={result.most_common_scores} />
            </AdminCard>
          )}
        </div>
      )}
    </>
  );
}


function LineupEditor({
  lineup,
  batters,
  onChange,
}: {
  lineup: LineupSlot[];
  batters: RosterBatter[];
  onChange: (index: number, externalRef: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
      {Array.from({ length: 9 }, (_, i) => {
        const slot = lineup[i];
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ width: "24px", fontSize: "0.8rem", color: "var(--text-muted)", textAlign: "right" }}>
              {i + 1}.
            </span>
            <select
              value={slot?.external_ref || ""}
              onChange={(e) => onChange(i, e.target.value)}
              style={{ flex: 1, fontSize: "0.85rem" }}
            >
              <option value="">Select batter</option>
              {batters.map((b) => (
                <option key={b.external_ref} value={b.external_ref}>
                  {b.name} ({b.games_played}G)
                </option>
              ))}
            </select>
          </div>
        );
      })}
      {batters.length === 0 && (
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          No roster data available. Select a team first.
        </p>
      )}
    </div>
  );
}
