"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ROUTES } from "@/lib/constants/routes";
import styles from "./page.module.css";
import { listScrapeRuns, listGames, type ScrapeRunResponse, type GameFilters } from "@/lib/api/sportsAdmin";
import { getStatusClass } from "@/lib/utils/status";

interface DashboardStats {
  totalGames: number;
  totalRuns: number;
  pendingRuns: number;
  runningRuns: number;
}

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentRuns, setRecentRuns] = useState<ScrapeRunResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadDashboard() {
      try {
        setLoading(true);
        
        const [runs, gamesResponse] = await Promise.all([
          listScrapeRuns(),
          listGames({ limit: 1, offset: 0 } as GameFilters),
        ]);

        const pending = runs.filter(r => r.status === "pending").length;
        const running = runs.filter(r => r.status === "running").length;

        setStats({
          totalGames: gamesResponse.total,
          totalRuns: runs.length,
          pendingRuns: pending,
          runningRuns: running,
        });

        setRecentRuns(runs.slice(0, 5));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    }

    loadDashboard();
  }, []);

  // Use shared status utility
  const getStatusClassName = (status: string) => {
    const baseClass = getStatusClass(status);
    return styles[baseClass] || styles.runStatusPending;
  };

  if (loading) {
    return <div className={styles.loading}>Loading dashboard...</div>;
  }

  if (error) {
    return <div className={styles.error}>Error: {error}</div>;
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Dashboard</h1>
        <p className={styles.subtitle}>Sports data ingestion overview</p>
      </header>

      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Total Games</div>
          <div className={styles.statValue}>{stats?.totalGames.toLocaleString() ?? 0}</div>
          <div className={styles.statSub}>Across all leagues</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Scrape Runs</div>
          <div className={styles.statValue}>{stats?.totalRuns ?? 0}</div>
          <div className={styles.statSub}>Total completed</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Pending</div>
          <div className={styles.statValue}>{stats?.pendingRuns ?? 0}</div>
          <div className={styles.statSub}>Jobs in queue</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Running</div>
          <div className={styles.statValue}>{stats?.runningRuns ?? 0}</div>
          <div className={styles.statSub}>Active workers</div>
        </div>
      </div>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Quick Actions</h2>
        <div className={styles.quickLinks}>
          <Link href={ROUTES.GAMES} className={styles.quickLink}>
            <div className={styles.quickLinkContent}>
              <div className={styles.quickLinkTitle}>Data browser</div>
              <div className={styles.quickLinkDesc}>Filter games, odds, and completeness</div>
            </div>
          </Link>
          <Link href={ROUTES.SEASON_AUDIT} className={styles.quickLink}>
            <div className={styles.quickLinkContent}>
              <div className={styles.quickLinkTitle}>Season Audit</div>
              <div className={styles.quickLinkDesc}>Check data completeness per league season</div>
            </div>
          </Link>
          <Link href={ROUTES.CONTROL_PANEL} className={styles.quickLink}>
            <div className={styles.quickLinkContent}>
              <div className={styles.quickLinkTitle}>Control Panel</div>
              <div className={styles.quickLinkDesc}>Trigger tasks and monitor job runs</div>
            </div>
          </Link>
        </div>
      </section>

      {recentRuns.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Recent Runs</h2>
          <div className={styles.recentRuns}>
            {recentRuns.map((run) => (
              <Link
                key={run.id}
                href={ROUTES.CONTROL_PANEL}
                className={styles.runItem}
              >
                <div className={`${styles.runStatus} ${getStatusClassName(run.status)}`} />
                <div className={styles.runInfo}>
                  <div className={styles.runTitle}>
                    {run.leagueCode} {run.season} — {run.status}
                  </div>
                  <div className={styles.runMeta}>{run.startDate} to {run.endDate}</div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

