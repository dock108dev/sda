"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ROUTES } from "@/lib/constants/routes";
import styles from "./AdminNav.module.css";

interface NavItem {
  href: string;
  label: string;
  /** Use exact pathname match instead of startsWith */
  exact?: boolean;
}

const navSections: { title: string; items: NavItem[] }[] = [
  {
    title: "General",
    items: [
      { href: ROUTES.OVERVIEW, label: "Overview", exact: true },
    ],
  },
  {
    title: "Data",
    items: [
      { href: ROUTES.GAMES, label: "Games" },
      { href: ROUTES.FAIRBET_ODDS, label: "Odds (FairBet)" },
    ],
  },
  {
    title: "Analytics",
    items: [
      { href: ROUTES.ANALYTICS, label: "Overview", exact: true },
      { href: ROUTES.ANALYTICS_WORKBENCH, label: "Workbench" },
      { href: ROUTES.ANALYTICS_MODELS, label: "Models" },
      { href: ROUTES.ANALYTICS_SIMULATOR, label: "Simulator" },
      { href: ROUTES.ANALYTICS_MODEL_PERFORMANCE, label: "Performance" },
      { href: ROUTES.ANALYTICS_EXPLORER, label: "Explorer" },
    ],
  },
  {
    title: "System",
    items: [
      { href: ROUTES.CONTROL_PANEL, label: "Control Panel" },
      { href: ROUTES.LOGS, label: "Logs" },
    ],
  },
];

export function AdminNav({ onNavigate }: { onNavigate?: () => void } = {}) {
  const pathname = usePathname();

  const isActive = (href: string, exact?: boolean) =>
    exact ? pathname === href : pathname.startsWith(href);

  return (
    <div className={styles.navContainer}>
      <div className={styles.logo}>
        <div className={styles.logoText}>Sports Admin</div>
        <div className={styles.logoSub}>Data Management</div>
      </div>

      <nav className={styles.nav}>
        {navSections.map((section) => (
          <div key={section.title} className={styles.navSection}>
            <div className={styles.navSectionTitle}>{section.title}</div>
            {section.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`${styles.navLink} ${isActive(item.href, item.exact) ? styles.navLinkActive : ""}`}
                onClick={onNavigate}
              >
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>

      <div className={styles.footer}>
        <Link href="/" className={styles.footerLink}>
          Back to Home
        </Link>
      </div>
    </div>
  );
}
