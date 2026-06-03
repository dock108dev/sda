"use client";

import { useState } from "react";
import { SportSelector } from "@/components/admin/SportSelector";
import { type AnalyticsSport } from "@/lib/constants/analytics";
import styles from "../analytics.module.css";
import { ExperimentHistory } from "./ExperimentHistory";

import { ExperimentBuilder } from "./ExperimentBuilder";

export default function ExperimentsPage() {
  // Bump to trigger history refresh after a new experiment is submitted
  const [refreshKey, setRefreshKey] = useState(0);
  const [sport, setSport] = useState<AnalyticsSport>("MLB");
  const sportCode = sport.toLowerCase();

  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>Experiments</h1>
        <p className={styles.pageSubtitle}>
          Configure feature combinations and parameter sweeps, then compare results
        </p>
      </header>

      <SportSelector value={sport} onChange={setSport} />

      <ExperimentBuilder sportCode={sportCode} onSubmitted={() => setRefreshKey((k) => k + 1)} />
      <div style={{ marginTop: "1.5rem" }}>
        <ExperimentHistory refreshKey={refreshKey} sportCode={sportCode} />
      </div>
    </div>
  );
}