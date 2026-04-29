import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  formatDate,
  formatDateTime,
  formatDateRange,
  formatDateInput,
  getDateDaysAgo,
  getQuickDateRange,
} from "./dateFormat";
import {
  formatMetricName,
  formatMetricValue,
  fmtPct,
  fmtNum,
} from "./formatting";
import {
  getStatusClass,
  getStatusColor,
  getStatusLabel,
} from "./status";
import {
  formatPeriodLabel,
  formatPeriodRange,
} from "./periodLabels";
import {
  getFullSeasonDates,
  shouldAutoFillDates,
} from "./seasonDates";
import type { LeagueCode } from "@/lib/constants/sports";
import { deriveDataStatus } from "./dataStatus";
import * as UtilsBarrel from "./index";

describe("dateFormat", () => {
  it("formats dates and datetimes", () => {
    expect(formatDate("2024-06-01")).toMatch(/2024|Jun|6|01/);
    expect(formatDate(new Date(Date.UTC(2024, 5, 1)))).toMatch(/2024|Jun/);
    expect(formatDateTime("2024-06-01T14:30:00Z")).toMatch(/2024|Jun/);
  });

  it("formats date ranges and input helpers", () => {
    expect(formatDateRange(undefined, undefined)).toBe("—");
    expect(formatDateRange(null, "2024-01-01")).toContain("?");
    expect(formatDateRange("2024-01-01", null)).toContain("?");
    expect(formatDateRange("2024-01-01", "2024-01-02")).toContain("→");

    const d = new Date(Date.UTC(2024, 2, 15));
    expect(formatDateInput(d)).toBe("2024-03-15");
    expect(formatDateInput("2024-03-15")).toBe("2024-03-15");

    vi.useFakeTimers();
    vi.setSystemTime(new Date(Date.UTC(2025, 0, 10, 12, 0, 0)));
    expect(getDateDaysAgo(3).toISOString().slice(0, 10)).toBe("2025-01-07");
    const quick = getQuickDateRange(7);
    expect(quick.startDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(quick.endDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    vi.useRealTimers();
  });
});

describe("formatting", () => {
  it("formats metric names and values", () => {
    expect(formatMetricName("contact_rate")).toBe("Contact Rate");
    expect(formatMetricValue(12.345)).toBe("12.3");
    expect(formatMetricValue(3.14159)).toBe("3.1416");
    expect(fmtPct(0.423)).toBe("42.3%");
    expect(fmtPct(null)).toBe("—");
    expect(fmtNum(3.14, 2)).toBe("3.14");
    expect(fmtNum(undefined)).toBe("—");
  });
});

describe("status", () => {
  it("maps status to class, color, and label", () => {
    expect(getStatusClass("success")).toBe("runStatusSuccess");
    expect(getStatusClass("pending")).toBe("runStatusPending");
    expect(getStatusClass("running")).toBe("runStatusRunning");
    expect(getStatusClass("error")).toBe("runStatusError");
    expect(getStatusClass("interrupted")).toBe("runStatusInterrupted");
    expect(getStatusClass("unknown")).toBe("runStatusPending");

    expect(getStatusColor("success")).toMatch(/^#/);
    expect(getStatusColor("not_a_key")).toBeTruthy();

    expect(getStatusLabel("success")).toBe("Success");
    expect(getStatusLabel("pending")).toBe("Pending");
    expect(getStatusLabel("running")).toBe("Running");
    expect(getStatusLabel("error")).toBe("Error");
    expect(getStatusLabel("interrupted")).toBe("Interrupted");
    expect(getStatusLabel("custom")).toBe("Custom");
  });
});

describe("periodLabels", () => {
  it("formats NHL, MLB, NCAAB, NBA periods", () => {
    expect(formatPeriodLabel(2, "NHL")).toBe("P2");
    expect(formatPeriodLabel(4, "NHL")).toBe("OT");
    expect(formatPeriodLabel(6, "NHL")).toBe("3OT");
    expect(formatPeriodLabel(5, "NHL", "SO")).toBe("SO");
    expect(formatPeriodLabel(2, "MLB")).toBe("2nd");
    expect(formatPeriodLabel(4, "MLB")).toBe("4th");
    expect(formatPeriodLabel(1, "NCAAB")).toBe("H1");
    expect(formatPeriodLabel(3, "NCAAB")).toBe("OT");
    expect(formatPeriodLabel(5, "NCAAB")).toBe("3OT");
    expect(formatPeriodLabel(4, "NBA")).toBe("Q4");
    expect(formatPeriodLabel(5, "NBA")).toBe("OT");
    expect(formatPeriodLabel(6, "NBA")).toBe("2OT");
    expect(formatPeriodRange(1, 2, "NBA")).toContain("–");
    expect(formatPeriodRange(3, 3, "NBA")).toBe("Q3");
  });
});

describe("seasonDates", () => {
  it("returns season windows per league", () => {
    expect(getFullSeasonDates("MLB", 2024).startDate).toContain("2024-03");
    expect(getFullSeasonDates("NBA", 2024).endDate).toContain("2025-06");
    expect(getFullSeasonDates("NFL", 2024).startDate).toContain("2024-09");
    expect(getFullSeasonDates("NHL", 2024).startDate).toContain("2024-10");
    expect(getFullSeasonDates("NCAAB", 2024).startDate).toContain("2024-11");
    expect(getFullSeasonDates("NCAAF", 2024).startDate).toContain("2024-08");
    expect(getFullSeasonDates("PGA" as LeagueCode, 2024).startDate).toContain("2024-01");
    expect(shouldAutoFillDates("NBA", "2024", "", "")).toBe(true);
    expect(shouldAutoFillDates("NBA", "", "x", "")).toBe(false);
  });
});

describe("deriveDataStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-15T18:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("handles future games and missing data", () => {
    expect(deriveDataStatus("boxscore", false, "2099-01-01").status).toBe("not_applicable");
    expect(deriveDataStatus("odds", false, "2099-01-01").status).toBe("missing");
    expect(deriveDataStatus("boxscore", false, "2026-04-10").status).toBe("missing");
  });

  it("detects stale vs present for in-progress window", () => {
    const gameToday = "2026-04-15";
    const oldTs = "2026-04-01T12:00:00Z";
    const stale = deriveDataStatus("boxscore", true, gameToday, oldTs);
    expect(stale.status).toBe("stale");
    expect(stale.reason).toContain("ago");

    const fresh = deriveDataStatus("boxscore", true, gameToday, "2026-04-15T12:00:00Z");
    expect(fresh.status).toBe("present");

    // odds: 1-day staleness — timestamp far enough back triggers stale + day-based "ago" text
    const staleOdds = deriveDataStatus("odds", true, gameToday, "2026-04-12T12:00:00Z");
    expect(staleOdds.status).toBe("stale");
    expect(staleOdds.reason).toMatch(/\d+d ago/);
  });

  it("does not flag stale for completed games", () => {
    const pastGame = "2025-12-01";
    const oldTs = "2025-12-02T12:00:00Z";
    const r = deriveDataStatus("boxscore", true, pastGame, oldTs);
    expect(r.status).toBe("present");
  });
});

describe("utils barrel", () => {
  it("re-exports helpers", () => {
    expect(UtilsBarrel.formatMetricName("x_y")).toBe("X Y");
    expect(UtilsBarrel.formatPeriodLabel(1, "NBA")).toBe("Q1");
  });
});
