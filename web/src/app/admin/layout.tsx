"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { AdminNav } from "@/components/admin/AdminNav";
import { RunsDrawer } from "@/components/admin/RunsDrawer";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import styles from "./layout.module.css";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Close sidebar on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSidebarOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, []);

  return (
    <>
      <head>
        <meta name="robots" content="noindex, nofollow" />
      </head>
      <div className={styles.adminShell}>
      <header className={styles.header}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button
            className={styles.hamburger}
            onClick={() => setSidebarOpen((o) => !o)}
            aria-label="Toggle navigation"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <div className={styles.headerLogo}>DOCK108</div>
        </div>
        <Link href="https://dock108.ai" className={styles.headerLink}>
          Back to hub
        </Link>
      </header>

      {/* Backdrop for mobile sidebar */}
      <div
        className={`${styles.sidebarBackdrop} ${sidebarOpen ? styles.sidebarBackdropVisible : ""}`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ""}`}>
        <AdminNav onNavigate={() => setSidebarOpen(false)} />
      </aside>

      <main className={styles.main}>
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <RunsDrawer />
    </div>
    </>
  );
}
