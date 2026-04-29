import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@/lib/api/sseBase", () => ({
  getSseBaseUrl: () => "http://localhost/proxy",
  safeEventSource: () => null,
}));

vi.mock("@/lib/api/fairbet", () => ({
  fetchFairbetLiveOdds: vi.fn().mockResolvedValue({
    bets: [],
    total: 0,
    evDiagnostics: {},
    lastUpdatedAt: null,
  }),
}));

import { useLiveOdds } from "./useLiveOdds";

describe("useLiveOdds when EventSource is unavailable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("stays disconnected when safeEventSource returns null", () => {
    const { result } = renderHook(() => useLiveOdds(42));
    expect(result.current.isConnected).toBe(false);
  });
});
