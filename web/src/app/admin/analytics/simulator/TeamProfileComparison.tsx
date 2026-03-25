"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { AdminCard } from "@/components/admin";
import { getTeamProfile, getTeamProfileMultiSport, type TeamProfileResponse } from "@/lib/api/analytics";
import styles from "../analytics.module.css";

interface MetricGroup {
  label: string;
  keys: { key: string; label: string; higherIsBetter: boolean }[];
}

const METRIC_GROUPS: MetricGroup[] = [
  {
    label: "Contact Quality",
    keys: [
      { key: "barrel_rate", label: "Barrel Rate", higherIsBetter: true },
      { key: "hard_hit_rate", label: "Hard Hit Rate", higherIsBetter: true },
      { key: "avg_exit_velocity", label: "Avg Exit Velocity", higherIsBetter: true },
    ],
  },
  {
    label: "Plate Discipline",
    keys: [
      { key: "chase_rate", label: "Chase Rate", higherIsBetter: false },
      { key: "whiff_rate", label: "Whiff Rate", higherIsBetter: false },
      { key: "contact_rate", label: "Contact Rate", higherIsBetter: true },
      { key: "z_contact_pct", label: "Zone Contact %", higherIsBetter: true },
      { key: "o_swing_pct", label: "O-Swing %", higherIsBetter: false },
    ],
  },
  {
    label: "Production",
    keys: [
      { key: "box_avg", label: "AVG", higherIsBetter: true },
      { key: "box_obp", label: "OBP", higherIsBetter: true },
      { key: "box_slg", label: "SLG", higherIsBetter: true },
      { key: "box_ops", label: "OPS", higherIsBetter: true },
    ],
  },
];

function formatMetric(value: number | undefined): string {
  if (value === undefined) return "-";
  if (value > 10) return value.toFixed(1); // exit velocity
  return value.toFixed(3);
}

function colorForMetric(
  value: number | undefined,
  baseline: number | undefined,
  higherIsBetter: boolean,
): string | undefined {
  if (value === undefined || baseline === undefined) return undefined;
  const better = higherIsBetter ? value > baseline : value < baseline;
  const worse = higherIsBetter ? value < baseline : value > baseline;
  if (better) return "#16a34a";
  if (worse) return "#dc2626";
  return undefined;
}

export function TeamProfileComparison({
  homeTeam,
  awayTeam,
  rollingWindow = 30,
  sport,
}: {
  homeTeam: string;
  awayTeam: string;
  rollingWindow?: number;
  sport?: string;
}) {
  const [homeProfile, setHomeProfile] = useState<TeamProfileResponse | null>(null);
  const [awayProfile, setAwayProfile] = useState<TeamProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProfiles = useCallback(async (home: string, away: string, window: number) => {
    setLoading(true);
    setError(null);
    try {
      const fetchFn = sport
        ? (team: string, w: number) => getTeamProfileMultiSport(team, sport, w)
        : getTeamProfile;
      const [homeRes, awayRes] = await Promise.all([
        fetchFn(home, window),
        fetchFn(away, window),
      ]);
      setHomeProfile(homeRes);
      setAwayProfile(awayRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sport]);

  const prevKey = useRef("");
  useEffect(() => {
    const key = `${homeTeam}|${awayTeam}|${rollingWindow}|${sport || ""}`;
    if (!homeTeam || !awayTeam || key === prevKey.current) return;
    prevKey.current = key;
    fetchProfiles(homeTeam, awayTeam, rollingWindow);
  }, [homeTeam, awayTeam, rollingWindow, sport, fetchProfiles]);

  if (!homeTeam || !awayTeam) return null;
  if (loading) return <p style={{ color: "var(--text-muted)" }}>Loading team profiles...</p>;
  if (error) return <div className={styles.error}>{error}</div>;
  if (!homeProfile || !awayProfile) return null;
  if (!homeProfile.games_used || !awayProfile.games_used) {
    return (
      <AdminCard title="Team Profiles">
        <p style={{ color: "var(--text-muted)" }}>
          Profile data unavailable for one or both teams.
        </p>
      </AdminCard>
    );
  }

  const baselines = homeProfile.baselines;

  return (
    <AdminCard
      title="Team Profile Comparison"
      subtitle={`${homeTeam} (${homeProfile.games_used} games) vs ${awayTeam} (${awayProfile.games_used} games) — rolling ${rollingWindow} game window`}
    >
      {METRIC_GROUPS.map((group) => (
        <div key={group.label} style={{ marginBottom: "1rem" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: "0.35rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {group.label}
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <th style={{ textAlign: "left", padding: "0.35rem 0.5rem", fontWeight: 500, color: "var(--text-muted)" }}>Metric</th>
                <th style={{ textAlign: "right", padding: "0.35rem 0.5rem", fontWeight: 500 }}>{homeTeam}</th>
                <th style={{ textAlign: "center", padding: "0.35rem 0.5rem", fontWeight: 500, color: "var(--text-muted)" }}>Lg Avg</th>
                <th style={{ textAlign: "right", padding: "0.35rem 0.5rem", fontWeight: 500 }}>{awayTeam}</th>
              </tr>
            </thead>
            <tbody>
              {group.keys.map(({ key, label, higherIsBetter }) => {
                const hv = homeProfile.metrics[key];
                const av = awayProfile.metrics[key];
                const bl = baselines[key];
                return (
                  <tr key={key} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "0.3rem 0.5rem", color: "var(--text-secondary)" }}>{label}</td>
                    <td style={{ textAlign: "right", padding: "0.3rem 0.5rem", fontWeight: 500, color: colorForMetric(hv, bl, higherIsBetter) }}>
                      {formatMetric(hv)}
                    </td>
                    <td style={{ textAlign: "center", padding: "0.3rem 0.5rem", color: "var(--text-muted)" }}>
                      {formatMetric(bl)}
                    </td>
                    <td style={{ textAlign: "right", padding: "0.3rem 0.5rem", fontWeight: 500, color: colorForMetric(av, bl, higherIsBetter) }}>
                      {formatMetric(av)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </AdminCard>
  );
}
