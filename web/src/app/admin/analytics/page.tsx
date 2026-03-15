"use client";

import Link from "next/link";
import { ROUTES } from "@/lib/constants/routes";
import { AdminCard } from "@/components/admin";
import styles from "./analytics.module.css";

const sections = [
  {
    href: ROUTES.ANALYTICS_SIMULATOR,
    title: "Simulator",
    desc: "Monte Carlo simulations using pitch-level data and team profiles",
  },
  {
    href: ROUTES.ANALYTICS_MODELS,
    title: "Models",
    desc: "Registry of trained models — compare, activate, and deploy",
  },
  {
    href: ROUTES.ANALYTICS_BATCH,
    title: "Batch Sims",
    desc: "Queue and monitor batch simulation runs",
  },
  {
    href: ROUTES.ANALYTICS_EXPERIMENTS,
    title: "Experiments",
    desc: "Run parameter sweeps — permutate algorithms, features, and windows, then compare results",
  },
  {
    href: ROUTES.ANALYTICS_PROFILES,
    title: "Profiles",
    desc: "View and compare team rolling profiles and scouting metrics",
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
