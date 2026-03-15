"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { fetchGame, rescrapeGame, resyncOdds, type AdminGameDetail } from "@/lib/api/sportsAdmin";
import { ROUTES } from "@/lib/constants/routes";
import { deriveDataStatus, type DataField } from "@/lib/utils/dataStatus";
import { DataStatusIndicator } from "@/components/admin/DataStatusIndicator";
import { CollapsibleSection } from "./CollapsibleSection";
import { PbpSection } from "./PbpSection";
import { SocialPostsSection } from "./SocialPostsSection";
import { FlowSection } from "./FlowSection";
import { OddsSection } from "./OddsSection";
import { MLBAdvancedStatsSection } from "./MLBAdvancedStatsSection";
import { PlayerStatsSection } from "./PlayerStatsSection";
import { ComputedFieldsSection } from "./ComputedFieldsSection";
import { PipelineRunsSection } from "./PipelineRunsSection";
import { flattenStats, FieldLabel } from "./gameDetailUtils";
import styles from "./styles.module.css";

export default function GameDetailClient() {
  const params = useParams<{ gameId?: string }>();
  const gameIdParam = params?.gameId ?? "";
  const isNumericId = /^\d+$/.test(gameIdParam);
  const [game, setGame] = useState<AdminGameDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<"rescrape" | "odds" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGame(gameIdParam);
      setGame(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load game");
    } finally {
      setLoading(false);
    }
  }, [gameIdParam]);

  useEffect(() => {
    if (isNumericId) {
      load();
    }
  }, [isNumericId, load]);

  const statusFlags = useMemo(() => {
    if (!game) return [];
    const g = game.game;
    const fields: { label: string; field: DataField; hasData: boolean; ts?: string | null }[] = [
      { label: "Boxscore", field: "boxscore", hasData: g.hasBoxscore, ts: g.lastScrapedAt },
      { label: "Player stats", field: "playerStats", hasData: g.hasPlayerStats, ts: g.lastScrapedAt },
      { label: "Odds", field: "odds", hasData: g.hasOdds, ts: g.lastOddsAt },
      { label: `Social (${g.socialPostCount || 0})`, field: "social", hasData: g.hasSocial, ts: g.lastSocialAt },
      { label: `PBP (${g.playCount || 0})`, field: "pbp", hasData: g.hasPbp, ts: g.lastPbpAt },
      { label: "Flow", field: "flow", hasData: g.hasFlow, ts: g.lastScrapedAt },
      { label: "Adv Stats", field: "advancedStats" as DataField, hasData: g.hasAdvancedStats, ts: g.lastAdvancedStatsAt ?? g.lastScrapedAt },
    ];
    return fields.map((f) => ({
      label: f.label,
      status: deriveDataStatus(f.field, f.hasData, g.gameDate, f.ts),
    }));
  }, [game]);

  const handleRescrape = async () => {
    setActionStatus(null);
    setActionLoading("rescrape");
    try {
      const res = await rescrapeGame(Number.parseInt(gameIdParam, 10));
      setActionStatus(res.message || "Rescrape requested");
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : "Rescrape failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleResyncOdds = async () => {
    setActionStatus(null);
    setActionLoading("odds");
    try {
      const res = await resyncOdds(Number.parseInt(gameIdParam, 10));
      setActionStatus(res.message || "Odds resync requested");
    } catch (err) {
      setActionStatus(err instanceof Error ? err.message : "Odds resync failed");
    } finally {
      setActionLoading(null);
    }
  };

  if (!isNumericId) return <div className={styles.container}>Invalid game id.</div>;
  if (loading) return <div className={styles.container}>Loading game...</div>;
  if (error) return <div className={styles.container}>Error: {error}</div>;
  if (!game) return <div className={styles.container}>Game not found.</div>;

  const g = game.game;
  const gameDate = new Date(g.gameDate).toLocaleString();

  return (
    <div className={styles.container}>
      <Link href={ROUTES.GAMES} className={styles.backLink}>
        ← Back to Games
      </Link>

      <div className={styles.card}>
        <h1>
          Game {g.id} — {g.leagueCode}
        </h1>
        <div className={styles.meta}>
          <FieldLabel label={gameDate} field="gameDate" /> · {g.seasonType ?? "season"} · Last scraped: {g.lastScrapedAt ?? "—"}
        </div>
        <div className={styles.scoreLine}>
          <div>
            <strong>
              {g.awayTeamId ? (
                <Link href={ROUTES.SPORTS_TEAM(g.awayTeamId)} style={{ color: "inherit", textDecoration: "underline" }}>
                  <FieldLabel label={g.awayTeam} field="awayTeam" />
                </Link>
              ) : (
                <FieldLabel label={g.awayTeam} field="awayTeam" />
              )}
            </strong>
            <span>Away</span>
            <span><FieldLabel label={String(g.awayScore ?? "—")} field="awayScore" /></span>
          </div>
          <div>
            <strong>
              {g.homeTeamId ? (
                <Link href={ROUTES.SPORTS_TEAM(g.homeTeamId)} style={{ color: "inherit", textDecoration: "underline" }}>
                  <FieldLabel label={g.homeTeam} field="homeTeam" />
                </Link>
              ) : (
                <FieldLabel label={g.homeTeam} field="homeTeam" />
              )}
            </strong>
            <span>Home</span>
            <span><FieldLabel label={String(g.homeScore ?? "—")} field="homeScore" /></span>
          </div>
        </div>
        <div style={{ marginTop: "1rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {statusFlags.map((f) => (
            <DataStatusIndicator
              key={f.label}
              status={f.status}
              label={f.label}
              compact={false}
            />
          ))}
        </div>
        <div style={{ marginTop: "1rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={handleRescrape}
            disabled={!!actionLoading}
            style={{ padding: "0.55rem 0.9rem", borderRadius: 8, border: "1px solid #cbd5e1" }}
          >
            {actionLoading === "rescrape" ? "Requesting..." : "Rescrape game"}
          </button>
          <button
            type="button"
            onClick={handleResyncOdds}
            disabled={!!actionLoading}
            style={{ padding: "0.55rem 0.9rem", borderRadius: 8, border: "1px solid #cbd5e1" }}
          >
            {actionLoading === "odds" ? "Requesting..." : "Resync odds"}
          </button>
          <button
            type="button"
            onClick={load}
            disabled={!!actionLoading}
            style={{ padding: "0.55rem 0.9rem", borderRadius: 8, border: "1px solid #cbd5e1" }}
          >
            Refresh
          </button>
        </div>
        {actionStatus && <div style={{ marginTop: "0.5rem", color: "#0f172a" }}>{actionStatus}</div>}
      </div>

      <CollapsibleSection title="Team Stats" defaultOpen={false}>
        {game.teamStats.length === 0 ? (
          <div style={{ color: "#475569" }}>No team stats found.</div>
        ) : (
          <div className={styles.teamStatsGrid}>
            {game.teamStats.map((t) => {
              const flattened = flattenStats(t.stats || {}, g.leagueCode, t.normalizedStats);
              return (
                <div key={t.team} className={styles.teamStatsCard}>
                  <div className={styles.teamStatsHeader}>
                    <h3>{t.team}</h3>
                    <span className={styles.badge}>{t.isHome ? "Home" : "Away"}</span>
                  </div>
                  <table className={styles.table}>
                    <tbody>
                      {flattened.map(({ key, label, value }) => (
                        <tr key={key}>
                          <td>{label}</td>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        )}
      </CollapsibleSection>

      <PlayerStatsSection
        playerStats={game.playerStats}
        nhlSkaters={game.nhlSkaters}
        nhlGoalies={game.nhlGoalies}
        mlbBatters={game.mlbBatters}
        mlbPitchers={game.mlbPitchers}
        isNHL={g.leagueCode === "NHL"}
        isMLB={g.leagueCode === "MLB"}
      />

      {((game.mlbAdvancedStats && game.mlbAdvancedStats.length > 0) ||
        (game.mlbPitcherGameStats && game.mlbPitcherGameStats.length > 0)) && (
        <MLBAdvancedStatsSection
          stats={game.mlbAdvancedStats}
          playerStats={game.mlbAdvancedPlayerStats}
          pitcherGameStats={game.mlbPitcherGameStats}
        />
      )}

      {game.mlbFieldingStats && game.mlbFieldingStats.length > 0 && (
        <CollapsibleSection title="Fielding Stats" defaultOpen={false}>
          {(() => {
            const byTeam = game.mlbFieldingStats.reduce<Record<string, typeof game.mlbFieldingStats>>((acc, s) => {
              const arr = acc[s.team] || [];
              arr.push(s);
              acc[s.team] = arr;
              return acc;
            }, {});
            return (
              <div className={styles.teamStatsGrid}>
                {Object.entries(byTeam).map(([team, rows]) => (
                  <div key={team} className={styles.teamStatsCard}>
                    <div className={styles.teamStatsHeader}><h3>{team}</h3></div>
                    <div style={{ overflowX: "auto" }}>
                      <table className={styles.table} style={{ fontSize: "0.85rem" }}>
                        <thead>
                          <tr>
                            <th>Player</th>
                            <th>Pos</th>
                            <th>OAA</th>
                            <th>DRS</th>
                            <th>UZR</th>
                            <th>E</th>
                            <th>A</th>
                            <th>PO</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((s, idx) => (
                            <tr key={`${team}-${idx}-${s.playerName}`}>
                              <td>{s.playerName}</td>
                              <td>{s.position ?? "—"}</td>
                              <td>{s.outsAboveAverage ?? "—"}</td>
                              <td>{s.defensiveRunsSaved ?? "—"}</td>
                              <td>{s.uzr != null ? s.uzr.toFixed(1) : "—"}</td>
                              <td>{s.errors ?? "—"}</td>
                              <td>{s.assists ?? "—"}</td>
                              <td>{s.putouts ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            );
          })()}
        </CollapsibleSection>
      )}

      <OddsSection odds={game.odds} />

      <SocialPostsSection posts={game.socialPosts || []} />

      <PbpSection plays={game.plays || []} groupedPlays={game.groupedPlays} leagueCode={g.leagueCode} />

      <FlowSection gameId={g.id} hasFlow={g.hasFlow} leagueCode={g.leagueCode} />

      <PipelineRunsSection gameId={g.id} />

      <ComputedFieldsSection derivedMetrics={game.derivedMetrics || {}} />
    </div>
  );
}
