/**
 * Sport-aware period labels for play-by-play and game flow display.
 *
 * NBA:   Q1-Q4, OT, 2OT, 3OT ...
 * NCAAB: H1, H2, OT, 2OT, 3OT ...
 * NHL:   P1-P3, OT, 2OT, 3OT ..., SO  (SO requires periodType === 'SO')
 *
 * NHL note: regular season has period 4 = OT, period 5 = shootout. Playoffs
 * have no shootout — periods 5/6/7 are 2OT/3OT/4OT. Without the source's
 * periodType ("REG"/"OT"/"SO") we cannot tell those apart from the period
 * number alone, so callers should pass periodType when available.
 */

export function formatPeriodLabel(
  period: number,
  leagueCode: string,
  periodType?: string | null,
): string {
  const code = leagueCode.toUpperCase();

  if (code === "NHL") {
    if (period <= 3) return `P${period}`;
    if ((periodType ?? "").toUpperCase() === "SO") return "SO";
    const ot = period - 3;
    return ot === 1 ? "OT" : `${ot}OT`;
  }

  if (code === "MLB") {
    const ordinals: Record<number, string> = {1: "1st", 2: "2nd", 3: "3rd"};
    return ordinals[period] ?? `${period}th`;
  }

  if (code === "NCAAB") {
    if (period <= 2) return `H${period}`;
    const ot = period - 2;
    return ot === 1 ? "OT" : `${ot}OT`;
  }

  // NBA (default)
  if (period <= 4) return `Q${period}`;
  const ot = period - 4;
  return ot === 1 ? "OT" : `${ot}OT`;
}

/**
 * Format a period range label for blocks spanning multiple periods.
 * e.g. "Q1-Q2", "H1-H2", "P2-P3"
 */
export function formatPeriodRange(
  periodStart: number,
  periodEnd: number,
  leagueCode: string,
): string {
  if (periodStart === periodEnd) {
    return formatPeriodLabel(periodStart, leagueCode);
  }
  return `${formatPeriodLabel(periodStart, leagueCode)}–${formatPeriodLabel(periodEnd, leagueCode)}`;
}
