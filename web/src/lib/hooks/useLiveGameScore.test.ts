import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLiveGameScore } from "./useLiveGameScore";

// ---------------------------------------------------------------------------
// Mock EventSource
// ---------------------------------------------------------------------------

class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0; // CONNECTING
  close = vi.fn(() => {
    this.readyState = 2;
  });

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  simulateOpen() {
    this.readyState = 1;
    act(() => {
      this.onopen?.();
    });
  }

  simulateMessage(data: object) {
    act(() => {
      this.onmessage?.({ data: JSON.stringify(data) });
    });
  }

  /** Raw SSE payload (not JSON) to exercise the parse error branch. */
  simulateRawMessage(data: string) {
    act(() => {
      this.onmessage?.({ data } as MessageEvent);
    });
  }

  simulateError() {
    this.readyState = 2;
    act(() => {
      this.onerror?.(new Event("error"));
    });
  }
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useLiveGameScore", () => {
  it("swallows errors from initial REST fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    renderHook(() => useLiveGameScore(42));
    MockEventSource.instances[0].simulateOpen();
    await act(async () => {
      await Promise.resolve();
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
    );
  });

  it("starts disconnected and creates an EventSource on mount", () => {
    const { result } = renderHook(() => useLiveGameScore(42));

    expect(result.current.isConnected).toBe(false);
    expect(MockEventSource.instances).toHaveLength(1);
    // URL-encodes colons: game%3A42%3Asummary
    expect(decodeURIComponent(MockEventSource.instances[0].url)).toContain("game:42:summary");
  });

  it("sets isConnected=true on open", () => {
    const { result } = renderHook(() => useLiveGameScore(42));
    MockEventSource.instances[0].simulateOpen();
    expect(result.current.isConnected).toBe(true);
  });

  it("updates score, clock, and status on game_patch event", () => {
    const { result } = renderHook(() => useLiveGameScore(42));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    es.simulateMessage({
      type: "game_patch",
      seq: 1,
      boot_epoch: "epoch-abc",
      score: { home: 3, away: 1 },
      clock: "10:23",
      status: "live",
    });

    expect(result.current.score).toEqual({ home: 3, away: 1 });
    expect(result.current.clock).toBe("10:23");
    expect(result.current.status).toBe("live");
    expect(result.current.isConnected).toBe(true);
  });

  it("ignores non-JSON SSE payloads", () => {
    const { result } = renderHook(() => useLiveGameScore(42));
    const es = MockEventSource.instances[0];
    es.simulateOpen();
    es.simulateRawMessage("not valid json{");
    expect(result.current.score).toBeNull();
  });

  it("stops scheduling reconnects after max attempts", () => {
    renderHook(() => useLiveGameScore(42));
    for (let n = 0; n < 20; n++) {
      const es = MockEventSource.instances[MockEventSource.instances.length - 1];
      es.simulateError();
      act(() => {
        vi.advanceTimersByTime(60_000);
      });
    }
    expect(MockEventSource.instances.length).toBeLessThanOrEqual(11);
  });

  it("ignores subscribed and unknown event types without throwing", () => {
    const { result } = renderHook(() => useLiveGameScore(42));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    es.simulateMessage({ type: "subscribed", channels: ["game:42:summary"] });
    es.simulateMessage({ type: "unknown_future_type" });

    expect(result.current.score).toBeNull();
  });

  it("reconnects with exponential backoff on error", () => {
    renderHook(() => useLiveGameScore(42));
    const es1 = MockEventSource.instances[0];

    es1.simulateOpen();
    es1.simulateError();

    expect(MockEventSource.instances).toHaveLength(1); // timer not yet fired

    act(() => {
      vi.advanceTimersByTime(1600); // first delay ~1000ms + jitter
    });

    expect(MockEventSource.instances).toHaveLength(2);
  });

  it("passes lastSeq and lastEpoch in reconnect URL", () => {
    renderHook(() => useLiveGameScore(42));
    const es1 = MockEventSource.instances[0];

    es1.simulateOpen();
    es1.simulateMessage({
      type: "game_patch",
      seq: 7,
      boot_epoch: "epoch-abc",
      score: { home: 1, away: 0 },
    });
    es1.simulateError();

    act(() => {
      vi.advanceTimersByTime(1600);
    });

    const url2 = MockEventSource.instances[1].url;
    expect(url2).toContain("lastSeq=7");
    expect(url2).toContain("lastEpoch=epoch-abc");
  });

  it("triggers full refetch on epoch_changed and clears lastSeq", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        score: { home: 5, away: 2 },
        clock: "Final",
        status: "final",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useLiveGameScore(42));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    // establish a seq first
    es.simulateMessage({
      type: "game_patch",
      seq: 3,
      boot_epoch: "epoch-old",
      score: { home: 1, away: 0 },
    });
    // server restart signalled
    es.simulateMessage({ type: "epoch_changed", epoch: "epoch-new" });

    await act(async () => {
      await Promise.resolve(); // flush microtasks (fetch)
    });

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/games/42"));
    expect(result.current.score).toEqual({ home: 5, away: 2 });
    expect(result.current.status).toBe("final");

    // After epoch_changed, reconnect should NOT include the stale seq
    es.simulateError();
    act(() => {
      vi.advanceTimersByTime(1600);
    });
    const url2 = MockEventSource.instances[1].url;
    expect(url2).not.toContain("lastSeq=");
    expect(url2).toContain("lastEpoch=epoch-new");
  });

  it("applies patch events in-place and triggers one refetch on phase_change", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        score: { home: 20, away: 15 },
        clock: "Q3",
        status: "live",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useLiveGameScore(42));
    const es = MockEventSource.instances[0];
    es.simulateOpen();

    // Emit 10 patch events — each should update score in-place, no refetch
    for (let i = 1; i <= 10; i++) {
      es.simulateMessage({
        type: "patch",
        seq: i,
        boot_epoch: "epoch-abc",
        score: { home: i, away: 0 },
        clock: `Q2 ${10 - i}:00`,
        status: "live",
      });
    }

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.score).toEqual({ home: 10, away: 0 });
    expect(result.current.clock).toBe("Q2 0:00");

    // Emit 1 phase_change — should trigger exactly 1 full refetch
    es.simulateMessage({
      type: "phase_change",
      seq: 11,
      boot_epoch: "epoch-abc",
      status: "live",
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/games/42"));
    // State updated from refetch
    expect(result.current.score).toEqual({ home: 20, away: 15 });
    expect(result.current.clock).toBe("Q3");
    // seq tracking preserved (not reset) after phase_change
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it("handles legacy game_patch events the same as patch", () => {
    const { result } = renderHook(() => useLiveGameScore(42));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    es.simulateMessage({
      type: "game_patch",
      seq: 1,
      boot_epoch: "epoch-abc",
      score: { home: 5, away: 3 },
      clock: "Q1 8:00",
      status: "live",
    });

    expect(result.current.score).toEqual({ home: 5, away: 3 });
    expect(result.current.clock).toBe("Q1 8:00");
  });

  it("cleans up EventSource and timers on unmount", () => {
    const { unmount } = renderHook(() => useLiveGameScore(42));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    es.simulateError(); // starts a reconnect timer

    unmount();

    // Timer cleared — no new EventSource after the delay
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(MockEventSource.instances).toHaveLength(1);
    expect(es.close).toHaveBeenCalled();
  });
});
