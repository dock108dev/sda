"use client";

import Link from "next/link";
import { ROUTES } from "@/lib/constants/routes";
import { AdminCard } from "@/components/admin";
import styles from "./analytics.module.css";

const sections = [
  {
    href: ROUTES.ANALYTICS_TEAM,
    title: "Team Analytics",
    desc: "View team-level metrics and performance profiles",
  },
  {
    href: ROUTES.ANALYTICS_PLAYER,
    title: "Player Analytics",
    desc: "Browse player metrics, power index, and contact rates",
  },
  {
    href: ROUTES.ANALYTICS_MATCHUP,
    title: "Matchup Explorer",
    desc: "Compare two players and view probability distributions",
  },
  {
    href: ROUTES.ANALYTICS_SIMULATOR,
    title: "Game Simulator",
    desc: "Run Monte Carlo simulations and view score distributions",
  },
  {
    href: ROUTES.ANALYTICS_MODEL_PERFORMANCE,
    title: "Model Performance",
    desc: "Track prediction accuracy, calibration, and model bias",
  },
  {
    href: ROUTES.ANALYTICS_FEATURE_CONFIG,
    title: "Feature Config",
    desc: "Manage ML feature selection, weighting, and experimentation",
  },
  {
    href: ROUTES.ANALYTICS_MODELS,
    title: "Model Registry",
    desc: "View trained models, versions, metrics, and activate deployments",
  },
  {
    href: ROUTES.ANALYTICS_ENSEMBLE,
    title: "Ensemble Config",
    desc: "Configure ensemble weights for combining probability sources",
  },
  {
    href: ROUTES.ANALYTICS_BASEBALL_MODELS,
    title: "Baseball Models",
    desc: "Pitch, batted ball, and run expectancy models with test simulations",
  },
];

export default function AnalyticsPage() {
  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Analytics</h1>
        <p className={styles.pageSubtitle}>
          Team profiles, matchup analysis, and game simulation tools
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
