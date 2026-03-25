"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminCard } from "@/components/admin";
import {
  runSimulation,
  listTeams,
  getMLBRoster,
  type SimulationRequest,
  type SimulationResult,
  type MLBTeam,
  type RosterBatter,
  type RosterPitcher,
} from "@/lib/api/analytics";
import { SportSelector } from "@/components/admin/SportSelector";
import { SPORT_CONFIGS, type AnalyticsSport } from "@/lib/constants/analytics";
import styles from "../analytics.module.css";
import { LineupEditor, type LineupSlot } from "./LineupEditor";
import { TeamProfileComparison } from "./TeamProfileComparison";
import { SimulationResults } from "./SimulationResults";

interface StarterSlot {
  external_ref: string;
  name: string;
  avg_ip?: number;
}

export function PregameSimulator() {
  const [sport, setSport] = useState<AnalyticsSport>("MLB");
  const sportCode = sport.toLowerCase();
  const sportConfig = SPORT_CONFIGS[sport] || SPORT_CONFIGS.MLB;
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [iterations, setIterations] = useState(5000);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // MLB teams for dropdowns
  const [teams, setTeams] = useState<MLBTeam[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(true);

  // Playoff exclusion
  const [excludePlayoffs, setExcludePlayoffs] = useState(false);

  // Sportsbook comparison
  const [homeMoneyline, setHomeMoneyline] = useState("");
  const [awayMoneyline, setAwayMoneyline] = useState("");

  // Lineup mode
  const [useLineup, setUseLineup] = useState(false);
  const [homeLineup, setHomeLineup] = useState<LineupSlot[]>([]);
  const [awayLineup, setAwayLineup] = useState<LineupSlot[]>([]);
  const [homeStarter, setHomeStarter] = useState<StarterSlot | null>(null);
  const [awayStarter, setAwayStarter] = useState<StarterSlot | null>(null);
  const [starterInnings, setStarterInnings] = useState(6);

  // Roster data for selectors
  const [homeBatters, setHomeBatters] = useState<RosterBatter[]>([]);
  const [awayBatters, setAwayBatters] = useState<RosterBatter[]>([]);
  const [homePitchers, setHomePitchers] = useState<RosterPitcher[]>([]);
  const [awayPitchers, setAwayPitchers] = useState<RosterPitcher[]>([]);
  const [rosterLoading, setRosterLoading] = useState(false);

  // Load teams when sport changes
  useEffect(() => {
    setTeams([]);
    setTeamsLoading(true);
    setHomeTeam("");
    setAwayTeam("");
    setResult(null);
    setError(null);
    setUseLineup(false);
    (async () => {
      try {
        const res = await listTeams(sportCode);
        setTeams(res.teams);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load teams");
      } finally {
        setTeamsLoading(false);
      }
    })();
  }, [sportCode]);

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
          setHomeStarter({ external_ref: top.external_ref, name: top.name, avg_ip: top.avg_ip });
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
          setAwayStarter({ external_ref: top.external_ref, name: top.name, avg_ip: top.avg_ip });
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
        sport: sportCode,
        home_team: homeTeam,
        away_team: awayTeam,
        iterations,
        probability_mode: sportConfig.defaultProbMode as SimulationRequest["probability_mode"],
        exclude_playoffs: excludePlayoffs || undefined,
      };
      // Sportsbook lines
      if (homeMoneyline && awayMoneyline) {
        req.sportsbook = {
          home_moneyline: parseFloat(homeMoneyline),
          away_moneyline: parseFloat(awayMoneyline),
        };
      }
      if (useLineup && lineupFilled(homeLineup) && lineupFilled(awayLineup)) {
        req.home_lineup = homeLineup;
        req.away_lineup = awayLineup;
        if (homeStarter) req.home_starter = { external_ref: homeStarter.external_ref, name: homeStarter.name, avg_ip: homeStarter.avg_ip };
        if (awayStarter) req.away_starter = { external_ref: awayStarter.external_ref, name: awayStarter.name, avg_ip: awayStarter.avg_ip };
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
      <SportSelector value={sport} onChange={setSport} />
      <AdminCard title="Pregame Setup">
        <div className={styles.formRow}>
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
          <div className={styles.formGroup}>
            <label>Iterations</label>
            <input type="number" value={iterations} onChange={(e) => setIterations(Math.max(100, parseInt(e.target.value) || 100))} min={100} max={50000} />
          </div>
        </div>

        {/* Lineup Mode Toggle (MLB only) */}
        {sportConfig.hasLineupMode && (
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
        )}

        {/* Exclude Playoffs Toggle */}
        <div className={styles.formRow} style={{ marginTop: "0.5rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={excludePlayoffs}
              onChange={(e) => setExcludePlayoffs(e.target.checked)}
            />
            <span style={{ fontWeight: 500 }}>Exclude playoff games</span>
            <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              — only use regular season data for profiles
            </span>
          </label>
        </div>

        {/* Sportsbook Lines (optional) */}
        <div className={styles.formRow} style={{ marginTop: "0.5rem" }}>
          <div className={styles.formGroup}>
            <label>Home Moneyline (optional)</label>
            <input
              type="number"
              placeholder="e.g. -150"
              value={homeMoneyline}
              onChange={(e) => setHomeMoneyline(e.target.value)}
            />
          </div>
          <div className={styles.formGroup}>
            <label>Away Moneyline (optional)</label>
            <input
              type="number"
              placeholder="e.g. +130"
              value={awayMoneyline}
              onChange={(e) => setAwayMoneyline(e.target.value)}
            />
          </div>
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

      {/* Lineup Configuration (MLB only) */}
      {sportConfig.hasLineupMode && useLineup && homeTeam && awayTeam && (
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
                  setHomeStarter(p ? { external_ref: p.external_ref, name: p.name, avg_ip: p.avg_ip } : null);
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
                  setAwayStarter(p ? { external_ref: p.external_ref, name: p.name, avg_ip: p.avg_ip } : null);
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

      {sportConfig.hasLineupMode && useLineup && homeTeam && awayTeam && (
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

      {/* Team Profile Comparison (shows when both teams selected) */}
      {homeTeam && awayTeam && homeTeam !== awayTeam && (
        <TeamProfileComparison homeTeam={homeTeam} awayTeam={awayTeam} sport={sportCode} />
      )}

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <SimulationResults
          result={result}
          homeMoneyline={homeMoneyline}
          awayMoneyline={awayMoneyline}
          sport={sportCode}
        />
      )}
    </>
  );
}
