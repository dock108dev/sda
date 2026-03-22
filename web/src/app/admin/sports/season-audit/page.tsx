"use client";

import { useState, useCallback } from "react";
import styles from "./page.module.css";
import { getSeasonAudit, type SeasonAuditResponse } from "@/lib/api/sportsAdmin";

/** Leagues with season audit support (have config + data pipelines). */
const AUDIT_LEAGUES = ["NBA", "NHL", "MLB", "NFL", "NCAAB"] as const;

function barColor(pct: number): string {
  if (pct >= 90) return styles.barGreen;
  if (pct >= 70) return styles.barYellow;
  return styles.barRed;
}

function textColor(pct: number): string {
  if (pct >= 90) return styles.green;
  if (pct >= 70) return styles.yellow;
  return styles.red;
}

interface CoverageRow {
  label: string;
  count: number;
  pct: number;
}

function LeagueCard({ data }: { data: SeasonAuditResponse }) {
  const coverageRows: CoverageRow[] = [
    { label: "Boxscores", count: data.withBoxscore, pct: data.boxscorePct },
    { label: "Player Stats", count: data.withPlayerStats, pct: data.playerStatsPct },
    { label: "Odds", count: data.withOdds, pct: data.oddsPct },
    { label: "Play-by-Play", count: data.withPbp, pct: data.pbpPct },
    { label: "Social", count: data.withSocial, pct: data.socialPct },
    { label: "Game Flow", count: data.withFlow, pct: data.flowPct },
    { label: "Adv Stats", count: data.withAdvancedStats, pct: data.advancedStatsPct },
  ];

  // For in-progress seasons, compare against pro-rated expected games
  const isInProgress = data.seasonPctComplete != null && data.seasonPctComplete > 0 && data.seasonPctComplete < 100;
  const progressTarget = isInProgress ? data.expectedGamesToDate : data.expectedGames;
  const progressPct = progressTarget ? Math.round(data.totalGames / progressTarget * 100 * 10) / 10 : data.coveragePct;

  return (
    <div className={styles.summaryCard}>
      <div className={styles.summaryHeader}>
        <span className={styles.summaryTitle}>{data.leagueCode}</span>
        <span className={styles.summaryMeta}>
          {data.teamsWithGames} teams
          {data.expectedTeams != null && ` / ${data.expectedTeams}`}
        </span>
      </div>

      {/* Season dates */}
      {data.seasonStart && data.seasonEnd && (
        <div style={{ fontSize: "0.8rem", color: "#64748b", marginBottom: "0.75rem" }}>
          {data.seasonStart} — {data.seasonEnd}
          {data.seasonPctComplete != null && (
            <span style={{ marginLeft: "0.5rem", fontWeight: 600 }}>
              ({data.seasonPctComplete}% of season elapsed)
            </span>
          )}
        </div>
      )}

      {/* Big numbers */}
      <div className={styles.bigNumbers}>
        <div className={styles.bigNumber}>
          <div className={styles.bigNumberValue}>
            {data.totalGames.toLocaleString()}
          </div>
          <div className={styles.bigNumberLabel}>Games</div>
        </div>
        {isInProgress && data.expectedGamesToDate != null ? (
          <div className={styles.bigNumber}>
            <div className={styles.bigNumberValue}>
              {data.expectedGamesToDate.toLocaleString()}
            </div>
            <div className={styles.bigNumberLabel}>Expected to Date</div>
          </div>
        ) : data.expectedGames != null ? (
          <div className={styles.bigNumber}>
            <div className={styles.bigNumberValue}>
              {data.expectedGames.toLocaleString()}
            </div>
            <div className={styles.bigNumberLabel}>Expected</div>
          </div>
        ) : null}
        {progressPct != null && (
          <div className={styles.bigNumber}>
            <div className={`${styles.bigNumberValue} ${textColor(Math.min(progressPct, 100))}`}>
              {Math.min(progressPct, 999)}%
            </div>
            <div className={styles.bigNumberLabel}>
              {isInProgress ? "vs Expected to Date" : "Coverage"}
            </div>
          </div>
        )}
      </div>

      {/* Season coverage bar */}
      {progressTarget != null && progressPct != null && (
        <div style={{ marginBottom: "1rem" }}>
          <div className={styles.progressBarOuter}>
            <div
              className={`${styles.progressBarInner} ${barColor(Math.min(progressPct, 100))}`}
              style={{ width: `${Math.min(progressPct, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Data type rows */}
      <div className={styles.progressRows}>
        {coverageRows.map((row) => (
          <div key={row.label} className={styles.progressRow}>
            <span className={styles.progressLabel}>{row.label}</span>
            <div className={styles.progressBarOuter}>
              <div
                className={`${styles.progressBarInner} ${barColor(row.pct)}`}
                style={{ width: `${Math.min(row.pct, 100)}%` }}
              />
            </div>
            <span className={`${styles.progressPct} ${textColor(row.pct)}`}>
              {row.pct}%
            </span>
            <span className={styles.progressCount}>
              {row.count.toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SeasonAuditPage() {
  const [season, setSeason] = useState<number>(new Date().getFullYear() - 1);
  const [results, setResults] = useState<Record<string, SeasonAuditResponse>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const handleAudit = useCallback(async () => {
    setLoading(true);
    setResults({});
    setErrors({});

    const settled = await Promise.allSettled(
      AUDIT_LEAGUES.map((league) =>
        getSeasonAudit({ league, season, seasonType: "regular" })
      )
    );

    const newResults: Record<string, SeasonAuditResponse> = {};
    const newErrors: Record<string, string> = {};

    settled.forEach((result, i) => {
      const league = AUDIT_LEAGUES[i];
      if (result.status === "fulfilled") {
        newResults[league] = result.value;
      } else {
        newErrors[league] = result.reason instanceof Error
          ? result.reason.message
          : String(result.reason);
      }
    });

    setResults(newResults);
    setErrors(newErrors);
    setLoading(false);
  }, [season]);

  const hasResults = Object.keys(results).length > 0;

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Season Audit</h1>
        <p className={styles.subtitle}>
          Data completeness across all leagues for a season
        </p>
      </header>

      <div className={styles.controls}>
        <div className={styles.field}>
          <span className={styles.fieldLabel}>Season Start Year</span>
          <input
            className={styles.input}
            type="number"
            value={season}
            onChange={(e) => setSeason(Number(e.target.value))}
            min={2000}
            max={2099}
          />
        </div>

        <button className={styles.button} onClick={handleAudit} disabled={loading}>
          {loading ? "Loading..." : "Audit All Leagues"}
        </button>
      </div>

      {loading && <div className={styles.loading}>Fetching data for all leagues...</div>}

      {hasResults && (
        <div className={styles.leagueGrid}>
          {AUDIT_LEAGUES.map((league) => {
            const data = results[league];
            const err = errors[league];

            if (err) {
              return (
                <div key={league} className={styles.summaryCard}>
                  <div className={styles.summaryHeader}>
                    <span className={styles.summaryTitle}>{league}</span>
                  </div>
                  <div className={styles.error}>{err}</div>
                </div>
              );
            }

            if (!data) return null;

            return <LeagueCard key={league} data={data} />;
          })}
        </div>
      )}

      {!hasResults && !loading && (
        <div className={styles.empty}>
          Pick a season start year and click Audit All Leagues.
        </div>
      )}
    </div>
  );
}
