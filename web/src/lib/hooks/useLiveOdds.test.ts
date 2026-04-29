import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLiveOdds } from "./useLiveOdds";
import type { OddsSnapshot } from "@dock108/js-core";
import * as fairbet from "@/lib/api/fairbet";

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
// Helpers
// ---------------------------------------------------------------------------

function makeSnapshot(overrides: Partial<OddsSnapshot> = {}): OddsSnapshot {
  return {
    gameId: 99,
    leagueCode: "NBA",
    homeTeam: "Lakers",
    awayTeam: "Celtics",
    gameDate: "2026-04-19T20:00:00Z",
    marketKey: "h2h",
    selectionKey: "team:lakers",
    lineValue: 0,
    marketCategory: "mainline",
    playerName: null,
    description: null,
    trueProb: 0.52,
    referencePrice: -110,
    oppositeReferencePrice: -110,
    estimatedSharpPrice: null,
    extrapolationRefLine: null,
    extrapolationDistance: null,
    consensusBookCount: null,
    consensusIqr: null,
    perBookFairProbs: null,
    books: [
      {
        book: "DraftKings",
        price: -108,
        evPercent: 1.2,
        displayEv: 1.2,
        impliedProb: 0.519,
        isSharp: false,
        evMethod: "shin",
        evConfidenceTier: "medium",
      },
    ],
    evMethod: "shin",
    evConfidenceTier: "medium",
    evDisabledReason: null,
    hasFair: true,
    confidence: null,
    confidenceFlags: [],
    ...overrides,
  };
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

describe("useLiveOdds", () => {
  it("swallows errors from initial fetchFairbetLiveOdds", async () => {
    vi.spyOn(fairbet, "fetchFairbetLiveOdds").mockRejectedValueOnce(new Error("offline"));
    renderHook(() => useLiveOdds(99));
    MockEventSource.instances[0].simulateOpen();
    await act(async () => {
      await Promise.resolve();
    });
  });

  it("starts disconnected and subscribes to fairbet:odds channel", () => {
    const { result } = renderHook(() => useLiveOdds(99));

    expect(result.current.isConnected).toBe(false);
    expect(result.current.odds).toHaveLength(0);
    expect(result.current.evAnalysis).toBeNull();
    expect(MockEventSource.instances).toHaveLength(1);
    expect(decodeURIComponent(MockEventSource.instances[0].url)).toContain("fairbet:odds");
  });

  it("sets isConnected=true on open and fetches initial state", async () => {
    const snapshot = makeSnapshot();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        bets: [snapshot],
        total: 1,
        evDiagnostics: { positive_ev_bets: 1 },
        lastUpdatedAt: "2026-04-19T20:05:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];

    await act(async () => {
      es.simulateOpen();
      await Promise.resolve();
    });

    expect(result.current.isConnected).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("game_id=99"),
      expect.anything(),
    );
    expect(result.current.odds).toHaveLength(1);
    expect(result.current.evAnalysis).not.toBeNull();
    expect(result.current.evAnalysis?.gameId).toBe(99);
    expect(result.current.evAnalysis?.totalBets).toBe(1);
  });

  it("updates odds on fairbet_patch event for the correct gameId", () => {
    const { result } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    const bets = [makeSnapshot({ trueProb: 0.55 })];

    es.simulateMessage({
      type: "fairbet_patch",
      gameId: 99,
      seq: 1,
      boot_epoch: "epoch-abc",
      bets,
      total: 1,
      evDiagnostics: { positive_ev_bets: 1 },
      lastUpdatedAt: "2026-04-19T20:06:00Z",
    });

    expect(result.current.odds).toHaveLength(1);
    expect(result.current.odds[0].trueProb).toBe(0.55);
    expect(result.current.evAnalysis?.totalBets).toBe(1);
    expect(result.current.evAnalysis?.positiveEvCount).toBe(1);
  });

  it("ignores fairbet_patch events for a different gameId", () => {
    const { result } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    es.simulateMessage({
      type: "fairbet_patch",
      gameId: 777, // different game
      seq: 1,
      boot_epoch: "epoch-abc",
      bets: [makeSnapshot({ gameId: 777 })],
      total: 1,
      evDiagnostics: {},
      lastUpdatedAt: null,
    });

    expect(result.current.odds).toHaveLength(0);
  });

  it("ignores non-JSON SSE payloads", () => {
    const { result } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];
    es.simulateOpen();
    es.simulateRawMessage("{{{");
    expect(result.current.odds).toHaveLength(0);
  });

  it("ignores subscribed and unknown event types without throwing", () => {
    const { result } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    es.simulateMessage({ type: "subscribed", channels: ["fairbet:odds"] });
    es.simulateMessage({ type: "unknown_future_type" });

    expect(result.current.odds).toHaveLength(0);
  });

  it("reconnects with exponential backoff on error", () => {
    renderHook(() => useLiveOdds(99));
    const es1 = MockEventSource.instances[0];

    es1.simulateOpen();
    es1.simulateError();

    expect(MockEventSource.instances).toHaveLength(1); // timer not yet fired

    act(() => {
      vi.advanceTimersByTime(1600);
    });

    expect(MockEventSource.instances).toHaveLength(2);
  });

  it("passes lastSeq and lastEpoch in reconnect URL", () => {
    renderHook(() => useLiveOdds(99));
    const es1 = MockEventSource.instances[0];

    es1.simulateOpen();
    es1.simulateMessage({
      type: "fairbet_patch",
      gameId: 99,
      seq: 5,
      boot_epoch: "epoch-xyz",
      bets: [makeSnapshot()],
      total: 1,
      evDiagnostics: {},
      lastUpdatedAt: null,
    });
    es1.simulateError();

    act(() => {
      vi.advanceTimersByTime(1600);
    });

    const url2 = MockEventSource.instances[1].url;
    expect(url2).toContain("lastSeq=5");
    expect(url2).toContain("lastEpoch=epoch-xyz");
  });

  it("triggers full refetch on epoch_changed and clears lastSeq", async () => {
    const bets = [makeSnapshot()];
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        bets,
        total: 1,
        evDiagnostics: {},
        lastUpdatedAt: "2026-04-19T21:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];

    es.simulateOpen();

    await act(async () => {
      await Promise.resolve(); // flush initial fetchFullState
    });
    fetchMock.mockClear();

    es.simulateMessage({
      type: "fairbet_patch",
      gameId: 99,
      seq: 3,
      boot_epoch: "epoch-old",
      bets: [],
      total: 0,
      evDiagnostics: {},
      lastUpdatedAt: null,
    });

    es.simulateMessage({ type: "epoch_changed", epoch: "epoch-new" });

    await act(async () => {
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("game_id=99"),
      expect.anything(),
    );
    expect(result.current.odds).toHaveLength(1);

    // After epoch_changed, reconnect should NOT include the stale seq
    es.simulateError();
    act(() => {
      vi.advanceTimersByTime(1600);
    });
    const url2 = MockEventSource.instances[1].url;
    expect(url2).not.toContain("lastSeq=");
    expect(url2).toContain("lastEpoch=epoch-new");
  });

  it("computes evAnalysis positiveEvCount correctly", () => {
    const { result } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    const bets = [
      makeSnapshot({ books: [{ book: "DK", price: -105, evPercent: 2.1, displayEv: 2.1, impliedProb: 0.512, isSharp: false, evMethod: null, evConfidenceTier: null }] }),
      makeSnapshot({ books: [{ book: "FD", price: -115, evPercent: -1.5, displayEv: -1.5, impliedProb: 0.535, isSharp: false, evMethod: null, evConfidenceTier: null }] }),
    ];

    es.simulateMessage({
      type: "fairbet_patch",
      gameId: 99,
      seq: 2,
      boot_epoch: "epoch-abc",
      bets,
      total: 2,
      evDiagnostics: {},
      lastUpdatedAt: null,
    });

    expect(result.current.evAnalysis?.positiveEvCount).toBe(1);
    expect(result.current.evAnalysis?.maxEv).toBeCloseTo(2.1);
  });

  it("cleans up EventSource and timers on unmount", () => {
    const { unmount } = renderHook(() => useLiveOdds(99));
    const es = MockEventSource.instances[0];

    es.simulateOpen();
    es.simulateError(); // starts a reconnect timer

    unmount();

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(MockEventSource.instances).toHaveLength(1);
    expect(es.close).toHaveBeenCalled();
  });
});
