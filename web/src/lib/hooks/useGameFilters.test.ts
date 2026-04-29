import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useGameFilters } from "./useGameFilters";

const listGames = vi.fn();

vi.mock("@/lib/api/sportsAdmin", () => ({
  listGames: (...args: unknown[]) => listGames(...args),
}));

function makeGame(id: number): import("@/lib/api/sportsAdmin").GameSummary {
  return {
    id,
    leagueCode: "NBA",
    gameDate: "2026-04-01",
    homeTeam: "A",
    awayTeam: "B",
    score: null,
    hasBoxscore: true,
    hasPlayerStats: true,
    hasOdds: false,
    hasSocial: false,
    hasPbp: false,
    hasFlow: false,
    hasAdvancedStats: false,
    playCount: 0,
    socialPostCount: 0,
    scrapeVersion: null,
    lastScrapedAt: null,
    lastIngestedAt: null,
    lastPbpAt: null,
    lastSocialAt: null,
    lastOddsAt: null,
    lastAdvancedStatsAt: null,
    derivedMetrics: null,
    isLive: false,
    isFinal: true,
    isPregame: false,
  };
}

const response = {
  games: [] as import("@/lib/api/sportsAdmin").GameSummary[],
  total: 2,
  nextOffset: 50 as number | null,
  withBoxscoreCount: 1,
  withPlayerStatsCount: 1,
  withOddsCount: 0,
  withSocialCount: 0,
  withPbpCount: 0,
  withFlowCount: 0,
  withAdvancedStatsCount: 0,
};

