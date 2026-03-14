import { useState, useEffect, useCallback } from "react";
import { GameSummary, GameFilters, listGames } from "@/lib/api/sportsAdmin";
import { formatDateInput } from "@/lib/utils/dateFormat";

/** Build default filters with 7-day window ending yesterday and finalOnly. */
function getDefaultGameFilters(limit = 25): GameFilters {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(today.getDate() - 7);

  return {
    leagues: [],
    season: undefined,
    team: "",
    startDate: formatDateInput(weekAgo),
    endDate: formatDateInput(yesterday),
    missingBoxscore: false,
    missingPlayerStats: false,
    missingOdds: false,
    missingSocial: false,
    missingAny: false,
    finalOnly: true,
    limit,
    offset: 0,
  };
}

const STORAGE_KEY = "gameFilters";

function loadSavedFilters(defaultLimit: number): GameFilters | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as Partial<GameFilters>;
    // Merge saved values over defaults, reset offset to 0
    return { ...getDefaultGameFilters(defaultLimit), ...saved, offset: 0 };
  } catch {
    return null;
  }
}

function saveFilters(filters: GameFilters) {
  if (typeof window === "undefined") return;
  try {
    // Persist everything except offset
    const { offset: _, ...rest } = filters;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(rest));
  } catch {
    // localStorage unavailable — ignore
  }
}

export const DEFAULT_GAME_FILTERS: GameFilters = getDefaultGameFilters();

interface UseGameFiltersOptions {
  defaultLimit?: number;
  loadMoreMode?: boolean;
}

interface UseGameFiltersReturn {
  formFilters: GameFilters;
  setFormFilters: React.Dispatch<React.SetStateAction<GameFilters>>;
  appliedFilters: GameFilters;
  games: GameSummary[];
  total: number;
  nextOffset: number | null;
  aggregates: {
    withBoxscore: number;
    withPlayerStats: number;
    withOdds: number;
    withSocial: number;
    withPbp: number;
    withFlow: number;
    withAdvancedStats: number;
  } | null;
  loading: boolean;
  error: string | null;
  applyFilters: (nextFilters?: GameFilters) => void;
  resetFilters: () => void;
  loadMore: () => void;
  toggleLeague: (code: string) => void;
}

/**
 * Shared hook for game filtering and data loading.
 * Handles form state, applied filters, API calls, and pagination.
 */
export function useGameFilters(options: UseGameFiltersOptions = {}): UseGameFiltersReturn {
  const { defaultLimit = 25, loadMoreMode = false } = options;
  
  const [formFilters, setFormFilters] = useState<GameFilters>(() =>
    loadSavedFilters(defaultLimit) ?? getDefaultGameFilters(defaultLimit),
  );
  const [appliedFilters, setAppliedFilters] = useState<GameFilters>(() =>
    loadSavedFilters(defaultLimit) ?? getDefaultGameFilters(defaultLimit),
  );
  const [games, setGames] = useState<GameSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [aggregates, setAggregates] = useState<{
    withBoxscore: number;
    withPlayerStats: number;
    withOdds: number;
    withPbp: number;
    withSocial: number;
    withFlow: number;
    withAdvancedStats: number;
  } | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await listGames(appliedFilters);
        if (cancelled) return;
        
        if (loadMoreMode && appliedFilters.offset && appliedFilters.offset > 0) {
          setGames((prev) => [...prev, ...response.games]);
        } else {
          setGames(response.games);
        }
        
        setTotal(response.total);
        setAggregates({
          withBoxscore: response.withBoxscoreCount ?? 0,
          withPlayerStats: response.withPlayerStatsCount ?? 0,
          withOdds: response.withOddsCount ?? 0,
          withSocial: response.withSocialCount ?? 0,
          withPbp: response.withPbpCount ?? 0,
          withFlow: response.withFlowCount ?? 0,
          withAdvancedStats: response.withAdvancedStatsCount ?? 0,
        });
        setNextOffset(response.nextOffset);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load games");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [appliedFilters, loadMoreMode]);

  const applyFilters = useCallback(
    (nextFilters?: GameFilters) => {
      const filtersToApply: GameFilters = nextFilters
        ? { ...nextFilters, leagues: nextFilters.leagues ?? [] }
        : { ...formFilters, leagues: formFilters.leagues ?? [], offset: 0 };
      setAppliedFilters(filtersToApply);
      saveFilters(filtersToApply);
    if (!loadMoreMode) {
      setGames([]);
    }
      setAggregates(null);
    },
    [formFilters, loadMoreMode],
  );

  const resetFilters = useCallback(() => {
    const defaultFilters = getDefaultGameFilters(defaultLimit);
    setFormFilters(defaultFilters);
    setAppliedFilters(defaultFilters);
    setGames([]);
    setAggregates(null);
    saveFilters(defaultFilters);
  }, [defaultLimit]);

  const loadMore = useCallback(() => {
    if (nextOffset === null) return;
    setAppliedFilters((prev) => ({ ...prev, offset: nextOffset }));
  }, [nextOffset]);

  const toggleLeague = useCallback((code: string) => {
    setFormFilters((prev) => {
      const exists = prev.leagues.includes(code);
      return {
        ...prev,
        leagues: exists ? prev.leagues.filter((lg) => lg !== code) : [...prev.leagues, code],
      };
    });
  }, []);

  return {
    formFilters,
    setFormFilters,
    appliedFilters,
    games,
    total,
    aggregates,
    nextOffset,
    loading,
    error,
    applyFilters,
    resetFilters,
    loadMore,
    toggleLeague,
  };
}

