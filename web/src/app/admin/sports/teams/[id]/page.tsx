"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import styles from "./page.module.css";
import { fetchTeam, listTeams, updateTeamColors, type TeamDetail, type TeamSummary } from "@/lib/api/sportsAdmin";
import { ROUTES } from "@/lib/constants/routes";

const API_REF_FIELDS: { label: string; field: keyof TeamDetail }[] = [
  { label: "ID", field: "id" },
  { label: "Name", field: "name" },
  { label: "Short Name", field: "shortName" },
  { label: "Abbreviation", field: "abbreviation" },
  { label: "League", field: "leagueCode" },
  { label: "Location", field: "location" },
  { label: "External Ref", field: "externalRef" },
  { label: "Light Color", field: "colorLightHex" },
  { label: "Dark Color", field: "colorDarkHex" },
];

export default function TeamDetailPage() {
  const params = useParams();
  const teamId = Number(params.id);

  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lightColor, setLightColor] = useState("#6366f1");
  const [darkColor, setDarkColor] = useState("#6366f1");
  const [colorSaving, setColorSaving] = useState(false);
  const [copyLabel, setCopyLabel] = useState("Copy as JSON");
  const [leagueTeams, setLeagueTeams] = useState<TeamSummary[]>([]);
  const [selectedOpponent, setSelectedOpponent] = useState<string>("");

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await fetchTeam(teamId);
        setTeam(data);
        setLightColor(data.colorLightHex || "#6366f1");
        setDarkColor(data.colorDarkHex || "#6366f1");
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    }

    if (teamId) {
      load();
    }
  }, [teamId]);

  // Fetch league teams for matchup preview
  useEffect(() => {
    if (!team) return;
    async function loadLeagueTeams() {
      try {
        const res = await listTeams({ league: team!.leagueCode, limit: 200 });
        setLeagueTeams(res.teams.filter((t) => t.id !== team!.id));
      } catch {
        // Non-critical: matchup preview won't work but page still functional
      }
    }
    loadLeagueTeams();
  }, [team]);

  if (loading) {
    return <div className={styles.loading}>Loading team...</div>;
  }

  if (error) {
    return <div className={styles.error}>Error: {error}</div>;
  }

  if (!team) {
    return <div className={styles.error}>Team not found</div>;
  }

  async function handleSaveColors() {
    setColorSaving(true);
    try {
      const updated = await updateTeamColors(teamId, {
        colorLightHex: lightColor,
        colorDarkHex: darkColor,
      });
      setTeam(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setColorSaving(false);
    }
  }

  function handleCopyJson() {
    const obj: Record<string, unknown> = {};
    for (const { field } of API_REF_FIELDS) {
      obj[field] = team![field];
    }
    navigator.clipboard.writeText(JSON.stringify(obj, null, 2)).then(() => {
      setCopyLabel("Copied!");
      setTimeout(() => setCopyLabel("Copy as JSON"), 2000);
    });
  }

  const getResultClass = (result: string) => {
    switch (result) {
      case "W": return styles.resultWin;
      case "L": return styles.resultLoss;
      default: return styles.resultDraw;
    }
  };

  const opponent = leagueTeams.find((t) => String(t.id) === selectedOpponent);

  return (
    <div className={styles.container}>
      <Link href="/admin/sports/teams" className={styles.backLink}>
        ← Back to teams
      </Link>

      <header className={styles.header}>
        <div className={styles.teamBadge}>
          <span className={styles.abbr}>{team.abbreviation}</span>
          <h1 className={styles.title}>{team.name}</h1>
        </div>
        <div className={styles.meta}>
          <span className={styles.metaItem}>{team.leagueCode}</span>
          {team.location && (
            <span className={styles.metaItem}>{team.location}</span>
          )}
          <span className={styles.metaItem}>
            {team.recentGames.length} recent games
          </span>
        </div>
      </header>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>API Reference</h2>
        <table className={styles.apiRefTable}>
          <thead>
            <tr>
              <th>Label</th>
              <th>API Field</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {API_REF_FIELDS.map(({ label, field }) => (
              <tr key={field}>
                <td>{label}</td>
                <td className={styles.apiRefField}>{field}</td>
                <td className={styles.apiRefValue}>{String(team[field] ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className={styles.copyJsonButton} onClick={handleCopyJson}>
          {copyLabel}
        </button>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Team Colors</h2>
        <div className={styles.colorEditor}>
          <div className={styles.colorField}>
            <label className={styles.colorLabel}>Light Mode</label>
            <input
              type="color"
              className={styles.colorInput}
              value={lightColor}
              onChange={(e) => setLightColor(e.target.value)}
            />
            <span className={styles.hexLabel}>{team.colorLightHex || "Not set"}</span>
          </div>
          <div className={styles.colorField}>
            <label className={styles.colorLabel}>Dark Mode</label>
            <input
              type="color"
              className={styles.colorInput}
              value={darkColor}
              onChange={(e) => setDarkColor(e.target.value)}
            />
            <span className={styles.hexLabel}>{team.colorDarkHex || "Not set"}</span>
          </div>
          <button
            className={styles.saveButton}
            onClick={handleSaveColors}
            disabled={colorSaving}
          >
            {colorSaving ? "Saving..." : "Save Colors"}
          </button>
        </div>
        <div className={styles.colorPreview}>
          <span
            className={styles.previewBadge}
            style={{ background: lightColor, color: "#fff" }}
          >
            {team.abbreviation} (Light)
          </span>
          <span
            className={styles.previewBadge}
            style={{ background: darkColor, color: "#fff" }}
          >
            {team.abbreviation} (Dark)
          </span>
        </div>

        {leagueTeams.length > 0 && (
          <div className={styles.matchupPreview}>
            <h3 className={styles.sectionTitle}>Matchup Color Preview</h3>
            <select
              className={styles.matchupSelect}
              value={selectedOpponent}
              onChange={(e) => setSelectedOpponent(e.target.value)}
            >
              <option value="">Select opponent...</option>
              {leagueTeams.map((t) => (
                <option key={t.id} value={String(t.id)}>
                  {t.abbreviation} — {t.name}
                </option>
              ))}
            </select>
            {opponent && (
              <>
                <div className={styles.matchupRow}>
                  <span className={styles.matchupLabel}>Light</span>
                  <span className={styles.matchupTeam} style={{ background: lightColor }}>
                    {team.abbreviation}
                  </span>
                  <span className={styles.matchupVs}>vs</span>
                  <span className={styles.matchupTeam} style={{ background: opponent.colorLightHex || "#6366f1" }}>
                    {opponent.abbreviation}
                  </span>
                </div>
                <div className={styles.matchupRow}>
                  <span className={styles.matchupLabel}>Dark</span>
                  <span className={styles.matchupTeam} style={{ background: darkColor }}>
                    {team.abbreviation}
                  </span>
                  <span className={styles.matchupVs}>vs</span>
                  <span className={styles.matchupTeam} style={{ background: opponent.colorDarkHex || "#6366f1" }}>
                    {opponent.abbreviation}
                  </span>
                </div>
              </>
            )}
          </div>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Recent Games</h2>
        {team.recentGames.length === 0 ? (
          <div className={styles.empty}>No games found for this team</div>
        ) : (
          <table className={styles.gamesTable}>
            <thead>
              <tr>
                <th>Date</th>
                <th>Opponent</th>
                <th>Location</th>
                <th>Score</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {team.recentGames.map((game) => (
                <tr key={game.id}>
                  <td>
                    <Link href={ROUTES.SPORTS_GAME(game.id)}>
                      {new Date(game.gameDate).toLocaleDateString()}
                    </Link>
                  </td>
                  <td>{game.opponent}</td>
                  <td>
                    {game.isHome ? (
                      <span>Home</span>
                    ) : (
                      <span>Away</span>
                    )}
                  </td>
                  <td>{game.score}</td>
                  <td className={getResultClass(game.result)}>
                    {game.result}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
