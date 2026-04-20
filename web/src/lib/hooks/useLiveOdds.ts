import { useState, useEffect, useRef, useCallback } from "react";
import type { OddsSnapshot, EVAnalysis, FairbetOddsEvent } from "@dock108/js-core";

export type LiveOddsState = {
  odds: OddsSnapshot[];
  evAnalysis: EVAnalysis | null;
  isConnected: boolean;
};

const BASE_URL =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_SPORTS_API_URL) ||
  "http://localhost:8000";

const INITIAL_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;
const MAX_RECONNECT_ATTEMPTS = 10;

function computeEvAnalysis(
  gameId: number,
  bets: OddsSnapshot[],
  evDiagnostics: Record<string, number>,
  lastUpdatedAt: string | null,
): EVAnalysis {
  let maxEv: number | null = null;
  let positiveEvCount = 0;
  for (const bet of bets) {
    for (const book of bet.books) {
      const ev = book.displayEv ?? book.evPercent ?? null;
      if (ev === null) continue;
      if (ev > 0) positiveEvCount++;
      if (maxEv === null || ev > maxEv) maxEv = ev;
    }
  }
  return {
    gameId,
    totalBets: bets.length,
    positiveEvCount,
    maxEv,
    lastUpdatedAt,
    diagnostics: evDiagnostics,
  };
}

export function useLiveOdds(gameId: string | number): LiveOddsState {
  const [odds, setOdds] = useState<OddsSnapshot[]>([]);
  const [evAnalysis, setEvAnalysis] = useState<EVAnalysis | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  const lastSeqRef = useRef<number | null>(null);
  const lastEpochRef = useRef<string | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const fetchFullState = useCallback(async () => {
    try {
      const res = await fetch(
        `${BASE_URL}/api/fairbet/live?game_id=${gameId}`,
      );
      if (!res.ok || !mountedRef.current) return;
      const data = await res.json();
      if (!mountedRef.current) return;
      if (Array.isArray(data.bets)) {
        const bets = data.bets as OddsSnapshot[];
        setOdds(bets);
        setEvAnalysis(
          computeEvAnalysis(
            Number(gameId),
            bets,
            (data.evDiagnostics as Record<string, number>) ?? {},
            (data.lastUpdatedAt as string | null) ?? null,
          ),
        );
      }
    } catch {
      // network error during epoch-change refetch — will recover on next reconnect
    }
  }, [gameId]);

  const connect = useCallback(function connectImpl() {
    if (!mountedRef.current) return;

    const url = new URL(`${BASE_URL}/v1/sse`);
    url.searchParams.set("channels", "fairbet:odds");
    if (lastSeqRef.current !== null) {
      url.searchParams.set("lastSeq", String(lastSeqRef.current));
    }
    if (lastEpochRef.current !== null) {
      url.searchParams.set("lastEpoch", lastEpochRef.current);
    }

    const es = new EventSource(url.toString());
    esRef.current = es;

    es.onopen = () => {
      if (!mountedRef.current) return;
      setIsConnected(true);
      attemptRef.current = 0;
      // Fetch current state on connect; SSE delivers patches thereafter
      fetchFullState();
    };

    es.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      let data: FairbetOddsEvent;
      try {
        data = JSON.parse(event.data as string) as FairbetOddsEvent;
      } catch {
        return;
      }

      if (data.type === "epoch_changed") {
        // Server restarted: discard stale seq, refetch full state
        lastSeqRef.current = null;
        lastEpochRef.current = data.epoch ?? null;
        fetchFullState();
        return;
      }

      if (
        data.type === "fairbet_patch" &&
        data.gameId === Number(gameId) &&
        Array.isArray(data.bets)
      ) {
        if (data.seq !== undefined) lastSeqRef.current = data.seq;
        if (data.boot_epoch) lastEpochRef.current = data.boot_epoch;
        const bets = data.bets;
        setOdds(bets);
        setEvAnalysis(
          computeEvAnalysis(
            Number(gameId),
            bets,
            data.evDiagnostics ?? {},
            data.lastUpdatedAt ?? null,
          ),
        );
      }
    };

    es.onerror = () => {
      if (!mountedRef.current) return;
      setIsConnected(false);
      es.close();

      if (attemptRef.current >= MAX_RECONNECT_ATTEMPTS) return;

      // Exponential backoff with jitter to avoid thundering herd
      const delay = Math.min(
        INITIAL_DELAY_MS * 2 ** attemptRef.current + Math.random() * 500,
        MAX_DELAY_MS,
      );
      attemptRef.current += 1;
      timerRef.current = setTimeout(connectImpl, delay);
    };
  }, [gameId, fetchFullState]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      esRef.current?.close();
    };
  }, [connect]);

  return { odds, evAnalysis, isConnected };
}
