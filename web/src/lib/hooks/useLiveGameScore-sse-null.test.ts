import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@/lib/api/sseBase", () => ({
  getSseBaseUrl: () => "http://localhost/proxy",
  safeEventSource: () => null,
}));

vi.mock("@/lib/api/apiBase", () => ({
  getApiBase: () => "/proxy",
}));

import { useLiveGameScore } from "./useLiveGameScore";

describe("useLiveGameScore when EventSource is unavailable", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ score: null, clock: null, status: null }),
      }),
    );
  });

  it("stays disconnected when safeEventSource returns null", () => {
    const { result } = renderHook(() => useLiveGameScore(77));
    expect(result.current.isConnected).toBe(false);
  });
});
