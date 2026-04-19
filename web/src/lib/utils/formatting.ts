/**
 * Shared formatting helpers for analytics metric display and advanced stats sections.
 */

/** Convert snake_case key to Title Case (e.g. "contact_rate" → "Contact Rate"). */
export function formatMetricName(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Format a numeric metric value with appropriate precision. */
export function formatMetricValue(value: number): string {
  if (value >= 10) return value.toFixed(1);
  return value.toFixed(4);
}

/** Format a decimal as a percentage (e.g. 0.423 → "42.3%"). */
export function fmtPct(v: number | null | undefined): string {
  return v != null ? `${(v * 100).toFixed(1)}%` : "—";
}

/** Format a number with configurable decimal places. */
export function fmtNum(v: number | null | undefined, decimals = 1): string {
  return v != null ? v.toFixed(decimals) : "—";
}
