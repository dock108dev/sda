"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import styles from "./page.module.css";
import { AdminCard, AdminStatCard } from "@/components/admin";
import { ROUTES } from "@/lib/constants/routes";
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
        <AdminStatCard
          label="Total Games"
          value={stats?.totalGames.toLocaleString() ?? 0}
          hint="Across all leagues"
        />
        <AdminStatCard
          label="Scrape Runs"
          value={stats?.totalRuns ?? 0}
          hint="Total completed"
        />
        <AdminStatCard
          label="Pending"
          value={stats?.pendingRuns ?? 0}
          hint="Jobs in queue"
        />
        <AdminStatCard
          label="Running"
          value={stats?.runningRuns ?? 0}
          hint="Active workers"
        />
      </div>

      <AdminCard title="Quick actions" subtitle="Jump to common admin workflows">
        <div className={styles.quickLinks}>
          <Link href={ROUTES.CONTROL_PANEL} className={styles.quickLink}>
            <div className={styles.quickLinkContent}>
              <div className={styles.quickLinkTitle}>Control Panel</div>
              <div className={styles.quickLinkDesc}>Trigger tasks and monitor job runs</div>
            </div>
          </Link>
          <Link href={ROUTES.GAMES} className={styles.quickLink}>
            <div className={styles.quickLinkContent}>
              <div className={styles.quickLinkTitle}>Games</div>
              <div className={styles.quickLinkDesc}>Browse games, teams, and scrape runs</div>
            </div>
          </Link>
          <Link href={ROUTES.FAIRBET_ODDS} className={styles.quickLink}>
            <div className={styles.quickLinkContent}>
              <div className={styles.quickLinkTitle}>FairBet Odds</div>
              <div className={styles.quickLinkDesc}>Compare odds across books</div>
            </div>
          </Link>
          <Link href={ROUTES.LOGS} className={styles.quickLink}>
            <div className={styles.quickLinkContent}>
              <div className={styles.quickLinkTitle}>Logs</div>
              <div className={styles.quickLinkDesc}>View container logs</div>
            </div>
          </Link>
        </div>
      </AdminCard>

      {recentRuns.length > 0 && (
        <AdminCard title="Recent runs">
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
                  <div className={styles.runMeta}>
                    {run.startDate} to {run.endDate}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </AdminCard>
      )}
    </div>
  );
}

