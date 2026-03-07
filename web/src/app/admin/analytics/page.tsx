"use client";

import Link from "next/link";
import { ROUTES } from "@/lib/constants/routes";
import { AdminCard } from "@/components/admin";
import styles from "./analytics.module.css";

const sections = [
  {
    href: ROUTES.ANALYTICS_WORKBENCH,
    title: "Workbench",
    desc: "Build feature loadouts, train models, and view results",
  },
  {
    href: ROUTES.ANALYTICS_MODELS,
    title: "Models",
    desc: "Registry of trained models — compare, activate, and deploy",
  },
  {
    href: ROUTES.ANALYTICS_SIMULATOR,
    title: "Simulator",
    desc: "Run Monte Carlo simulations on single or batch games",
  },
  {
    href: ROUTES.ANALYTICS_MODEL_PERFORMANCE,
    title: "Performance",
    desc: "Track prediction accuracy, calibration, and model drift",
  },
  {
    href: ROUTES.ANALYTICS_EXPLORER,
    title: "Explorer",
    desc: "Browse team, player, and matchup data with advanced stats",
  },
];

export default function AnalyticsPage() {
  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Analytics</h1>
        <p className={styles.pageSubtitle}>
          Build models, run simulations, and track prediction performance
        </p>
      </header>

      <div className={styles.navGrid}>
        {sections.map((s) => (
          <Link key={s.href} href={s.href} className={styles.navLink}>
            <AdminCard title={s.title} subtitle={s.desc}>
              <span className={styles.navArrow}>&rarr;</span>
            </AdminCard>
          </Link>
        ))}
      </div>
    </div>
  );
}