describe("useGameFilters", () => {
  beforeEach(() => {
    listGames.mockResolvedValue(response);
    localStorage.clear();
  });

  it("ignores corrupt JSON in localStorage and keeps defaults", async () => {
    localStorage.setItem("gameFilters", "{invalid json");
    const { result } = renderHook(() => useGameFilters({ defaultLimit: 10 }));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.formFilters.team).toBe("");
    expect(listGames).toHaveBeenCalled();
  });

  it("loads games after hydration", async () => {
    const { result } = renderHook(() => useGameFilters({ defaultLimit: 10 }));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(listGames).toHaveBeenCalled();
    expect(result.current.total).toBe(2);
    expect(result.current.aggregates?.withBoxscore).toBe(1);
  });

  it("applyFilters saves and refetches", async () => {
    const { result } = renderHook(() => useGameFilters({ defaultLimit: 10 }));

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      result.current.applyFilters({
        ...result.current.formFilters,
        team: "LAL",
        offset: 0,
      });
    });

    await waitFor(() => {
      expect(listGames.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("applyFilters() with no argument uses current form state", async () => {
    const { result } = renderHook(() => useGameFilters({ defaultLimit: 10 }));

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      result.current.setFormFilters((prev) => ({ ...prev, team: "MIA" }));
    });

    await act(async () => {
      result.current.applyFilters();
    });

    await waitFor(() => expect(result.current.appliedFilters.team).toBe("MIA"));
  });

  it("toggleLeague adds and removes a code", async () => {
    const { result } = renderHook(() => useGameFilters());

    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.toggleLeague("NBA");
    });
    expect(result.current.formFilters.leagues).toContain("NBA");

    act(() => {
      result.current.toggleLeague("NBA");
    });
    expect(result.current.formFilters.leagues).not.toContain("NBA");
  });

  it("resetFilters restores defaults", async () => {
    localStorage.setItem(
      "gameFilters",
      JSON.stringify({ team: "XYZ", leagues: ["NBA"] }),
    );

    const { result } = renderHook(() => useGameFilters({ defaultLimit: 10 }));

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      result.current.resetFilters();
    });

    expect(result.current.formFilters.team).toBe("");
    expect(result.current.formFilters.leagues).toEqual([]);
  });

  it("surfaces API errors", async () => {
    listGames.mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(() => useGameFilters());

    await waitFor(() => {
      expect(result.current.error).toBe("network down");
    });
  });

  it("sets a generic error when listGames rejects with a non-Error", async () => {
    listGames.mockRejectedValueOnce("timeout");
    const { result } = renderHook(() => useGameFilters());

    await waitFor(() => {
      expect(result.current.error).toBe("Failed to load games");
    });
  });

  it("ignores listGames result after unmount", async () => {
    let resolveList!: (v: typeof response) => void;
    const pending = new Promise<typeof response>((r) => {
      resolveList = r;
    });
    listGames.mockReturnValueOnce(pending);

    const { result, unmount } = renderHook(() => useGameFilters());

    await waitFor(() => expect(result.current.loading).toBe(true));
    unmount();
    await act(async () => {
      resolveList(response);
      await Promise.resolve();
    });
  });

  it("ignores listGames rejection after unmount", async () => {
    let rejectList!: (e: Error) => void;
    const pending = new Promise<typeof response>((_, reject) => {
      rejectList = reject;
    });
    listGames.mockReturnValueOnce(pending);

    const { result, unmount } = renderHook(() => useGameFilters());

    await waitFor(() => expect(result.current.loading).toBe(true));
    unmount();
    await act(async () => {
      rejectList(new Error("aborted"));
      await Promise.resolve();
    });
  });

  it("applyFilters accepts explicit filter object including empty leagues", async () => {
    const { result } = renderHook(() => useGameFilters({ defaultLimit: 10 }));

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      result.current.applyFilters({
        ...result.current.formFilters,
        leagues: [],
        team: "BOS",
        offset: 0,
      });
    });

    await waitFor(() => expect(result.current.appliedFilters.team).toBe("BOS"));
  });

  it("applyFilters without loadMoreMode clears games list", async () => {
    listGames.mockResolvedValueOnce({
      ...response,
      games: [makeGame(1)],
      total: 1,
      nextOffset: null,
    });
    const { result } = renderHook(() => useGameFilters({ loadMoreMode: false }));

    await waitFor(() => expect(result.current.games.length).toBe(1));

    await act(async () => {
      result.current.applyFilters({ ...result.current.formFilters, offset: 0 });
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it("applyFilters tolerates localStorage setItem failures", async () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    const { result } = renderHook(() => useGameFilters());

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      result.current.applyFilters({ ...result.current.formFilters, offset: 0 });
    });

    spy.mockRestore();
  });

  it("loadMore does nothing when nextOffset is null", async () => {
    listGames.mockResolvedValue({ ...response, nextOffset: null });
    const { result } = renderHook(() => useGameFilters());

    await waitFor(() => expect(result.current.loading).toBe(false));
    const calls = listGames.mock.calls.length;

    await act(async () => {
      result.current.loadMore();
    });

    expect(listGames.mock.calls.length).toBe(calls);
  });

  it("loadMore bumps offset when nextOffset is set", async () => {
    const { result } = renderHook(() => useGameFilters({ loadMoreMode: true }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.nextOffset).toBe(50);

    listGames.mockResolvedValueOnce({
      ...response,
      games: [makeGame(1)],
      nextOffset: null,
    });

    await act(async () => {
      result.current.loadMore();
    });

    await waitFor(() => {
      expect(listGames.mock.calls.some((c) => (c[0] as { offset?: number }).offset === 50)).toBe(
        true,
      );
    });
  });

  it("appends games in loadMoreMode when offset advances", async () => {
    listGames
      .mockResolvedValueOnce({
        ...response,
        games: [makeGame(1)],
        total: 5,
        nextOffset: 25,
      })
      .mockResolvedValueOnce({
        ...response,
        games: [makeGame(2)],
        total: 5,
        nextOffset: null,
      });

    const { result } = renderHook(() => useGameFilters({ loadMoreMode: true, defaultLimit: 25 }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.games).toHaveLength(1);

    await act(async () => {
      result.current.loadMore();
    });

    await waitFor(() => expect(result.current.games.length).toBe(2));
    expect(result.current.games.map((g) => g.id)).toEqual([1, 2]);
  });
});
