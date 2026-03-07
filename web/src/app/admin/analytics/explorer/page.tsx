"use client";

import { useState } from "react";
import { AdminCard } from "@/components/admin";
import {
  getTeamAnalytics,
  getPlayerAnalytics,
  getMatchupAnalytics,
  type TeamAnalytics,
  type PlayerAnalytics,
  type MatchupAnalytics,
} from "@/lib/api/analytics";
import { formatMetricName, formatMetricValue } from "@/lib/utils/formatting";
import styles from "../analytics.module.css";

type ExplorerTab = "team" | "player" | "matchup";

export default function ExplorerPage() {
  const [tab, setTab] = useState<ExplorerTab>("team");

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Explorer</h1>
        <p className={styles.pageSubtitle}>
          Browse team, player, and matchup analytics
        </p>
      </header>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        {(["team", "player", "matchup"] as const).map((t) => (
          <button
            key={t}
            className={`${styles.btn} ${tab === t ? styles.btnPrimary : ""}`}
            onClick={() => setTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "team" && <TeamPanel />}
      {tab === "player" && <PlayerPanel />}
      {tab === "matchup" && <MatchupPanel />}
    </div>
  );
}

function TeamPanel() {
  const [sport, setSport] = useState("mlb");
  const [teamId, setTeamId] = useState("");
  const [data, setData] = useState<TeamAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    if (!teamId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getTeamAnalytics(sport, teamId.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <AdminCard title="Team Lookup">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Team ID</label>
            <input
              type="text"
              value={teamId}
              onChange={(e) => setTeamId(e.target.value)}
              placeholder="e.g. NYY"
              onKeyDown={(e) => e.key === "Enter" && handleFetch()}
            />
          </div>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleFetch}
            disabled={loading || !teamId.trim()}
          >
            {loading ? "Loading..." : "Fetch"}
          </button>
        </div>
      </AdminCard>
      {error && <div className={styles.error}>{error}</div>}
      {data && (
        <div className={styles.resultsSection}>
          <AdminCard title={data.name || data.team_id} subtitle={`${data.sport.toUpperCase()} Team Profile`}>
            {Object.keys(data.metrics).length === 0 ? (
              <p className={styles.empty}>No metrics available yet</p>
            ) : (
              <div className={styles.metricsGrid}>
                {Object.entries(data.metrics).map(([key, value]) => (
                  <div key={key} className={styles.metricItem}>
                    <span className={styles.metricLabel}>{formatMetricName(key)}</span>
                    <span className={styles.metricValue}>{formatMetricValue(value)}</span>
                  </div>
                ))}
              </div>
            )}
          </AdminCard>
        </div>
      )}
    </>
  );
}

function PlayerPanel() {
  const [sport, setSport] = useState("mlb");
  const [playerId, setPlayerId] = useState("");
  const [data, setData] = useState<PlayerAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    if (!playerId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getPlayerAnalytics(sport, playerId.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <AdminCard title="Player Lookup">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Player ID</label>
            <input
              type="text"
              value={playerId}
              onChange={(e) => setPlayerId(e.target.value)}
              placeholder="e.g. player_123"
              onKeyDown={(e) => e.key === "Enter" && handleFetch()}
            />
          </div>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleFetch}
            disabled={loading || !playerId.trim()}
          >
            {loading ? "Loading..." : "Fetch"}
          </button>
        </div>
      </AdminCard>
      {error && <div className={styles.error}>{error}</div>}
      {data && (
        <div className={styles.resultsSection}>
          <AdminCard title={data.name || data.player_id} subtitle={`${data.sport.toUpperCase()} Player Profile`}>
            {Object.keys(data.metrics).length === 0 ? (
              <p className={styles.empty}>No metrics available yet</p>
            ) : (
              <div className={styles.metricsGrid}>
                {Object.entries(data.metrics).map(([key, value]) => (
                  <div key={key} className={styles.metricItem}>
                    <span className={styles.metricLabel}>{formatMetricName(key)}</span>
                    <span className={styles.metricValue}>{formatMetricValue(value)}</span>
                  </div>
                ))}
              </div>
            )}
          </AdminCard>
        </div>
      )}
    </>
  );
}

function MatchupPanel() {
  const [sport, setSport] = useState("mlb");
  const [entityA, setEntityA] = useState("");
  const [entityB, setEntityB] = useState("");
  const [data, setData] = useState<MatchupAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    if (!entityA.trim() || !entityB.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getMatchupAnalytics(sport, entityA.trim(), entityB.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <AdminCard title="Matchup Analysis">
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Sport</label>
            <select value={sport} onChange={(e) => setSport(e.target.value)}>
              <option value="mlb">MLB</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Player A (Batter)</label>
            <input
              type="text"
              value={entityA}
              onChange={(e) => setEntityA(e.target.value)}
              placeholder="e.g. batter_123"
            />
          </div>
          <div className={styles.formGroup}>
            <label>Player B (Pitcher)</label>
            <input
              type="text"
              value={entityB}
              onChange={(e) => setEntityB(e.target.value)}
              placeholder="e.g. pitcher_456"
              onKeyDown={(e) => e.key === "Enter" && handleFetch()}
            />
          </div>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleFetch}
            disabled={loading || !entityA.trim() || !entityB.trim()}
          >
            {loading ? "Loading..." : "Analyze"}
          </button>
        </div>
      </AdminCard>
      {error && <div className={styles.error}>{error}</div>}
      {data && (
        <div className={styles.resultsSection}>
          <AdminCard
            title={`${data.entity_a} vs ${data.entity_b}`}
            subtitle="Probability Distribution"
          >
            {Object.keys(data.probabilities).length === 0 ? (
              <p className={styles.empty}>No probability data available</p>
            ) : (
              <div>
                {Object.entries(data.probabilities).map(([key, value]) => (
                  <div key={key} className={styles.probBar}>
                    <span className={styles.probLabel}>{formatMetricName(key)}</span>
                    <div className={styles.probTrack}>
                      <div
                        className={styles.probFill}
                        style={{ width: `${Math.min(value * 100, 100)}%` }}
                      />
                    </div>
                    <span className={styles.probValue}>{(value * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            )}
          </AdminCard>
        </div>
      )}
    </>
  );
}
