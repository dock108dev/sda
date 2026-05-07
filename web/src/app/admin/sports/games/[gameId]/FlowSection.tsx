"use client";

/**
 * Game Summary Section — Admin debugging view.
 *
 * Displays the v3-summary recap (3-5 paragraphs) for a completed game.
 * Pulls from GET /api/v1/games/{gameId}/summary.
 */

import { useCallback, useEffect, useState } from "react";
import { fetchGameSummary } from "@/lib/api/sportsAdmin";
import type {
  FlowStatusResponse,
  GameSummaryResponse,
} from "@/lib/api/sportsAdmin/gameFlowTypes";
import { CollapsibleSection } from "./CollapsibleSection";
import styles from "./styles.module.css";

type FlowSectionProps = {
  gameId: number;
  hasFlow: boolean;
  leagueCode: string;
  gameStatus: string;
};

function isFlowStatusResponse(
  r: GameSummaryResponse | FlowStatusResponse,
): r is FlowStatusResponse {
  return "status" in r && !("summary" in r);
}

export function FlowSection({ gameId, hasFlow, gameStatus }: FlowSectionProps) {
  const isFinal = gameStatus === "final";
  const [summary, setSummary] = useState<GameSummaryResponse | null>(null);
  const [pendingStatus, setPendingStatus] = useState<FlowStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGameSummary(gameId);
      if (data === null) {
        setError("Game not found");
      } else if (isFlowStatusResponse(data)) {
        setPendingStatus(data);
        setSummary(null);
      } else {
        setSummary(data);
        setPendingStatus(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load summary");
    } finally {
      setLoading(false);
    }
  }, [gameId]);

  useEffect(() => {
    if (hasFlow || isFinal) {
      loadSummary();
    }
  }, [hasFlow, isFinal, loadSummary]);

  if (!hasFlow && !isFinal) {
    return null;
  }

  return (
    <CollapsibleSection title="Game Summary" defaultOpen={true}>
      {loading && <div className={styles.subtle}>Loading summary...</div>}

      {error && <div className={styles.storyError}>Error: {error}</div>}

      {!loading && !error && pendingStatus && (
        <div className={styles.subtle}>
          {pendingStatus.status === "RECAP_PENDING" ? (
            <>
              Recap generating&hellip;
              {pendingStatus.etaMinutes != null && pendingStatus.etaMinutes > 0
                ? ` ETA: ~${pendingStatus.etaMinutes} min`
                : " (may be overdue)"}
            </>
          ) : (
            `Game is ${pendingStatus.status.replace("_", " ").toLowerCase()} — no recap yet.`
          )}
        </div>
      )}

      {!loading && !error && !summary && !pendingStatus && (
        <div className={styles.subtle}>No summary found.</div>
      )}

      {summary && (
        <div className={styles.storyContainer}>
          <div className={styles.storySummary}>
            {summary.summary.length} paragraphs · archetype:{" "}
            <strong>{summary.archetype ?? "unknown"}</strong> · model:{" "}
            {summary.modelUsed ?? "—"} · version: {summary.storyVersion}
          </div>
          <div className={styles.momentsList}>
            {summary.summary.map((paragraph, idx) => (
              <p key={idx} className={styles.momentNarrative}>
                {paragraph}
              </p>
            ))}
          </div>
          <div className={styles.subtle}>
            Final: {summary.finalScore.awayAbbr ?? "AWAY"}{" "}
            {summary.finalScore.away}, {summary.finalScore.homeAbbr ?? "HOME"}{" "}
            {summary.finalScore.home}
          </div>
          {summary.referencedPlayIds.length > 0 && (
            <div className={styles.subtle}>
              Referenced plays: {summary.referencedPlayIds.join(", ")}
            </div>
          )}
        </div>
      )}
    </CollapsibleSection>
  );
}
