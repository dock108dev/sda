import { describe, expect, it } from "vitest";
import {
  ANALYTICS_SPORTS,
  SPORT_CONFIGS,
} from "./analytics";
import { ROUTES } from "./routes";
import { LEAGUE_SEGMENTS, SEGMENT_LABELS } from "./segments";
import {
  FAIRBET_LEAGUES,
  SCRAPE_RUN_STATUS_COLORS,
  SUPPORTED_LEAGUES,
} from "./sports";

describe("analytics constants", () => {
  it("lists analytics sports and configs", () => {
    expect(ANALYTICS_SPORTS.length).toBeGreaterThan(0);
    expect(SPORT_CONFIGS.NBA.scoringUnit).toBe("points");
    expect(SPORT_CONFIGS.NHL.hasGoalie).toBe(true);
  });
});

describe("routes", () => {
  it("builds path helpers", () => {
    expect(ROUTES.OVERVIEW).toBe("/admin");
    expect(ROUTES.SPORTS_GAME(42)).toBe("/admin/sports/games/42");
    expect(ROUTES.SPORTS_TEAM(9)).toBe("/admin/sports/teams/9");
    expect(ROUTES.GOLF_POOL("x")).toBe("/admin/golf/pools/x");
  });
});

describe("segments", () => {
  it("has league segments and labels", () => {
    expect(LEAGUE_SEGMENTS.NBA.length).toBeGreaterThan(0);
    expect(SEGMENT_LABELS.q1).toBe("Q1");
    expect(SEGMENT_LABELS.halftime).toBe("Halftime");
  });
});

describe("sports constants", () => {
  it("includes leagues and colors", () => {
    expect(SUPPORTED_LEAGUES).toContain("NBA");
    expect(FAIRBET_LEAGUES).toContain("MLB");
    expect(SCRAPE_RUN_STATUS_COLORS.success).toMatch(/^#/);
  });
});
