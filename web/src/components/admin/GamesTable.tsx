"use client";

import { useState } from "react";
import Link from "next/link";
import { type GameSummary, resyncGame } from "@/lib/api/sportsAdmin";
import { ROUTES } from "@/lib/constants/routes";
import { deriveDataStatus, type DataField } from "@/lib/utils/dataStatus";
import { DataStatusIndicator } from "./DataStatusIndicator";
import styles from "./GamesTable.module.css";

interface GamesTableProps {
  games: GameSummary[];
  detailLink?: (id: number | string) => string;
  showCompleteness?: boolean;
}

/** Map of data field → accessor on GameSummary for the boolean + optional timestamp */
function getFieldStatus(game: GameSummary, field: DataField) {
  const tsMap: Record<DataField, string | null | undefined> = {
    boxscore: game.lastScrapedAt,
    playerStats: game.lastScrapedAt,
    odds: game.lastOddsAt,
    social: game.lastSocialAt,
    pbp: game.lastPbpAt,
    flow: game.lastScrapedAt,
    advancedStats: game.lastAdvancedStatsAt,
  };

  const hasMap: Record<DataField, boolean> = {
    boxscore: game.hasBoxscore,
    playerStats: game.hasPlayerStats,
    odds: game.hasOdds,
    social: game.hasSocial,
    pbp: game.hasPbp,
    flow: game.hasFlow,
    advancedStats: game.hasAdvancedStats,
  };

  return deriveDataStatus(field, hasMap[field], game.gameDate, tsMap[field]);
}

/**
 * Table component for displaying game summaries.
 * Shows game metadata and structured data status indicators.
 */
function isMissingCoreData(game: GameSummary): boolean {
  return !game.hasBoxscore || !game.hasPlayerStats || !game.hasOdds || !game.hasPbp || !game.hasAdvancedStats;
}

function ResyncButton({ gameId }: { gameId: number }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setState("loading");
    try {
      await resyncGame(gameId);
      setState("done");
    } catch {
      setState("error");
    }
  };

  if (state === "done") return <span style={{ color: "#16a34a", fontSize: "0.75rem" }}>Queued</span>;
  if (state === "error") return <span style={{ color: "#dc2626", fontSize: "0.75rem" }}>Failed</span>;

  return (
    <button
      onClick={handleClick}
      disabled={state === "loading"}
      style={{
        padding: "0.15rem 0.4rem",
        fontSize: "0.7rem",
        borderRadius: "4px",
        border: "1px solid #3b82f6",
        background: "transparent",
        color: "#3b82f6",
        cursor: state === "loading" ? "wait" : "pointer",
        whiteSpace: "nowrap",
      }}
    >
      {state === "loading" ? "..." : "Sync"}
    </button>
  );
}

export function GamesTable({ games, detailLink = ROUTES.SPORTS_GAME, showCompleteness = true }: GamesTableProps) {
  return (
    <>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>ID</th>
            <th>Date</th>
            <th>League</th>
            <th>Teams</th>
            {showCompleteness && (
              <>
                <th>Boxscore</th>
                <th>Players</th>
                <th>Odds</th>
                <th>Social</th>
                <th>PBP</th>
                <th>Flow</th>
                <th>Adv Stats</th>
                <th></th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {games.length === 0 ? (
            <tr>
                <td colSpan={showCompleteness ? 12 : 4} className={styles.emptyCell}>
                No games found
              </td>
            </tr>
          ) : (
            games.map((game) => {
              const gameId = game.id;
              const hasValidId = gameId !== undefined && gameId !== null;
              const missing = isMissingCoreData(game);
              const idContent = hasValidId ? (
                <Link href={detailLink(gameId)} className={styles.link}>
                  {gameId}
                  </Link>
              ) : (
                "—"
              );

              return (
              <tr key={gameId ?? `${game.awayTeam}-${game.homeTeam}-${game.gameDate}`}>
                <td>{idContent}</td>
                <td>{new Date(game.gameDate).toLocaleString()}</td>
                <td>{game.leagueCode}</td>
                <td>
                  {game.awayTeam} @ {game.homeTeam}
                </td>
                {showCompleteness && (
                  <>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "boxscore")} />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "playerStats")} />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "odds")} />
                    </td>
                    <td>
                      <DataStatusIndicator
                        status={getFieldStatus(game, "social")}
                        count={game.socialPostCount}
                      />
                    </td>
                    <td>
                      <DataStatusIndicator
                        status={getFieldStatus(game, "pbp")}
                        count={game.playCount}
                      />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "flow")} />
                    </td>
                    <td>
                      <DataStatusIndicator status={getFieldStatus(game, "advancedStats")} />
                    </td>
                    <td>
                      {hasValidId && missing ? <ResyncButton gameId={gameId} /> : null}
                    </td>
                  </>
                )}
              </tr>
            )})
          )}
        </tbody>
      </table>
    </>
  );
}
