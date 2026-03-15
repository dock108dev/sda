"use client";

import { PregameSimulator } from "./PregameSimulator";
import styles from "../analytics.module.css";

export default function SimulatorPage() {
  return (
    <div className={styles.container}>
      <header className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>MLB Simulator</h1>
        <p className={styles.pageSubtitle}>
          Monte Carlo simulations using pitch-level data and team profiles
        </p>
      </header>

      <PregameSimulator />
    </div>
  );
}
