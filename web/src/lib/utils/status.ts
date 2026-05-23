/**
 * Shared utilities for handling status display across admin pages.
 */

import { SCRAPE_RUN_STATUS_COLORS } from "@/lib/constants/sports";

export type RunStatus = "success" | "pending" | "running" | "error" | "degraded" | "interrupted";

/**
 * Get CSS class name for a run status.
 * Used with CSS modules that define status badge styles.
 */
export function getStatusClass(status: string): string {
  switch (status) {
    case "success":
      return "runStatusSuccess";
    case "pending":
      return "runStatusPending";
    case "running":
      return "runStatusRunning";
    case "error":
      return "runStatusError";
    case "degraded":
      return "runStatusDegraded";
    case "interrupted":
      return "runStatusInterrupted";
    default:
      return "runStatusPending";
  }
}

/**
 * Get background color for a run status.
 * Returns hex color code from SCRAPE_RUN_STATUS_COLORS mapping.
 */
export function getStatusColor(status: string): string {
  return SCRAPE_RUN_STATUS_COLORS[status] ?? SCRAPE_RUN_STATUS_COLORS.pending ?? "#5f6368";
}

/**
 * Get human-readable label for a status.
 */
export function getStatusLabel(status: string): string {
  switch (status) {
    case "success":
      return "Success";
    case "pending":
      return "Pending";
    case "running":
      return "Running";
    case "error":
      return "Error";
    case "degraded":
      return "Degraded";
    case "interrupted":
      return "Interrupted";
    default:
      return status.charAt(0).toUpperCase() + status.slice(1);
  }
}
