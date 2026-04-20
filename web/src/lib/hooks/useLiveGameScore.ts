import { useState, useEffect, useRef, useCallback } from "react";
import type { ScoreObject, GameStatus, LiveGameEvent } from "@dock108/js-core";

export type LiveGameScoreState = {
  score: ScoreObject | null;
  clock: string | null;
  status: GameStatus | null;
  isConnected: boolean;
};

const BASE_URL =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_SPORTS_API_URL) ||
  "http://localhost:8000";

const INITIAL_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;
const MAX_RECONNECT_ATTEMPTS = 10;

export function useLiveGameScore(gameId: string | number): LiveGameScoreState {
  const [score, setScore] = useState<ScoreObject | null>(null);
  const [clock, setClock] = useState<string | null>(null);
  const [status, setStatus] = useState<GameStatus | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  const lastSeqRef = useRef<number | null>(null);
  const lastEpochRef = useRef<string | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const fetchFullState = useCallback(async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/v1/games/${gameId}`);
      if (!res.ok || !mountedRef.current) return;
      const data = await res.json();
      if (!mountedRef.current) return;
      if (data.score != null) setScore(data.score as ScoreObject);
      if (data.clock != null) setClock(data.clock as string);
      if (data.status != null) setStatus(data.status as GameStatus);
    } catch {
      // network error during epoch-change refetch — will recover on next reconnect
    }
  }, [gameId]);

  const connect = useCallback(function connectImpl() {
    if (!mountedRef.current) return;

    const url = new URL(`${BASE_URL}/v1/sse`);
    url.searchParams.set("channels", `game:${gameId}:summary`);
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
    };

    es.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      let data: LiveGameEvent;
      try {
        data = JSON.parse(event.data as string) as LiveGameEvent;
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

      if (data.type === "phase_change") {
        // Game period/status transitioned: keep seq tracking, refetch full state
        if (data.seq !== undefined) lastSeqRef.current = data.seq;
        if (data.boot_epoch) lastEpochRef.current = data.boot_epoch;
        fetchFullState();
        return;
      }

      if (data.type === "patch" || data.type === "game_patch") {
        if (data.seq !== undefined) lastSeqRef.current = data.seq;
        if (data.boot_epoch) lastEpochRef.current = data.boot_epoch;
        if (data.score !== undefined) setScore(data.score);
        if (data.clock !== undefined) setClock(data.clock);
        if (data.status !== undefined) setStatus(data.status);
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

  return { score, clock, status, isConnected };
}
