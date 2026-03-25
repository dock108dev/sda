"use client";

import { useState, useEffect } from "react";
import { listTeams, type MLBTeam } from "@/lib/api/analytics";
import { SportSelector } from "@/components/admin/SportSelector";
import { type AnalyticsSport } from "@/lib/constants/analytics";
import { TeamProfileComparison } from "../simulator/TeamProfileComparison";
import styles from "../analytics.module.css";

export default function ProfilesPage() {
  const [sport, setSport] = useState<AnalyticsSport>("MLB");
  const sportCode = sport.toLowerCase();
  const [teams, setTeams] = useState<MLBTeam[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(true);
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [rollingWindow, setRollingWindow] = useState(30);

  useEffect(() => {
    setTeams([]);
    setTeamsLoading(true);
    setHomeTeam("");
    setAwayTeam("");
    (async () => {
      try {
        const res = await listTeams(sportCode);
        setTeams(res.teams);
      } finally {
        setTeamsLoading(false);
      }
    })();
  }, [sportCode]);

  const teamsWithStats = teams.filter((t) => t.games_with_stats > 0);

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Team Profiles</h1>
        <p className={styles.pageSubtitle}>
          Compare team rolling profiles and scouting metrics
        </p>
      </header>

      <SportSelector value={sport} onChange={setSport} />

      <div className={styles.formRow}>
        <div className={styles.formGroup}>
          <label>Team A</label>
          {teamsLoading ? (
            <select disabled><option>Loading...</option></select>
          ) : (
            <select value={homeTeam} onChange={(e) => setHomeTeam(e.target.value)}>
              <option value="">Select team</option>
              {teamsWithStats.map((t) => (
                <option key={t.id} value={t.abbreviation} disabled={t.abbreviation === awayTeam}>
                  {t.abbreviation} — {t.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className={styles.formGroup}>
          <label>Team B</label>
          {teamsLoading ? (
            <select disabled><option>Loading...</option></select>
          ) : (
            <select value={awayTeam} onChange={(e) => setAwayTeam(e.target.value)}>
              <option value="">Select team</option>
              {teamsWithStats.map((t) => (
                <option key={t.id} value={t.abbreviation} disabled={t.abbreviation === homeTeam}>
                  {t.abbreviation} — {t.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className={styles.formGroup}>
          <label>Rolling Window: {rollingWindow} games</label>
          <input
            type="range"
            min={5}
            max={80}
            step={5}
            value={rollingWindow}
            onChange={(e) => setRollingWindow(parseInt(e.target.value))}
          />
        </div>
      </div>

      {homeTeam && awayTeam && homeTeam !== awayTeam && (
        <TeamProfileComparison
          homeTeam={homeTeam}
          awayTeam={awayTeam}
          rollingWindow={rollingWindow}
          sport={sportCode}
        />
      )}
    </div>
  );
}
