import { describe, expect, it } from "vitest";

describe("ci smoke", () => {
  it("runs in CI", () => {
    expect(1 + 1).toBe(2);
  });
});
