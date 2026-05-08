import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/constants/sports", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/constants/sports")>();
  return {
    ...actual,
    SCRAPE_RUN_STATUS_COLORS: {
      ...actual.SCRAPE_RUN_STATUS_COLORS,
      pending: undefined as unknown as string,
    },
  };
});

import { getStatusColor } from "./status";

describe("getStatusColor", () => {
  it("falls back to hard-coded gray when map and pending are unset", () => {
    expect(getStatusColor("totally_unknown_status")).toBe("#5f6368");
  });
});
